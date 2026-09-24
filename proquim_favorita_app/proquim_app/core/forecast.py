"""
Motor de predicción del próximo pedido de La Favorita (cajas por SKU).

Compite con 5 modelos por SKU y elige el de menor error (MAE) en un backtest
"rolling origin" sobre las últimas semanas:

  1. PM4        Promedio móvil 4 semanas.
  2. SES        Suavizamiento exponencial simple (alpha optimizado).
  3. Croston    Croston-SBA: ideal para pedidos intermitentes (semanas en cero).
  4. Reposición Modelo "order-up-to": Favorita pide lo que le falta para llegar a un
                stock objetivo S. S se aprende del historial (stock antes del
                pedido + cajas pedidas) y se proyecta el stock al día del pedido
                con el consumo diario. Es el único que "mira" el stock actual.
  5. Ensamble   Promedio de SES, Croston y Reposición (si existe).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analytics import inicio_semana, semanal, consumo_diario, pivot_stock, DIAS_ES


# ----------------------------------------------------------------------------
# modelos de serie de tiempo
# ----------------------------------------------------------------------------
def f_pm4(y: np.ndarray) -> float:
    return float(np.mean(y[-4:])) if len(y) else 0.0


def _ses(y, a):
    lvl = y[0]
    sse = 0.0
    for v in y[1:]:
        sse += (v - lvl) ** 2
        lvl = a * v + (1 - a) * lvl
    return lvl, sse


def f_ses(y: np.ndarray) -> float:
    if len(y) < 3:
        return f_pm4(y)
    best = min((_ses(y, a) for a in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)), key=lambda t: t[1])
    return float(best[0])


def f_croston_sba(y: np.ndarray, a: float = 0.2) -> float:
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return 0.0
    if len(nz) == 1:
        return float(y[nz[0]] / max(len(y), 1))
    z = y[nz[0]]
    p = nz[0] + 1.0
    q = 1
    for v in y[nz[0] + 1:]:
        if v > 0:
            z = a * v + (1 - a) * z
            p = a * q + (1 - a) * p
            q = 1
        else:
            q += 1
    return float((1 - a / 2) * z / p)


MODELOS_TS = {"PM4": f_pm4, "SES": f_ses, "Croston": f_croston_sba}


# ----------------------------------------------------------------------------
# modelo de reposición (usa stock)
# ----------------------------------------------------------------------------
def _stock_antes(stock_s: pd.Series, fecha: pd.Timestamp, max_dias: int = 5) -> float:
    s = stock_s[(stock_s.index < fecha) & (stock_s.index >= fecha - pd.Timedelta(days=max_dias))].dropna()
    return float(s.iloc[-1]) if len(s) else np.nan


def _objetivo_S(hist: list[tuple[float, float]]) -> float:
    """hist = [(stock_antes, cajas_pedidas)] de semanas con pedido."""
    vals = [s + q for s, q in hist if not np.isnan(s)]
    return float(np.median(vals)) if len(vals) >= 3 else np.nan


def _reposicion(S: float, stock_proj: float, min_ped: float) -> float:
    if np.isnan(S) or np.isnan(stock_proj):
        return np.nan
    falta = S - stock_proj
    return float(falta) if falta >= min_ped else 0.0


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def multiplo_pedido(pedidos: pd.DataFrame) -> int:
    if pedidos.empty:
        return 1
    q = pedidos["cajas"].round()
    for m in (10, 5):
        if (q % m == 0).mean() >= 0.85:
            return m
    return 1


def redondear(v: float, m: int) -> float:
    if v is None or np.isnan(v):
        return np.nan
    return float(np.round(v / m) * m) if m > 1 else float(np.round(v))


def dia_pedido_tipico(pedidos: pd.DataFrame) -> int:
    if pedidos.empty:
        return 2
    return int(pedidos.drop_duplicates("fecha")["fecha"].dt.weekday.mode().iloc[0])


def proxima_fecha(hoy: pd.Timestamp, weekday: int) -> pd.Timestamp:
    d = (weekday - hoy.weekday()) % 7
    return (hoy + pd.Timedelta(days=d)).normalize()


# ----------------------------------------------------------------------------
# motor principal
# ----------------------------------------------------------------------------
def pronosticar(pedidos: pd.DataFrame, exist: pd.DataFrame, maestro: pd.DataFrame, hoy: pd.Timestamp,
                dia_pedido: int | None = None, semanas_bt: int = 8, z: float = 1.28,
                ventana_consumo: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Devuelve:
      resumen  -> una fila por SKU con el pronóstico del próximo pedido
      backtest -> predicciones vs real por semana/modelo (para gráficos y métricas)
    """
    if pedidos.empty:
        return pd.DataFrame(), pd.DataFrame()

    dia = dia_pedido if dia_pedido is not None else dia_pedido_tipico(pedidos)
    mult = multiplo_pedido(pedidos)
    fecha_obj = proxima_fecha(hoy, dia)

    w = semanal(pedidos)  # hasta la última semana con datos
    st = pivot_stock(exist) if exist is not None and not exist.empty else pd.DataFrame()
    cons = consumo_diario(exist, hoy, ventana_consumo).set_index("codigo")["consumo_dia"] \
        if exist is not None and not exist.empty else pd.Series(dtype=float)

    # fecha real de pedido por semana (o día típico si no hubo pedido)
    fechas_ped = pedidos.groupby(inicio_semana(pedidos["fecha"]))["fecha"].min()

    def fecha_semana(sem):
        return fechas_ped.get(sem, sem + pd.Timedelta(days=dia))

    nombres = maestro.set_index("codigo")["nombre"] if not maestro.empty else pd.Series(dtype=str)
    res, bt_rows = [], []

    for c in w.columns:
        serie = w[c]
        first = serie[serie > 0].index.min()
        serie = serie[serie.index >= first]
        y = serie.values.astype(float)
        sems = serie.index
        stock_s = st[c] if (not st.empty and c in st.columns) else pd.Series(dtype=float)

        # historial para reposición
        hist_rep = []
        for sem, q in zip(sems, y):
            s0 = _stock_antes(stock_s, fecha_semana(sem)) if len(stock_s) else np.nan
            hist_rep.append((s0, q))
        pos = [q for q in y if q > 0]
        min_ped = (np.percentile(pos, 10) * 0.6) if pos else mult

        # ---------------- backtest ----------------
        errs = {k: [] for k in list(MODELOS_TS) + ["Reposición", "Ensamble"]}
        n = len(y)
        for t in range(max(6, n - semanas_bt), n):
            tr = y[:t]
            real = y[t]
            preds = {k: f(tr) for k, f in MODELOS_TS.items()}
            S = _objetivo_S([h for h in hist_rep[:t] if h[1] > 0])
            preds["Reposición"] = _reposicion(S, hist_rep[t][0], min_ped)
            ens = [preds["SES"], preds["Croston"]] + ([preds["Reposición"]] if not np.isnan(preds["Reposición"]) else [])
            preds["Ensamble"] = float(np.mean(ens))
            for k, v in preds.items():
                if not np.isnan(v):
                    errs[k].append(v - real)
                    bt_rows.append({"codigo": c, "semana": sems[t], "modelo": k, "pred": v, "real": real})

        mae = {k: float(np.mean(np.abs(e))) for k, e in errs.items() if len(e) >= 3}
        rmse = {k: float(np.sqrt(np.mean(np.square(e)))) for k, e in errs.items() if len(e) >= 3}
        bias = {k: float(np.mean(e)) for k, e in errs.items() if len(e) >= 3}

        # ---------------- pronóstico siguiente pedido ----------------
        preds = {k: f(y) for k, f in MODELOS_TS.items()}
        S = _objetivo_S([h for h in hist_rep if h[1] > 0])
        stock_now = float(stock_s.dropna().iloc[-1]) if len(stock_s.dropna()) else np.nan
        f_stock = stock_s.dropna().index[-1] if len(stock_s.dropna()) else pd.NaT
        cd = float(cons.get(c, np.nan))
        stock_viejo = pd.notna(f_stock) and (hoy - f_stock).days > 7
        if not np.isnan(stock_now) and not np.isnan(cd) and not stock_viejo:
            dias = max((fecha_obj - f_stock).days, 0)
            stock_proj = max(stock_now - cd * dias, 0.0)
        else:
            stock_proj = np.nan
        preds["Reposición"] = _reposicion(S, stock_proj, min_ped)
        ens = [preds["SES"], preds["Croston"]] + ([preds["Reposición"]] if not np.isnan(preds["Reposición"]) else [])
        preds["Ensamble"] = float(np.mean(ens))

        if mae:
            elegido = min(mae, key=mae.get)
        else:
            elegido = "Ensamble"
        if np.isnan(preds.get(elegido, np.nan)):
            elegido = "Ensamble"
        p = max(preds[elegido], 0.0)
        err = rmse.get(elegido, np.std(y[-12:]) if len(y) else 0.0)
        lo, hi = max(p - z * err, 0.0), p + z * err

        # probabilidad de que haya pedido
        prob = float((y[-12:] > 0).mean()) if len(y) else 0.0
        if not np.isnan(preds["Reposición"]):
            prob = 0.5 * prob + 0.5 * (1.0 if preds["Reposición"] > 0 else 0.1)

        # tendencia: últimas 4 vs 4 anteriores
        a4, b4 = y[-4:].mean() if n >= 4 else np.nan, y[-8:-4].mean() if n >= 8 else np.nan
        tend = (a4 - b4) / b4 if b4 and not np.isnan(b4) and b4 > 0 else np.nan

        res.append({
            "codigo": c,
            "producto": nombres.get(c, c),
            "fecha_pedido_estimada": fecha_obj,
            "pronostico_cajas": redondear(p, mult),
            "rango_min": redondear(lo, mult),
            "rango_max": redondear(hi, mult),
            "prob_pedido": prob,
            "modelo": elegido,
            "mae_modelo": mae.get(elegido, np.nan),
            "sesgo_modelo": bias.get(elegido, np.nan),
            "mae_pm4": mae.get("PM4", np.nan),
            "stock_actual": stock_now,
            "stock_desactualizado": bool(stock_viejo),
            "stock_proyectado": stock_proj,
            "stock_objetivo_S": S,
            "consumo_dia": cd,
            "tendencia_4s": tend,
            "prom_12s": float(y[-12:].mean()) if n else 0.0,
            **{f"pred_{k}": v for k, v in preds.items()},
        })

    resumen = pd.DataFrame(res)
    if not resumen.empty:
        resumen["tener_listo_cajas"] = resumen["rango_max"]  # P90 aprox.
        resumen = resumen.sort_values("pronostico_cajas", ascending=False).reset_index(drop=True)
    return resumen, pd.DataFrame(bt_rows)


def metricas_globales(bt: pd.DataFrame) -> pd.DataFrame:
    """WAPE por modelo en el backtest (error total / volumen real total)."""
    if bt.empty:
        return pd.DataFrame()
    g = bt.assign(abs_err=(bt["pred"] - bt["real"]).abs()).groupby("modelo").agg(
        err=("abs_err", "sum"), real=("real", "sum"), n=("real", "size"))
    g["WAPE"] = g["err"] / g["real"].replace(0, np.nan)
    g["Precisión"] = (1 - g["WAPE"]).clip(lower=0)
    return g.reset_index().sort_values("WAPE")
