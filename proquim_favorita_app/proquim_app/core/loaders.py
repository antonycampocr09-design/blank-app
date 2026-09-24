"""
Carga y normalización de TODAS las fuentes de datos.

Esquemas normalizados que devuelve este módulo (todas las fuentes terminan aquí):

  pedidos      -> fecha (datetime), codigo (str), producto (str), cajas (float),
                  [local, orden] opcionales, fuente (str)
  existencias  -> fecha (datetime), codigo (str), producto (str), categoria (str),
                  unid_caja (float), exist_unid (float), exist_cajas (float), fuente (str)
  productos    -> codigo, producto, categoria, marca, presentacion, estado
"""
from __future__ import annotations

import datetime as dt
import glob
import io
import os
import re
from typing import Iterable

import numpy as np
import pandas as pd
import openpyxl

# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
_BARCODE_RE = re.compile(r"^\d{6,14}$")
_FNAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[_ T](\d{2})[-:](\d{2}))?")

MARCAS = ["7 AYUDAS", "GARZA", "DISH LAV", "ISLY", "TEEPOL", "PET", "DISPLAY"]


def norm_code(v) -> str | None:
    """Convierte cualquier representación de un código de barras a str limpio."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return str(int(round(v)))
    s = str(v).strip().replace(" ", "")
    if s.endswith(".0"):
        s = s[:-2]
    # notación científica de Sheets: 7.86102E+12
    if re.match(r"^\d+(\.\d+)?[eE]\+\d+$", s):
        try:
            s = str(int(float(s)))
        except ValueError:
            pass
    return s if _BARCODE_RE.match(s) else None


def to_num(v) -> float:
    if v is None:
        return np.nan
    if isinstance(v, (int, float, np.number)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if s in ("", "-", "—"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def marca_de(nombre: str) -> str:
    n = (nombre or "").upper().strip()
    for m in MARCAS:
        if m in n[: len(m) + 6]:
            return "PET" if m == "PET" else m
    if "POTENCIADOR" in n:
        return "GARZA"
    return "OTRAS"


def fecha_de_nombre(nombre: str) -> dt.datetime | None:
    m = _FNAME_DATE_RE.search(os.path.basename(nombre or ""))
    if not m:
        return None
    d = dt.datetime.strptime(m.group(1), "%Y-%m-%d")
    if m.group(2):
        d = d.replace(hour=int(m.group(2)), minute=int(m.group(3)))
    return d


def parse_fecha(s: pd.Series) -> pd.Series:
    """Fechas de Sheets/Excel: texto dd/mm/aaaa, ISO o número serial (1899-12-30)."""
    num = pd.to_numeric(s, errors="coerce")
    serial = pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce").where(num.between(20000, 80000))
    txt = pd.to_datetime(s.where(num.isna()).astype("string"), errors="coerce", dayfirst=True, format="mixed")
    return serial.fillna(txt)


def _open_wb(src):
    """src puede ser ruta, bytes o un UploadedFile de Streamlit."""
    if isinstance(src, (str, os.PathLike)):
        return openpyxl.load_workbook(src, data_only=True, read_only=False)
    if hasattr(src, "getvalue"):
        return openpyxl.load_workbook(io.BytesIO(src.getvalue()), data_only=True)
    if isinstance(src, (bytes, bytearray)):
        return openpyxl.load_workbook(io.BytesIO(src), data_only=True)
    return openpyxl.load_workbook(src, data_only=True)


# ----------------------------------------------------------------------------
# 1) Reporte de Existencias Diarias (lo que descarga el bot de La Favorita)
# ----------------------------------------------------------------------------
def parse_existencias(src, nombre: str | None = None, fecha: dt.datetime | None = None) -> pd.DataFrame:
    """
    Lee el Excel 'N1.R.03 - Existencias Diarias' (ya limpio por el bot o crudo).

    Columnas (relativas a la columna del proveedor '7978-PROQUIM S.A.'):
      +0 proveedor | +1 categoría | +2 subcategoría | +3 código barras | +4 descripción
      +5 estado    | +6 presentación | +7 cód. interno | +8 unid/caja | +9 exist. unidades
      +10 exist. CAJAS | +11 pendiente/tránsito
    """
    nombre = nombre or getattr(src, "name", None) or (src if isinstance(src, str) else "")
    fecha = fecha or fecha_de_nombre(nombre) or dt.datetime.now()
    wb = _open_wb(src)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # detectar columna del proveedor (sirve para archivo crudo o limpio)
    off = 0
    for r in rows[:40]:
        for j, v in enumerate(r):
            if isinstance(v, str) and "PROQUIM" in v.upper():
                off = j
                break
        else:
            continue
        break

    out, cat, subcat = [], None, None
    for r in rows:
        r = list(r) + [None] * 16
        c = r[off:off + 13]
        if c[1]:
            cat = str(c[1]).strip()
        if c[2]:
            subcat = str(c[2]).strip()
        code = norm_code(c[3])
        if not code:
            continue
        cajas = to_num(c[10])
        if np.isnan(cajas):
            continue
        out.append({
            "fecha": pd.Timestamp(fecha),
            "codigo": code,
            "producto": str(c[4] or "").strip(),
            "categoria": re.sub(r"^\d+-", "", cat or "").strip().title(),
            "subcategoria": re.sub(r"^\d+-", "", subcat or "").strip().title(),
            "estado": str(c[5] or "").strip(),
            "presentacion": str(c[6] or "").strip(),
            "cod_interno": str(c[7] or "").strip(),
            "unid_caja": to_num(c[8]),
            "exist_unid": to_num(c[9]),
            "exist_cajas": cajas,
            "pendiente": to_num(c[11]),
            "fuente": os.path.basename(nombre) or "existencias",
        })
    return pd.DataFrame(out)


def parse_existencias_folder(carpeta: str) -> pd.DataFrame:
    """Lee todos los Reporte_Existencias_*.xlsx de una carpeta (modo local)."""
    files = sorted(glob.glob(os.path.join(carpeta, "Reporte_Existencias_*.xlsx")))
    dfs = []
    for f in files:
        try:
            dfs.append(parse_existencias(f))
        except Exception as e:  # archivo abierto/corrupto
            print("No se pudo leer", f, e)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# ----------------------------------------------------------------------------
# 2) Matriz histórica (Data_forecast.xlsx: bloque INVENTARIO y bloque PEDIDO)
# ----------------------------------------------------------------------------
def parse_matriz(src) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (inventario_long, pedidos_long) a partir de la hoja 'Matriz'."""
    wb = _open_wb(src)
    ws = wb["Matriz"] if "Matriz" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))

    inv, ped = [], []
    header, bloque = None, None
    for r in rows:
        if len(r) > 1 and isinstance(r[1], str) and r[1].strip().upper() == "ITEM":
            header = r
            continue
        if r[0]:
            lab = str(r[0]).upper()
            if "INVENTARIO" in lab:
                bloque = "inv"
            elif "PEDIDO" in lab or "COMPRA" in lab or "TRANSITO" in lab:
                bloque = "ped"
        code = norm_code(r[2]) if len(r) > 2 else None
        if not code or header is None or bloque is None:
            continue
        prod = str(r[1] or "").strip()
        for j in range(3, len(r)):
            h = header[j] if j < len(header) else None
            if not isinstance(h, (dt.datetime, dt.date)):
                continue
            v = to_num(r[j])
            if np.isnan(v):
                continue
            rec = {"fecha": pd.Timestamp(h), "codigo": code, "producto": prod}
            if bloque == "inv":
                rec["exist_cajas"] = v
                inv.append(rec)
            elif v > 0:
                rec["cajas"] = v
                ped.append(rec)
    inv_df = pd.DataFrame(inv)
    if not inv_df.empty:
        inv_df["fuente"] = "Matriz histórica"
    ped_df = pd.DataFrame(ped)
    if not ped_df.empty:
        ped_df["fuente"] = "Matriz histórica"
    return inv_df, ped_df


# ----------------------------------------------------------------------------
# 3) Historial_Pedidos (Google Sheets alimentado desde Gmail) - columna K = cajas
# ----------------------------------------------------------------------------
_COL_HINTS = {
    "fecha": ["fecha pedido", "fecha_pedido", "fecha de pedido", "fecha emision", "fecha"],
    "codigo": ["codigo barra", "cod. barra", "codigo de barras", "cod barras", "ean", "barra",
               "codigo", "código", "item"],
    "producto": ["descripcion", "descripción", "producto", "articulo", "artículo", "nombre"],
    "cajas": ["cajas", "caja", "cantidad cajas", "cant. cajas", "cantidad"],
    "local": ["local", "tienda", "destino", "bodega", "cd", "centro"],
    "orden": ["orden", "n° pedido", "no. pedido", "numero pedido", "pedido", "oc"],
    "fecha_entrega": ["fecha entrega", "entrega", "fecha_entrega"],
}


def _match_col(cols: list[str], hints: list[str], used: set) -> str | None:
    low = {c: str(c).strip().lower() for c in cols}
    for h in hints:
        for c, l in low.items():
            if c in used:
                continue
            if l == h:
                return c
    for h in hints:
        for c, l in low.items():
            if c in used:
                continue
            if h in l:
                return c
    return None


def detectar_columnas(df: pd.DataFrame) -> dict:
    """Autodetecta columnas. Cajas = columna K (índice 10) salvo que exista una llamada 'cajas'."""
    cols = list(df.columns)
    used: set = set()
    m: dict = {}
    # cajas: prioridad columna K
    if len(cols) > 10:
        m["cajas"] = cols[10]
    else:
        m["cajas"] = _match_col(cols, _COL_HINTS["cajas"], used)
    used.add(m["cajas"])
    for k in ["fecha_entrega", "fecha", "codigo", "producto", "local", "orden"]:
        c = _match_col(cols, _COL_HINTS[k], used)
        m[k] = c
        if c:
            used.add(c)
    # fallback código: columna con más valores tipo código de barras
    if not m.get("codigo"):
        best, score = None, 0
        for c in cols:
            s = df[c].head(200).map(norm_code).notna().mean()
            if s > score:
                best, score = c, s
        m["codigo"] = best if score > 0.5 else None
    # fallback fecha: primera columna que parsea como fecha
    if not m.get("fecha"):
        for c in cols:
            if c in used:
                continue
            p = parse_fecha(df[c].head(100))
            if p.notna().mean() > 0.7:
                m["fecha"] = c
                break
    return m


def normalizar_pedidos(df: pd.DataFrame, mapping: dict | None = None, fuente="Historial_Pedidos") -> tuple[pd.DataFrame, dict]:
    if df is None or df.empty:
        return pd.DataFrame(), {}
    mapping = mapping or detectar_columnas(df)
    if not mapping.get("fecha") or not mapping.get("codigo") or not mapping.get("cajas"):
        return pd.DataFrame(), mapping
    out = pd.DataFrame({
        "fecha": parse_fecha(df[mapping["fecha"]]),
        "codigo": df[mapping["codigo"]].map(norm_code),
        "cajas": df[mapping["cajas"]].map(to_num),
    })
    out["producto"] = df[mapping["producto"]].astype(str).str.strip() if mapping.get("producto") else ""
    for k in ("local", "orden"):
        if mapping.get(k):
            out[k] = df[mapping[k]].astype(str).str.strip()
    out = out.dropna(subset=["fecha", "codigo", "cajas"])
    out = out[out["cajas"] > 0]
    out["fecha"] = out["fecha"].dt.normalize()
    out["fuente"] = fuente
    return out.reset_index(drop=True), mapping


def leer_tabla(src) -> pd.DataFrame:
    """Lee un Excel/CSV subido (para Historial_Pedidos exportado) buscando la hoja correcta."""
    name = getattr(src, "name", str(src)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(src)
    data = src.getvalue() if hasattr(src, "getvalue") else src
    xl = pd.ExcelFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    sheet = next((s for s in xl.sheet_names if "historial" in s.lower() and "pedido" in s.lower()), xl.sheet_names[0])
    return xl.parse(sheet)


# ----------------------------------------------------------------------------
# 4) Google Sheets
# ----------------------------------------------------------------------------
def gsheet_client(sa_info: dict):
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive.readonly"]
    creds = Credentials.from_service_account_info(dict(sa_info), scopes=scopes)
    return gspread.authorize(creds)


def leer_gsheet(sheet_id: str, hoja: str, sa_info: dict | None = None) -> pd.DataFrame:
    """
    Con cuenta de servicio (recomendado, hoja privada) o, si no hay credenciales,
    vía exportación CSV pública (la hoja debe estar compartida 'cualquiera con el enlace').
    """
    if sa_info:
        gc = gsheet_client(sa_info)
        ws = gc.open_by_key(sheet_id).worksheet(hoja)
        # UNFORMATTED: los códigos de barras llegan completos (no 7.86E+12)
        values = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        if not values:
            return pd.DataFrame()
        hdr = _dedupe([h if h else f"col_{i}" for i, h in enumerate(values[0])])
        return pd.DataFrame(values[1:], columns=hdr)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={hoja}"
    return pd.read_csv(url)


def _dedupe(cols: Iterable[str]) -> list[str]:
    seen, out = {}, []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def existencias_desde_gsheet(df: pd.DataFrame) -> pd.DataFrame:
    """Hoja 'Historial_Existencias' que llena el bot (ver bot/subir_a_google_sheets.py)."""
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    d["fecha"] = parse_fecha(d["fecha"])
    d["codigo"] = d["codigo"].map(norm_code)
    for c in ("unid_caja", "exist_unid", "exist_cajas", "pendiente"):
        if c in d:
            d[c] = d[c].map(to_num)
    d["fuente"] = "Google Sheets · Historial_Existencias"
    return d.dropna(subset=["fecha", "codigo", "exist_cajas"])


# ----------------------------------------------------------------------------
# 5) Combinar
# ----------------------------------------------------------------------------
def combinar_pedidos(*dfs: pd.DataFrame) -> pd.DataFrame:
    """
    Une pedidos de varias fuentes. Si la misma (fecha, código) viene de varias fuentes,
    gana la última pasada (Google Sheets > Matriz). Si hay 'local', se suma por local.
    """
    dfs = [d for d in dfs if d is not None and not d.empty]
    if not dfs:
        return pd.DataFrame(columns=["fecha", "codigo", "producto", "cajas", "fuente"])
    # una fuente más nueva manda desde su primera fecha: evita contar dos veces
    # el mismo pedido si la Matriz y Historial_Pedidos lo registran con fechas distintas
    recortados = []
    for i, d in enumerate(dfs):
        corte = min((x["fecha"].min() for x in dfs[i + 1:]), default=None)
        recortados.append(d[d["fecha"] < corte] if corte is not None else d)
    dfs = recortados
    prio = {id(d): i for i, d in enumerate(dfs)}
    todo = pd.concat([d.assign(_p=prio[id(d)]) for d in dfs], ignore_index=True)
    # para cada fecha+código nos quedamos con la fuente de mayor prioridad
    maxp = todo.groupby(["fecha", "codigo"])["_p"].transform("max")
    todo = todo[todo["_p"] == maxp].drop(columns="_p")
    return todo.sort_values("fecha").reset_index(drop=True)


def combinar_existencias(*dfs: pd.DataFrame) -> pd.DataFrame:
    """Una foto por día y código (la última del día)."""
    dfs = [d for d in dfs if d is not None and not d.empty]
    if not dfs:
        return pd.DataFrame(columns=["fecha", "codigo", "exist_cajas"])
    todo = pd.concat(dfs, ignore_index=True)
    todo["ts"] = todo["fecha"]
    todo["fecha"] = todo["fecha"].dt.normalize()
    todo = todo.sort_values("ts").drop_duplicates(["fecha", "codigo"], keep="last")
    return todo.drop(columns="ts").reset_index(drop=True)


def maestro_productos(exist: pd.DataFrame, pedidos: pd.DataFrame) -> pd.DataFrame:
    """Catálogo: prioriza nombres del reporte de existencias (oficiales de Favorita)."""
    partes = []
    if exist is not None and not exist.empty:
        cols = [c for c in ["codigo", "producto", "categoria", "presentacion", "estado", "unid_caja"] if c in exist]
        e = exist.sort_values("fecha")[cols].copy()
        e = e[e["producto"].astype(str).str.len() > 0]
        partes.append(e.assign(_o=0))
    if pedidos is not None and not pedidos.empty:
        partes.append(pedidos.sort_values("fecha")[["codigo", "producto"]].assign(_o=1))
    if not partes:
        return pd.DataFrame(columns=["codigo", "producto", "categoria", "marca"])
    m = pd.concat(partes, ignore_index=True)
    # por código, preferir fuente 0 (existencias) y el registro más reciente
    m = m.sort_values("_o", ascending=False).drop_duplicates("codigo", keep="last")
    # completar campos faltantes de existencias
    for c in ["categoria", "presentacion", "estado", "unid_caja"]:
        if c not in m:
            m[c] = np.nan
        if exist is not None and c in exist:
            last = exist.sort_values("fecha").drop_duplicates("codigo", keep="last").set_index("codigo")[c]
            m[c] = m[c].where(m[c].notna() & (m[c].astype(str) != ""), m["codigo"].map(last))
    m["producto"] = m["producto"].astype(str).str.strip()
    pres = m["presentacion"].fillna("").astype(str)
    add = [(" " + p) if p and p.replace(" ", "").lower() not in n.replace(" ", "").lower() else ""
           for n, p in zip(m["producto"], pres)]
    m["nombre"] = m["producto"] + pd.Series(add, index=m.index)
    m["marca"] = m["producto"].map(marca_de)
    m["categoria"] = m["categoria"].fillna("Sin categoría").replace("", "Sin categoría")
    return m.drop(columns="_o").reset_index(drop=True)
