"""
Sube el Reporte_Existencias_*.xlsx que descarga el bot a la hoja 'Historial_Existencias'
del mismo Google Sheet donde está 'Historial_Pedidos'. Así la app en Streamlit Cloud
(que NO puede ver tu escritorio) tiene el stock diario de Favorita.

USO
  1) pip install gspread google-auth openpyxl
  2) Guarda el JSON de la cuenta de servicio como:  credenciales_google.json  (junto a este archivo)
  3) Comparte el Google Sheet con el correo de la cuenta de servicio (Editor).
  4) Al final de tu bot, después de  wb.save(nuevo_nombre):

        from subir_a_google_sheets import subir_existencias
        subir_existencias(nuevo_nombre)

  También puedes cargar TODO lo que ya tienes en la carpeta (una sola vez):
        python subir_a_google_sheets.py --carpeta "C:\\Users\\WELCOME\\Desktop\\FAVORTIA PROQUIM"
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re
import sys

import openpyxl

SHEET_ID = "1dN8IqX60L2bkinbuyJKe5iF6ihsOMB5CFWGTJTTy-PM"
HOJA = "Historial_Existencias"
CREDENCIALES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credenciales_google.json")
COLUMNAS = ["fecha", "codigo", "producto", "categoria", "presentacion", "estado",
            "unid_caja", "exist_unid", "exist_cajas", "pendiente", "archivo"]


def _num(v):
    try:
        return float(v) if v not in (None, "") else ""
    except (TypeError, ValueError):
        return ""


def leer_reporte(ruta: str) -> list[list]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", os.path.basename(ruta))
    fecha = (dt.datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
             if m else dt.datetime.fromtimestamp(os.path.getmtime(ruta)))
    ws = openpyxl.load_workbook(ruta, data_only=True).active
    filas, cat = [], ""
    for r in ws.iter_rows(values_only=True):
        r = list(r) + [None] * 13
        off = next((j for j, v in enumerate(r[:5]) if isinstance(v, str) and "PROQUIM" in v.upper()), None)
        if off is None:
            continue
        c = r[off:off + 13]
        if c[1]:
            cat = re.sub(r"^\d+-", "", str(c[1])).strip().title()
        codigo = str(c[3] or "").strip().replace(".0", "")
        if not codigo.isdigit() or _num(c[10]) == "":
            continue
        filas.append([fecha.strftime("%Y-%m-%d %H:%M"), "'" + codigo, str(c[4] or "").strip(), cat,
                      str(c[6] or "").strip(), str(c[5] or "").strip(),
                      _num(c[8]), _num(c[9]), _num(c[10]), _num(c[11]), os.path.basename(ruta)])
    return filas


def _hoja():
    import gspread
    gc = gspread.service_account(filename=CREDENCIALES)
    sh = gc.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(HOJA)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(HOJA, rows=1000, cols=len(COLUMNAS))
        ws.append_row(COLUMNAS)
    return ws


def subir_existencias(ruta: str, ws=None) -> int:
    ws = ws or _hoja()
    ya = set(ws.col_values(len(COLUMNAS)))  # columna 'archivo' → evita duplicados
    if os.path.basename(ruta) in ya:
        print(f"↩️  {os.path.basename(ruta)} ya estaba en Google Sheets")
        return 0
    filas = leer_reporte(ruta)
    if filas:
        ws.append_rows(filas, value_input_option="USER_ENTERED")
    print(f"☁️  {len(filas)} filas subidas a '{HOJA}' desde {os.path.basename(ruta)}")
    return len(filas)


if __name__ == "__main__":
    if "--carpeta" in sys.argv:
        carpeta = sys.argv[sys.argv.index("--carpeta") + 1]
        ws = _hoja()
        for f in sorted(glob.glob(os.path.join(carpeta, "Reporte_Existencias_*.xlsx"))):
            subir_existencias(f, ws)
    elif len(sys.argv) > 1:
        subir_existencias(sys.argv[1])
    else:
        print(__doc__)
