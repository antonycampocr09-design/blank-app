"""
Análisis: stock vs pedidos, consumo (sell-out), recepciones, lead time, patrones, ABC-XYZ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def inicio_semana(s: pd.Series) -> pd.Series:
    return (s - pd.to_timedelta(s.dt.weekday, unit="D")).dt.normalize()


# ----------------------------------------------------------------------------
# Stock / consumo
# ----------------------------------------------------------------------------
def pivot_stock(exist: pd.DataFrame) -> pd.DataFrame:
    if exist is None or exist.empty:
        return pd.DataFrame()
    return exist.pivot_table(index="fecha", columns="codigo", values="exist_cajas", aggfunc="last").sort_index()


def movimientos(exist: pd.DataFrame) -> pd.DataFrame:
    """
    Diferencias entre fotos consecutivas de stock por código.
      delta < 0  -> venta / salida del CD (sell-out)
      delta > 0  -> recepción (llegó mercadería de Proquim)
    """
    if exist is None or exist.empty:
        return pd.DataFrame(columns=["fecha", "codigo", "delta", "dias"])
    e = exist[["fecha", "codigo", "exist_cajas"]].sort_values(["codigo", "fecha"]).copy()
    e["prev"] = e.groupby("codigo")["exist_cajas"].shift()
    e["prev_fecha"] = e.groupby("codigo")["fecha"].shift()
    e = e.dropna(subset=["prev"])
    e["delta"] = e["exist_cajas"] - e["prev"]
    e["dias"] = (e["fecha"] - e["prev_fecha"]).dt.days.clip(lower=1)
    return e[["fecha", "codigo", "delta", "dias", "exist_cajas", "prev"]]


def consumo_diario(exist: pd.DataFrame, hoy: pd.Timestamp, ventana_dias: int = 42) -> pd.DataFrame:
    """Consumo promedio diario (cajas/día) estimado de las bajadas de stock en la ventana."""
    mv = movimientos(exist)
    if mv.empty:
        return pd.DataFrame(columns=["codigo", "consumo_dia", "recibido_ventana"])
    desde = hoy - pd.Timedelta(days=ventana_dias)
    mv = mv[mv["fecha"] > desde]
    g = mv.groupby("codigo")
    salidas = g["delta"].apply(lambda s: -s[s < 0].sum())
    entradas = g["delta"].apply(lambda s: s[s > 0].sum())
    span = g["dias"].sum().clip(lower=1)
    return pd.DataFrame({
        "consumo_dia": salidas / span,
        "recibido_ventana": entradas,
    }).reset_index()


def recepciones(exist: pd.DataFrame, umbral: float = 1.0) -> pd.DataFrame:
    mv = movimientos(exist)
    r = mv[mv["delta"] >= umbral].copy()
    r = r.rename(columns={"delta": "recibido"})
    return r[["fecha", "codigo", "recibido"]].reset_index(drop=True)


def cumplimiento(pedidos: pd.DataFrame, exist: pd.DataFrame, max_dias: int = 14) -> pd.DataFrame:
    """
    Empareja cada pedido con la primera subida de stock posterior (≤ max_dias).
    Da: lead time (días pedido→recepción) y % recibido vs pedido (aprox.; la subida
    neta subestima lo recibido si hubo ventas ese mismo día).
    """
    rec = recepciones(exist)
    if pedidos.empty or rec.empty:
        return pd.DataFrame()
    ped = pedidos.groupby(["fecha", "codigo"], as_index=False)["cajas"].sum()
    out = []
    rec_by = {k: v.sort_values("fecha") for k, v in rec.groupby("codigo")}
    for _, p in ped.iterrows():
        r = rec_by.get(p["codigo"])
        if r is None:
            continue
        cand = r[(r["fecha"] > p["fecha"]) & (r["fecha"] <= p["fecha"] + pd.Timedelta(days=max_dias))]
        if cand.empty:
            out.append({**p, "fecha_recepcion": pd.NaT, "recibido": 0.0, "lead_dias": np.nan})
            continue
        c = cand.iloc[0]
        out.append({**p, "fecha_recepcion": c["fecha"], "recibido": c["recibido"],
                    "lead_dias": (c["fecha"] - p["fecha"]).days})
    df = pd.DataFrame(out)
    if not df.empty:
        df["pct_recibido"] = (df["recibido"] / df["cajas"]).clip(upper=1.5)
    return df


# ----------------------------------------------------------------------------
# Pedidos: series y patrones
# ----------------------------------------------------------------------------
def semanal(pedidos: pd.DataFrame, hasta: pd.Timestamp | None = None) -> pd.DataFrame:
    """Matriz semana (lunes) × código con cajas pedidas (0 si no hubo pedido)."""
    if pedidos.empty:
        return pd.DataFrame()
    p = pedidos.copy()
    p["semana"] = inicio_semana(p["fecha"])
    w = p.pivot_table(index="semana", columns="codigo", values="cajas", aggfunc="sum")
    fin = inicio_semana(pd.Series([hasta]))[0] if hasta is not None else w.index.max()
    idx = pd.date_range(w.index.min(), max(fin, w.index.max()), freq="W-MON")
    return w.reindex(idx).fillna(0.0)


def dias_de_pedido(pedidos: pd.DataFrame) -> pd.DataFrame:
    if pedidos.empty:
        return pd.DataFrame()
    d = pedidos.groupby("fecha", as_index=False)["cajas"].sum()
    d["dia"] = d["fecha"].dt.weekday
    g = d.groupby("dia").agg(pedidos=("fecha", "nunique"), cajas=("cajas", "sum")).reindex(range(7), fill_value=0)
    g["dia_nombre"] = DIAS_ES
    g["pct"] = g["pedidos"] / max(g["pedidos"].sum(), 1)
    return g.reset_index()


def abc_xyz(w: pd.DataFrame, semanas: int = 16) -> pd.DataFrame:
    """ABC por volumen (80/15/5) y XYZ por variabilidad (CV semanal)."""
    if w.empty:
        return pd.DataFrame()
    x = w.tail(semanas)
    tot = x.sum().sort_values(ascending=False)
    cum = tot.cumsum() / max(tot.sum(), 1)
    abc = pd.Series(np.where(cum <= 0.80, "A", np.where(cum <= 0.95, "B", "C")), index=tot.index)
    # el primero siempre A aunque supere 80 %
    if len(abc):
        abc.iloc[0] = "A"
    mean = x.mean()
    cv = (x.std(ddof=0) / mean.replace(0, np.nan)).fillna(np.inf)
    xyz = pd.Series(np.where(cv < 0.75, "X", np.where(cv < 1.5, "Y", "Z")), index=cv.index)
    freq = (x > 0).mean()
    return pd.DataFrame({
        "total_cajas": tot, "prom_semanal": mean.reindex(tot.index), "cv": cv.reindex(tot.index),
        "frecuencia": freq.reindex(tot.index), "ABC": abc, "XYZ": xyz.reindex(tot.index),
    }).reset_index().rename(columns={"index": "codigo"})


# ----------------------------------------------------------------------------
# Tabla maestra: stock vs pedidos
# ----------------------------------------------------------------------------
def estado_stock(dias_cob: float, stock: float, cob_min: float, cob_obj: float, cob_max: float) -> str:
    if stock is None or np.isnan(stock):
        return "Sin dato"
    if stock <= 0:
        return "Agotado"
    if np.isnan(dias_cob) or np.isinf(dias_cob):
        return "Sin rotación"
    if dias_cob < cob_min:
        return "Crítico"
    if dias_cob < cob_obj:
        return "Bajo"
    if dias_cob > cob_max:
        return "Sobrestock"
    return "OK"


ESTADO_ORDEN = ["Agotado", "Crítico", "Bajo", "OK", "Sobrestock", "Sin rotación", "Sin dato"]
ESTADO_ICONO = {"Agotado": "⛔", "Crítico": "🔴", "Bajo": "🟠", "OK": "🟢",
                "Sobrestock": "🔵", "Sin rotación": "⚪", "Sin dato": "▫️"}


def tabla_comparativa(pedidos, exist, maestro, hoy, cob_min=7, cob_obj=14, cob_max=45, ventana=42) -> pd.DataFrame:
    codigos = set(maestro["codigo"]) if not maestro.empty else set()
    base = maestro.set_index("codigo") if not maestro.empty else pd.DataFrame()

    # último stock
    if exist is not None and not exist.empty:
        last = exist.sort_values("fecha").drop_duplicates("codigo", keep="last").set_index("codigo")
        stock = last["exist_cajas"]
        f_stock = last["fecha"]
    else:
        stock = pd.Series(dtype=float)
        f_stock = pd.Series(dtype="datetime64[ns]")
    cons = consumo_diario(exist, hoy, ventana).set_index("codigo") if exist is not None and not exist.empty else pd.DataFrame()

    w = semanal(pedidos, hoy)
    p4 = w.tail(4).mean() if not w.empty else pd.Series(dtype=float)
    p12 = w.tail(12).mean() if not w.empty else pd.Series(dtype=float)
    freq12 = (w.tail(12) > 0).mean() if not w.empty else pd.Series(dtype=float)
    ult = pedidos.sort_values("fecha").groupby("codigo").agg(ult_fecha=("fecha", "last")) if not pedidos.empty else pd.DataFrame()
    if not pedidos.empty:
        ult_c = pedidos.groupby(["codigo", "fecha"])["cajas"].sum().reset_index().sort_values("fecha").drop_duplicates("codigo", keep="last").set_index("codigo")["cajas"]
    else:
        ult_c = pd.Series(dtype=float)

    rows = []
    for c in sorted(codigos | set(stock.index) | set(p12.index)):
        s = float(stock.get(c, np.nan))
        cd = float(cons["consumo_dia"].get(c, np.nan)) if not cons.empty else np.nan
        dias = s / cd if cd and cd > 0 and not np.isnan(s) else (np.inf if not np.isnan(s) and s > 0 else np.nan)
        rows.append({
            "codigo": c,
            "producto": base["nombre"].get(c, "") if not base.empty else "",
            "marca": base["marca"].get(c, "") if not base.empty else "",
            "categoria": base["categoria"].get(c, "") if not base.empty else "",
            "stock_cajas": s,
            "fecha_stock": f_stock.get(c, pd.NaT),
            "consumo_dia": cd,
            "consumo_semana": cd * 7 if not np.isnan(cd) else np.nan,
            "dias_cobertura": dias,
            "pedido_prom_4s": float(p4.get(c, 0.0)),
            "pedido_prom_12s": float(p12.get(c, 0.0)),
            "frecuencia_12s": float(freq12.get(c, 0.0)),
            "ult_pedido_fecha": ult["ult_fecha"].get(c, pd.NaT) if not ult.empty else pd.NaT,
            "ult_pedido_cajas": float(ult_c.get(c, np.nan)),
        })
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["estado"] = [estado_stock(d, s, cob_min, cob_obj, cob_max) for d, s in zip(t["dias_cobertura"], t["stock_cajas"])]
    # si la última foto de stock tiene más de 7 días, no confiamos en el estado
    viejo = t["fecha_stock"].notna() & (t["fecha_stock"] < hoy - pd.Timedelta(days=7))
    t.loc[viejo, "estado"] = "Sin dato"
    t["fecha_quiebre"] = [hoy + pd.Timedelta(days=float(d)) if np.isfinite(d) else pd.NaT
                          for d in t["dias_cobertura"].fillna(np.inf)]
    t["stock_vs_pedido"] = t["stock_cajas"] / t["pedido_prom_12s"].replace(0, np.nan)
    t["_ord"] = t["estado"].map({e: i for i, e in enumerate(ESTADO_ORDEN)})
    return t.sort_values(["_ord", "dias_cobertura"]).drop(columns="_ord").reset_index(drop=True)
