"""
PROQUIM · Inteligencia de Pedidos La Favorita
Streamlit app: stock vs pedidos, patrones y predicción del próximo pedido.

Ejecutar local:   streamlit run app.py
Publicar:         https://share.streamlit.io  (ver README.md)
"""
from __future__ import annotations

import datetime as dt
import os
import glob

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import loaders as L
from core import analytics as A
from core import forecast as F
from core import ui as U

st.set_page_config(page_title="PROQUIM · Pedidos Favorita", page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")
U.estilo()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.join(APP_DIR, "data")
SHEET_ID_DEFAULT = "1dN8IqX60L2bkinbuyJKe5iF6ihsOMB5CFWGTJTTy-PM"
CARPETA_BOT = r"C:\Users\WELCOME\Desktop\FAVORTIA PROQUIM"


def _secret(path, default=None):
    try:
        cur = st.secrets
        for p in path.split("."):
            cur = cur[p]
        return cur
    except Exception:
        return default


# =============================================================================
# CARGA (cacheada)
# =============================================================================
@st.cache_data(show_spinner=False)
def c_matriz(data: bytes, nombre: str):
    return L.parse_matriz(data)


@st.cache_data(show_spinner=False)
def c_existencias(data: bytes, nombre: str):
    return L.parse_existencias(data, nombre=nombre)


@st.cache_data(show_spinner=False)
def c_tabla(data: bytes, nombre: str):
    class _F:  # imita UploadedFile
        def __init__(s, d, n): s._d, s.name = d, n
        def getvalue(s): return s._d
    if nombre.lower().endswith(".csv"):
        import io
        return pd.read_csv(io.BytesIO(data))
    return L.leer_tabla(_F(data, nombre))


@st.cache_data(ttl=600, show_spinner="Leyendo Google Sheets…")
def c_gsheet(sheet_id: str, hoja: str, _sa, sa_key: str):
    return L.leer_gsheet(sheet_id, hoja, _sa)


@st.cache_data(show_spinner=False)
def c_carpeta(carpeta: str, firma: tuple):
    return L.parse_existencias_folder(carpeta)


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown("### 📦 PROQUIM · Favorita")
    st.caption("Inteligencia de pedidos y stock")

    with st.expander("🔌 Fuentes de datos", expanded=False):
        sa_info = _secret("gcp_service_account")
        usar_gs = st.toggle("Google Sheets", value=bool(sa_info),
                            help="Lee 'Historial_Pedidos' (Gmail → Sheets) y 'Historial_Existencias' (bot).")
        sheet_id = st.text_input("ID del Google Sheet", value=_secret("sheets.sheet_id", SHEET_ID_DEFAULT))
        hoja_ped = st.text_input("Hoja de pedidos", value=_secret("sheets.hoja_pedidos", "Historial_Pedidos"))
        hoja_exi = st.text_input("Hoja de existencias", value=_secret("sheets.hoja_existencias", "Historial_Existencias"))
        if usar_gs and not sa_info:
            st.caption("Sin credenciales: se intentará lectura pública (hoja compartida por enlace).")
        st.divider()
        up_matriz = st.file_uploader("Matriz histórica (Data_forecast.xlsx)", type=["xlsx"])
        up_hist = st.file_uploader("Historial_Pedidos exportado (xlsx/csv)", type=["xlsx", "csv"])
        up_exist = st.file_uploader("Reportes de Existencias del bot", type=["xlsx"], accept_multiple_files=True)
        st.divider()
        carpeta = st.text_input("Carpeta local del bot (solo si corres la app en tu PC)", value=CARPETA_BOT)
        usar_demo = st.toggle("Incluir datos de ejemplo (carpeta data/)", value=True)
        if st.button("🔄 Recargar datos", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    with st.expander("⚙️ Parámetros", expanded=False):
        hoy = pd.Timestamp(st.date_input("Fecha de análisis", value=dt.date.today()))
        dia_opc = ["Auto (detectar)"] + A.DIAS_ES
        dia_sel = st.selectbox("Día en que Favorita envía el pedido", dia_opc, index=0)
        c1, c2 = st.columns(2)
        cob_min = c1.number_input("Cobertura crítica (días)", 1, 60, 7)
        cob_obj = c2.number_input("Cobertura objetivo (días)", 2, 90, 14)
        cob_max = st.number_input("Sobrestock desde (días)", 10, 180, 45)
        ventana = st.slider("Ventana para medir consumo (días)", 14, 120, 42, step=7)
        nivel = st.select_slider("Nivel de servicio del rango", options=["80 %", "90 %", "95 %"], value="90 %")
        z = {"80 %": 0.84, "90 %": 1.28, "95 %": 1.65}[nivel]

# =============================================================================
# CONSOLIDAR FUENTES
# =============================================================================
estado_fuentes = []
ped_parts, exi_parts = [], []
mapping_ped = None
raw_hist = None

# 1) demo / matriz
if up_matriz is not None:
    inv_m, ped_m = c_matriz(up_matriz.getvalue(), up_matriz.name)
    estado_fuentes.append(("Matriz histórica (subida)", len(ped_m), len(inv_m)))
    ped_parts.append(ped_m); exi_parts.append(inv_m)
elif usar_demo and os.path.exists(os.path.join(DEMO_DIR, "Data_forecast.xlsx")):
    p = os.path.join(DEMO_DIR, "Data_forecast.xlsx")
    inv_m, ped_m = c_matriz(_bytes(p), p)
    estado_fuentes.append(("Matriz histórica (data/)", len(ped_m), len(inv_m)))
    ped_parts.append(ped_m); exi_parts.append(inv_m)

if usar_demo:
    for p in sorted(glob.glob(os.path.join(DEMO_DIR, "Reporte_Existencias_*.xlsx"))):
        e = c_existencias(_bytes(p), os.path.basename(p))
        exi_parts.append(e)
        estado_fuentes.append((f"Existencias · {os.path.basename(p)}", 0, len(e)))

# 2) carpeta local del bot
if carpeta and os.path.isdir(carpeta):
    files = sorted(glob.glob(os.path.join(carpeta, "Reporte_Existencias_*.xlsx")))
    firma = tuple((f, os.path.getmtime(f)) for f in files)
    e = c_carpeta(carpeta, firma)
    exi_parts.append(e)
    estado_fuentes.append((f"Carpeta local ({len(files)} archivos)", 0, len(e)))

# 3) existencias subidas
for f in up_exist or []:
    e = c_existencias(f.getvalue(), f.name)
    exi_parts.append(e)
    estado_fuentes.append((f"Existencias · {f.name}", 0, len(e)))

# 4) historial subido
if up_hist is not None:
    raw_hist = c_tabla(up_hist.getvalue(), up_hist.name)

# 5) Google Sheets
gs_error = None
if usar_gs and sheet_id:
    try:
        sa_key = sa_info.get("client_email", "") if sa_info else ""
        raw_gs = c_gsheet(sheet_id, hoja_ped, dict(sa_info) if sa_info else None, sa_key)
        raw_hist = raw_gs if raw_hist is None else pd.concat([raw_gs, raw_hist], ignore_index=True)
    except Exception as ex:
        gs_error = f"Pedidos: {ex}"
    try:
        sa_key = sa_info.get("client_email", "") if sa_info else ""
        raw_ge = c_gsheet(sheet_id, hoja_exi, dict(sa_info) if sa_info else None, sa_key)
        e = L.existencias_desde_gsheet(raw_ge)
        exi_parts.append(e)
        estado_fuentes.append(("Google Sheets · " + hoja_exi, 0, len(e)))
    except Exception as ex:
        gs_error = (gs_error + " | " if gs_error else "") + f"Existencias: {ex}"

# mapeo de columnas de Historial_Pedidos (columna K = cajas por defecto)
if raw_hist is not None and not raw_hist.empty:
    auto = L.detectar_columnas(raw_hist)
    with st.sidebar.expander("🧭 Columnas de Historial_Pedidos", expanded=False):
        st.caption("Detectadas automáticamente. Cajas = columna K por defecto.")
        cols = ["—"] + list(raw_hist.columns)
        mapping_ped = {}
        for k, lab in [("fecha", "Fecha del pedido"), ("codigo", "Código de barras"), ("producto", "Producto"),
                       ("cajas", "Cajas (col. K)"), ("local", "Local / destino"), ("orden", "N° orden")]:
            v = auto.get(k)
            sel = st.selectbox(lab, cols, index=cols.index(v) if v in cols else 0, key=f"map_{k}")
            mapping_ped[k] = None if sel == "—" else sel
    ped_h, _ = L.normalizar_pedidos(raw_hist, mapping_ped, fuente="Historial_Pedidos")
    estado_fuentes.append(("Historial_Pedidos", len(ped_h), 0))
    ped_parts.append(ped_h)  # última = mayor prioridad

PEDIDOS = L.combinar_pedidos(*ped_parts)
EXIST = L.combinar_existencias(*exi_parts)
MAESTRO = L.maestro_productos(EXIST, PEDIDOS)

if PEDIDOS.empty and EXIST.empty:
    U.hero("PROQUIM · Inteligencia de Pedidos", "Conecta una fuente de datos para empezar", [])
    st.info("Abre **🔌 Fuentes de datos** en la barra lateral y conecta Google Sheets o sube tus archivos.")
    if gs_error:
        st.error(gs_error)
    st.stop()

# ---------------- filtros ----------------
with st.sidebar:
    st.markdown("#### Filtros")
    marcas = sorted(MAESTRO["marca"].dropna().unique())
    f_marca = st.multiselect("Marca", marcas, placeholder="Todas")
    cats = sorted(MAESTRO["categoria"].dropna().unique())
    f_cat = st.multiselect("Categoría", cats, placeholder="Todas")
    solo_activos = st.toggle("Solo SKUs con pedidos en 12 semanas", value=True)

m = MAESTRO.copy()
if f_marca:
    m = m[m["marca"].isin(f_marca)]
if f_cat:
    m = m[m["categoria"].isin(f_cat)]
if solo_activos and not PEDIDOS.empty:
    activos = set(PEDIDOS[PEDIDOS["fecha"] >= hoy - pd.Timedelta(weeks=12)]["codigo"])
    m = m[m["codigo"].isin(activos)]
codes = set(m["codigo"])
P = PEDIDOS[PEDIDOS["codigo"].isin(codes)]
E = EXIST[EXIST["codigo"].isin(codes)]
NOMBRE = MAESTRO.set_index("codigo")["nombre"].to_dict()

dia_pedido = None if dia_sel.startswith("Auto") else A.DIAS_ES.index(dia_sel)
dia_real = dia_pedido if dia_pedido is not None else F.dia_pedido_tipico(P)


# =============================================================================
# CÁLCULOS (cacheados por firma de datos)
# =============================================================================
@st.cache_data(show_spinner="Calculando análisis y pronósticos…")
def calcular(P, E, m, hoy, cob_min, cob_obj, cob_max, ventana, dia_pedido, z):
    tabla = A.tabla_comparativa(P, E, m, hoy, cob_min, cob_obj, cob_max, ventana)
    res, bt = F.pronosticar(P, E, m, hoy, dia_pedido, z=z, ventana_consumo=ventana)
    return tabla, res, bt


TABLA, PRON, BT = calcular(P, E, m, hoy, cob_min, cob_obj, cob_max, ventana, dia_pedido, z)

# ---------------- encabezado ----------------
ult_ped = P["fecha"].max() if not P.empty else pd.NaT
ult_stk = E["fecha"].max() if not E.empty else pd.NaT
badges = [
    (f"Último pedido: {ult_ped:%d-%b-%Y}" if pd.notna(ult_ped) else "Sin pedidos",
     "ok" if pd.notna(ult_ped) and (hoy - ult_ped).days <= 8 else "warn"),
    (f"Último stock: {ult_stk:%d-%b-%Y}" if pd.notna(ult_stk) else "Sin stock",
     "ok" if pd.notna(ult_stk) and (hoy - ult_stk).days <= 2 else "warn"),
    (f"{len(codes)} SKUs", ""),
    (f"Pedido típico: {A.DIAS_ES[dia_real]}", ""),
]
if not PRON.empty:
    _fp = PRON["fecha_pedido_estimada"].iloc[0]
    badges.append((f"Próximo pedido: {A.DIAS_ES[_fp.weekday()]} {_fp:%d-%b}", "ok"))
U.hero("PROQUIM · Inteligencia de Pedidos La Favorita",
       "Lo que tiene Favorita en stock vs. lo que te pide — y cuánto te va a pedir", badges)
if gs_error:
    st.warning(f"Google Sheets no disponible ({gs_error}). Se usan las demás fuentes.", icon="⚠️")

tabs = st.tabs(["📊 Resumen", "⚖️ Stock vs Pedidos", "🔍 Patrones", "🔮 Predicción", "🚚 Cumplimiento", "🗂️ Datos"])


# =============================================================================
# TAB 1 · RESUMEN
# =============================================================================
with tabs[0]:
    stock_tot = TABLA["stock_cajas"].sum()
    # stock hace 7 días
    st_piv = A.pivot_stock(E)
    delta_stock = None
    if not st_piv.empty:
        hace7 = st_piv[st_piv.index <= hoy - pd.Timedelta(days=7)].ffill().tail(1).sum(axis=1)
        if len(hace7):
            delta_stock = stock_tot - float(hace7.iloc[0])
    cons_tot = TABLA["consumo_dia"].sum()
    cob_global = stock_tot / cons_tot if cons_tot > 0 else np.nan
    w_all = A.semanal(P)
    prom12 = w_all.sum(axis=1).tail(12).mean() if not w_all.empty else 0
    riesgo = TABLA[TABLA["estado"].isin(["Agotado", "Crítico", "Bajo"])]
    prox_total = PRON["pronostico_cajas"].sum() if not PRON.empty else 0
    prox_fecha = PRON["fecha_pedido_estimada"].iloc[0] if not PRON.empty else pd.NaT

    k = st.columns(5)
    k[0].metric("Stock en Favorita", U.fmt_num(stock_tot, suf=" cj"),
                delta=None if delta_stock is None else f"{delta_stock:+,.0f} vs hace 7 días".replace(",", " "))
    k[1].metric("Cobertura global", U.fmt_num(cob_global, 1, " días"),
                help="Stock total ÷ consumo diario total estimado")
    k[2].metric("Pedido semanal (prom. 12 s)", U.fmt_num(prom12, suf=" cj"))
    k[3].metric("SKUs en riesgo", f"{len(riesgo)}",
                delta=f"{(riesgo['estado'] != 'Bajo').sum()} críticos/agotados", delta_color="inverse")
    k[4].metric("Próximo pedido (estimado)",
                U.fmt_num(prox_total, suf=" cj"),
                delta=f"{(prox_total / prom12 - 1) * 100:+.0f}% vs promedio" if prom12 else None)

    c1, c2 = st.columns([1.35, 1])
    with c1:
        st.markdown("##### 🚨 Alertas de stock en Favorita")
        if riesgo.empty:
            st.success("Ningún SKU en riesgo con los parámetros actuales.")
        else:
            al = riesgo.merge(PRON[["codigo", "pronostico_cajas"]], on="codigo", how="left") if not PRON.empty else riesgo
            al = al.assign(Estado=al["estado"].map(lambda e: f"{A.ESTADO_ICONO.get(e, '')} {e}"))
            st.dataframe(
                al[["Estado", "producto", "stock_cajas", "dias_cobertura", "fecha_quiebre", "pedido_prom_4s"]
                   + (["pronostico_cajas"] if "pronostico_cajas" in al else [])],
                hide_index=True, width="stretch", height=330,
                column_config={
                    "producto": st.column_config.TextColumn("Producto", width="large"),
                    "stock_cajas": st.column_config.NumberColumn("Stock (cj)", format="%.0f"),
                    "dias_cobertura": st.column_config.NumberColumn("Cobertura (días)", format="%.1f"),
                    "fecha_quiebre": st.column_config.DateColumn("Quiebre estimado", format="DD-MMM"),
                    "pedido_prom_4s": st.column_config.NumberColumn("Pedido prom. 4s", format="%.0f"),
                    "pronostico_cajas": st.column_config.NumberColumn("Próx. pedido (cj)", format="%.0f"),
                })
    with c2:
        st.markdown("##### Estado del portafolio")
        cnt = TABLA["estado"].value_counts().reindex(A.ESTADO_ORDEN).dropna()
        fig = go.Figure(go.Bar(
            y=[f"{A.ESTADO_ICONO[e]} {e}" for e in cnt.index], x=cnt.values, orientation="h",
            marker=dict(color=[U.STATUS[e] for e in cnt.index], cornerradius=4),
            text=cnt.values.astype(int), textposition="outside",
            hovertemplate="%{y}: %{x} SKUs<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        U.plot(fig, 330, leyenda=False)

    c1, c2 = st.columns(2)
    with c1:
        if not w_all.empty:
            ws_ = w_all.sum(axis=1).tail(26)
            fig = go.Figure(go.Bar(x=ws_.index, y=ws_.values, marker=dict(color=U.NARANJA, cornerradius=4),
                                   name="Cajas pedidas", hovertemplate="Semana %{x|%d-%b}: %{y:,.0f} cj<extra></extra>"))
            if not PRON.empty:
                fig.add_trace(go.Bar(x=[prox_fecha - pd.Timedelta(days=prox_fecha.weekday())], y=[prox_total],
                                     marker=dict(color="rgba(235,104,52,.35)", line=dict(color=U.NARANJA, width=1.5), cornerradius=4),
                                     name="Pronóstico", hovertemplate="Pronóstico: %{y:,.0f} cj<extra></extra>"))
            U.plot(fig, 300, "Pedidos semanales de Favorita (cajas)")
    with c2:
        if not st_piv.empty:
            tot = st_piv.ffill().sum(axis=1)
            tot = tot[tot.index >= hoy - pd.Timedelta(days=182)]
            fig = go.Figure(go.Scatter(x=tot.index, y=tot.values, mode="lines", line=dict(color=U.AZUL, width=2),
                                       fill="tozeroy", fillcolor="rgba(42,120,214,.10)", name="Stock",
                                       hovertemplate="%{x|%d-%b}: %{y:,.0f} cj<extra></extra>"))
            U.plot(fig, 300, "Stock total en el CD de Favorita (cajas)", leyenda=False)


# =============================================================================
# TAB 2 · STOCK VS PEDIDOS
# =============================================================================
with tabs[1]:
    st.markdown("##### Comparativo por producto")
    st.caption("Stock actual en Favorita vs. lo que te piden. **Consumo** = bajadas de stock diarias (sell-out estimado). "
               "**Stock/Pedido** = cuántas semanas de pedido promedio tiene en bodega.")
    est_f = st.pills("Estado", A.ESTADO_ORDEN, selection_mode="multi", default=None, key="pill_estado")
    T = TABLA if not est_f else TABLA[TABLA["estado"].isin(est_f)]
    T = T.assign(Estado=T["estado"].map(lambda e: f"{A.ESTADO_ICONO.get(e, '')} {e}"),
                 frecuencia_12s=T["frecuencia_12s"] * 100)
    maxcob = float(np.nanmin([np.nanmax(T["dias_cobertura"].replace(np.inf, np.nan)) if len(T) else 60, 120])) or 60
    st.dataframe(
        T[["Estado", "producto", "marca", "stock_cajas", "consumo_semana", "dias_cobertura", "pedido_prom_4s",
           "pedido_prom_12s", "frecuencia_12s", "ult_pedido_fecha", "ult_pedido_cajas", "stock_vs_pedido", "fecha_stock"]],
        hide_index=True, width="stretch", height=460,
        column_config={
            "producto": st.column_config.TextColumn("Producto", width="large"),
            "marca": "Marca",
            "stock_cajas": st.column_config.NumberColumn("Stock (cj)", format="%.0f"),
            "consumo_semana": st.column_config.NumberColumn("Consumo/sem (cj)", format="%.1f"),
            "dias_cobertura": st.column_config.ProgressColumn("Cobertura (días)", format="%.0f", min_value=0, max_value=maxcob),
            "pedido_prom_4s": st.column_config.NumberColumn("Pedido prom. 4s", format="%.0f"),
            "pedido_prom_12s": st.column_config.NumberColumn("Pedido prom. 12s", format="%.0f"),
            "frecuencia_12s": st.column_config.ProgressColumn("Frecuencia pedido", format="%.0f%%", min_value=0, max_value=100),
            "ult_pedido_fecha": st.column_config.DateColumn("Último pedido", format="DD-MMM"),
            "ult_pedido_cajas": st.column_config.NumberColumn("Últ. cajas", format="%.0f"),
            "stock_vs_pedido": st.column_config.NumberColumn("Stock/Pedido (sem)", format="%.1f"),
            "fecha_stock": st.column_config.DatetimeColumn("Foto stock", format="DD-MMM HH:mm"),
        })

    st.markdown("##### Detalle por SKU")
    opciones = TABLA["codigo"].tolist()
    sel = st.selectbox("Producto", opciones, format_func=lambda c: f"{NOMBRE.get(c, c)} · {c}", key="sku_cmp")
    if sel:
        row = TABLA.set_index("codigo").loc[sel]
        c = st.columns(5)
        c[0].metric("Stock actual", U.fmt_num(row["stock_cajas"], suf=" cj"))
        c[1].metric("Consumo diario", U.fmt_num(row["consumo_dia"], 1, " cj"))
        c[2].metric("Cobertura", U.fmt_num(row["dias_cobertura"], 0, " días"))
        c[3].metric("Pedido prom. 12s", U.fmt_num(row["pedido_prom_12s"], suf=" cj"))
        c[4].metric(f"Estado {A.ESTADO_ICONO.get(row['estado'], '')}", row["estado"])

        s = E[E["codigo"] == sel].sort_values("fecha")
        p = P[P["codigo"] == sel].groupby("fecha", as_index=False)["cajas"].sum()
        rc = A.recepciones(E[E["codigo"] == sel])
        rng = st.segmented_control("Rango", ["3 meses", "6 meses", "Todo"], default="6 meses", key="rng_cmp")
        desde = hoy - pd.Timedelta(days={"3 meses": 92, "6 meses": 183}.get(rng, 3650))
        s, p, rc = s[s["fecha"] >= desde], p[p["fecha"] >= desde], rc[rc["fecha"] >= desde]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=p["fecha"], y=p["cajas"], name="Pedido de Favorita",
                             marker=dict(color=U.NARANJA, cornerradius=4), width=86400000 * 2.2,
                             hovertemplate="Pedido %{x|%a %d-%b}: %{y:,.0f} cj<extra></extra>"))
        fig.add_trace(go.Scatter(x=s["fecha"], y=s["exist_cajas"], name="Stock en Favorita", mode="lines",
                                 line=dict(color=U.AZUL, width=2, shape="hv"),
                                 hovertemplate="Stock %{x|%a %d-%b}: %{y:,.0f} cj<extra></extra>"))
        if not rc.empty:
            fig.add_trace(go.Scatter(x=rc["fecha"], y=s.set_index("fecha")["exist_cajas"].reindex(rc["fecha"]).values,
                                     mode="markers", name="Recepción detectada",
                                     marker=dict(size=12, color=U.SERIE[2], symbol="triangle-up",
                                                 line=dict(width=1, color="white")),
                                     customdata=rc["recibido"],
                                     hovertemplate="Recepción %{x|%d-%b}: +%{customdata:,.0f} cj<extra></extra>"))
        if pd.notna(row["consumo_dia"]) and row["consumo_dia"] > 0 and pd.notna(row["stock_cajas"]):
            dias = int(min(row["dias_cobertura"], 60)) if np.isfinite(row["dias_cobertura"]) else 30
            f0 = row["fecha_stock"].normalize()
            xs = pd.date_range(f0, f0 + pd.Timedelta(days=dias))
            ys = np.maximum(row["stock_cajas"] - row["consumo_dia"] * np.arange(len(xs)), 0)
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="Proyección de stock",
                                     line=dict(color=U.AZUL, width=2, dash="dot"),
                                     hovertemplate="Proyección %{x|%d-%b}: %{y:,.0f} cj<extra></extra>"))
        U.plot(fig, 380, "Stock vs pedidos (cajas)")
        st.caption("Barras = cajas que pidió Favorita · Línea = stock en su CD · ▲ = subida de stock (llegó tu mercadería) · "
                   "Punteada = proyección con el consumo actual.")

    st.markdown("##### Mapa stock vs demanda")
    sc = TABLA.dropna(subset=["stock_cajas"]).copy()
    sc = sc[sc["pedido_prom_12s"] > 0]
    fig = go.Figure()
    for est in A.ESTADO_ORDEN:
        d = sc[sc["estado"] == est]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(x=d["pedido_prom_12s"], y=d["stock_cajas"], mode="markers",
                                 name=f"{A.ESTADO_ICONO[est]} {est}", text=d["producto"],
                                 marker=dict(size=11, color=U.STATUS[est], line=dict(width=2, color="white")),
                                 hovertemplate="<b>%{text}</b><br>Pedido prom.: %{x:,.0f} cj/sem<br>Stock: %{y:,.0f} cj<extra></extra>"))
    if len(sc):
        mx = sc["pedido_prom_12s"].max() * 1.05
        for sem, lab in [(1, "1 sem"), (2, "2 sem"), (4, "4 sem")]:
            fig.add_trace(go.Scatter(x=[0, mx], y=[0, mx * sem], mode="lines+text", showlegend=False,
                                     line=dict(color=U.GRID, width=1, dash="dash"), hoverinfo="skip",
                                     text=["", lab], textposition="top left", textfont=dict(size=10, color="#898781")))
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title="Pedido promedio semanal (cajas)")
    fig.update_yaxes(title="Stock actual en Favorita (cajas)")
    U.plot(fig, 420, closest=True)
    st.caption("Debajo de la línea '1 sem' Favorita tiene menos stock que un pedido promedio → es probable que te pida más.")


# =============================================================================
# TAB 3 · PATRONES
# =============================================================================
with tabs[2]:
    w = A.semanal(P)
    if w.empty:
        st.info("No hay pedidos para analizar.")
    else:
        c1, c2 = st.columns([1, 1.4])
        with c1:
            dd = A.dias_de_pedido(P)
            fig = go.Figure(go.Bar(x=dd["dia_nombre"], y=dd["pedidos"], marker=dict(color=U.AZUL, cornerradius=4),
                                   customdata=np.c_[dd["pct"] * 100, dd["cajas"]],
                                   hovertemplate="%{x}: %{y} pedidos (%{customdata[0]:.0f}%)<br>%{customdata[1]:,.0f} cajas<extra></extra>"))
            U.plot(fig, 300, "¿Qué día llegan los pedidos?", leyenda=False)
        with c2:
            mw = P.merge(MAESTRO[["codigo", "marca"]], on="codigo", how="left")
            mw["semana"] = A.inicio_semana(mw["fecha"])
            gm = mw.groupby(["semana", "marca"])["cajas"].sum().unstack(fill_value=0).tail(26)
            orden = gm.sum().sort_values(ascending=False).index.tolist()
            top = orden[:4]
            if len(orden) > 4:
                gm["Otras"] = gm[orden[4:]].sum(axis=1)
                top = top + ["Otras"]
            fig = go.Figure()
            for i, mk in enumerate(top):
                fig.add_trace(go.Scatter(x=gm.index, y=gm[mk], name=mk, mode="lines",
                                         line=dict(color=U.SERIE[i] if mk != "Otras" else "#898781", width=2),
                                         hovertemplate=f"{mk}: %{{y:,.0f}} cj<extra></extra>"))
            U.plot(fig, 300, "Cajas pedidas por marca (semanal)")

        st.markdown("##### Mapa de calor: cajas pedidas por SKU y semana")
        nsem = st.slider("Semanas a mostrar", 8, min(52, len(w)), min(20, len(w)), key="hm_sem")
        wh = w.tail(nsem)
        orden_sku = wh.sum().sort_values(ascending=False)
        orden_sku = orden_sku[orden_sku > 0].index
        wh = wh[orden_sku]
        fig = go.Figure(go.Heatmap(
            z=wh.T.values, x=[d.strftime("%d-%b") for d in wh.index], y=[NOMBRE.get(c, c)[:38] for c in wh.columns],
            colorscale=[[i / (len(U.SEQ_AZUL) - 1), c] for i, c in enumerate(U.SEQ_AZUL)], xgap=2, ygap=2,
            hovertemplate="%{y}<br>Semana %{x}: %{z:,.0f} cj<extra></extra>", colorbar=dict(title="cj", thickness=10)))
        fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
        U.plot(fig, max(380, 16 * len(wh.columns) + 80), leyenda=False, closest=True)

        st.markdown("##### Clasificación ABC-XYZ (últimas 16 semanas)")
        st.caption("**ABC** por volumen (A = 80 % de las cajas). **XYZ** por regularidad: X = estable y predecible, "
                   "Y = variable, Z = errático/esporádico. Los AX son los que más te conviene tener siempre listos.")
        ax = A.abc_xyz(w)
        ax["producto"] = ax["codigo"].map(NOMBRE)
        ax["frecuencia"] = ax["frecuencia"] * 100
        c1, c2 = st.columns([1, 2])
        with c1:
            mat = pd.crosstab(ax["ABC"], ax["XYZ"]).reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"], fill_value=0)
            fig = go.Figure(go.Heatmap(z=mat.values, x=mat.columns, y=mat.index, text=mat.values, texttemplate="%{text}",
                                       colorscale=[[0, U.SEQ_AZUL[0]], [1, U.SEQ_AZUL[5]]], showscale=False, xgap=3, ygap=3,
                                       hovertemplate="%{y}%{x}: %{z} SKUs<extra></extra>"))
            fig.update_yaxes(autorange="reversed")
            U.plot(fig, 280, "SKUs por segmento", leyenda=False, closest=True)
        with c2:
            st.dataframe(ax[["ABC", "XYZ", "producto", "total_cajas", "prom_semanal", "frecuencia", "cv"]],
                         hide_index=True, width="stretch", height=280,
                         column_config={
                             "producto": st.column_config.TextColumn("Producto", width="large"),
                             "total_cajas": st.column_config.NumberColumn("Cajas 16s", format="%.0f"),
                             "prom_semanal": st.column_config.NumberColumn("Prom/sem", format="%.1f"),
                             "frecuencia": st.column_config.ProgressColumn("Frecuencia", format="%.0f%%", min_value=0, max_value=100),
                             "cv": st.column_config.NumberColumn("Variabilidad (CV)", format="%.2f"),
                         })


# =============================================================================
# TAB 4 · PREDICCIÓN
# =============================================================================
with tabs[3]:
    if PRON.empty:
        st.info("Se necesitan pedidos históricos para pronosticar.")
    else:
        met = F.metricas_globales(BT)
        prec = met.set_index("modelo")["Precisión"] if not met.empty else pd.Series(dtype=float)
        mejor = met.iloc[0]["modelo"] if not met.empty else "—"
        fecha_p = PRON["fecha_pedido_estimada"].iloc[0]
        tot = PRON["pronostico_cajas"].sum()
        # rango agregado: los errores de SKUs distintos se compensan (suma cuadrática)
        semi = float(np.sqrt(((PRON["rango_max"] - PRON["pronostico_cajas"]) ** 2).sum()))
        lo, hi = max(tot - semi, 0), tot + semi
        aumento = PRON[(PRON["pronostico_cajas"] > PRON["prom_12s"] * 1.2) & (PRON["pronostico_cajas"] >= 10)]

        k = st.columns(4)
        k[0].metric("Pedido estimado (total)", U.fmt_num(tot, suf=" cj"),
                    help="Suma del pronóstico de todos los SKUs filtrados")
        k[1].metric(f"Rango ({nivel})", f"{U.fmt_num(lo)} – {U.fmt_num(hi)} cj")
        k[2].metric("Precisión del modelo", U.fmt_num(prec.get(mejor, np.nan) * 100, 0, " %"),
                    delta=f"{(prec.get(mejor, 0) - prec.get('PM4', 0)) * 100:+.0f} pts vs promedio móvil" if "PM4" in prec else None,
                    help="1 − WAPE en las últimas 8 semanas (predicción semana a semana sin ver el futuro)")
        k[3].metric("SKUs que suben ≥ 20 %", f"{len(aumento)}", help="Pronóstico > 120 % del promedio de 12 semanas")

        st.markdown("##### Próximo pedido por SKU y lo que deberías tener listo")
        st.caption("Escribe tu **stock en bodega Proquim** para ver faltantes. *Tener listo* = extremo alto del rango "
                   f"({nivel}) para no quedarte corto.")
        base = PRON.copy()
        base["señal"] = np.select(
            [base["pronostico_cajas"] > base["prom_12s"] * 1.2, base["pronostico_cajas"] < base["prom_12s"] * 0.8],
            ["⬆️ Sube", "⬇️ Baja"], "➡️ Normal")
        base["stock_bodega"] = np.nan
        base["prob_pedido"] = (base["prob_pedido"] * 100).round()
        vista = base[["codigo", "producto", "señal", "pronostico_cajas", "rango_min", "rango_max", "prob_pedido",
                      "stock_actual", "stock_proyectado", "stock_objetivo_S", "modelo", "stock_bodega"]]
        ed = st.data_editor(
            vista, hide_index=True, width="stretch", height=460, key="ed_pron",
            disabled=[c for c in vista.columns if c != "stock_bodega"],
            column_config={
                "codigo": None,
                "producto": st.column_config.TextColumn("Producto", width="large"),
                "señal": "Señal",
                "pronostico_cajas": st.column_config.NumberColumn("Pronóstico (cj)", format="%.0f"),
                "rango_min": st.column_config.NumberColumn("Mín", format="%.0f"),
                "rango_max": st.column_config.NumberColumn("Tener listo", format="%.0f"),
                "prob_pedido": st.column_config.ProgressColumn("Prob. pedido", format="%.0f%%", min_value=0, max_value=100),
                "stock_actual": st.column_config.NumberColumn("Stock Fav. hoy", format="%.0f"),
                "stock_proyectado": st.column_config.NumberColumn("Stock Fav. al pedido", format="%.0f"),
                "stock_objetivo_S": st.column_config.NumberColumn("Stock objetivo Fav.", format="%.0f",
                                                                   help="Nivel al que Favorita suele reponer (aprendido del historial)"),
                "modelo": "Modelo",
                "stock_bodega": st.column_config.NumberColumn("✏️ Stock bodega Proquim", format="%.0f", min_value=0),
            })
        if ed["stock_bodega"].notna().any():
            fal = ed.dropna(subset=["stock_bodega"]).assign(faltante=lambda d: (d["rango_max"] - d["stock_bodega"]).clip(lower=0))
            fal = fal[fal["faltante"] > 0]
            if fal.empty:
                st.success("Con tu stock de bodega cubres el extremo alto del pronóstico en los SKUs ingresados. ✅")
            else:
                st.warning(f"Te faltarían **{fal['faltante'].sum():,.0f} cajas** en {len(fal)} SKU(s) para cubrir el escenario alto.")
                st.dataframe(fal[["producto", "rango_max", "stock_bodega", "faltante"]], hide_index=True, width="stretch",
                             column_config={"rango_max": st.column_config.NumberColumn("Tener listo", format="%.0f"),
                                            "stock_bodega": st.column_config.NumberColumn("Bodega", format="%.0f"),
                                            "faltante": st.column_config.NumberColumn("Faltante", format="%.0f")})

        st.download_button("⬇️ Descargar pronóstico (Excel)", width="content",
                           data=U.excel_bytes({"Pronostico": ed.assign(fecha_pedido=fecha_p),
                                               "Stock_vs_Pedidos": TABLA, "Precision_modelos": met}),
                           file_name=f"pronostico_favorita_{fecha_p:%Y-%m-%d}.xlsx")

        st.markdown("##### Detalle del pronóstico")
        c1, c2 = st.columns([2, 1])
        with c1:
            sku = st.selectbox("Producto", PRON["codigo"], format_func=lambda c: f"{NOMBRE.get(c, c)} · {c}", key="sku_pron")
            r = PRON.set_index("codigo").loc[sku]
            ws_ = A.semanal(P[P["codigo"] == sku])[sku].tail(26) if sku in A.semanal(P[P["codigo"] == sku]).columns else pd.Series(dtype=float)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=ws_.index, y=ws_.values, name="Pedido real", marker=dict(color=U.NARANJA, cornerradius=4),
                                 hovertemplate="Semana %{x|%d-%b}: %{y:,.0f} cj<extra></extra>"))
            b = BT[(BT["codigo"] == sku) & (BT["modelo"] == r["modelo"])]
            if not b.empty:
                fig.add_trace(go.Scatter(x=b["semana"], y=b["pred"], name=f"Lo que predijo ({r['modelo']})", mode="lines+markers",
                                         line=dict(color=U.AZUL, width=2), marker=dict(size=8, line=dict(width=2, color="white")),
                                         hovertemplate="Predicho: %{y:,.0f} cj<extra></extra>"))
            semp = r["fecha_pedido_estimada"] - pd.Timedelta(days=r["fecha_pedido_estimada"].weekday())
            fig.add_trace(go.Scatter(x=[semp], y=[r["pronostico_cajas"]], mode="markers", name="Próximo pedido",
                                     marker=dict(size=13, color=U.AZUL, symbol="diamond", line=dict(width=2, color="white")),
                                     error_y=dict(type="data", symmetric=False,
                                                  array=[r["rango_max"] - r["pronostico_cajas"]],
                                                  arrayminus=[r["pronostico_cajas"] - r["rango_min"]], color=U.AZUL, thickness=2),
                                     hovertemplate="Pronóstico: %{y:,.0f} cj<extra></extra>"))
            U.plot(fig, 360, NOMBRE.get(sku, sku))
        with c2:
            card = st.container(border=True)
            card.metric("Pronóstico", U.fmt_num(r["pronostico_cajas"], suf=" cj"),
                      delta=f"{(r['pronostico_cajas'] / r['prom_12s'] - 1) * 100:+.0f}% vs prom. 12s" if r["prom_12s"] else None)
            card.write(f"**Rango:** {U.fmt_num(r['rango_min'])} – {U.fmt_num(r['rango_max'])} cj")
            card.write(f"**Modelo elegido:** {r['modelo']} (error medio {U.fmt_num(r['mae_modelo'], 1)} cj; "
                     f"promedio móvil {U.fmt_num(r['mae_pm4'], 1)} cj)")
            if r.get("stock_desactualizado", False):
                card.warning("La última foto de stock de este SKU tiene más de 7 días (no vino en el último reporte del bot). "
                             "El pronóstico usa solo el historial de pedidos.", icon="⚠️")
            elif pd.notna(r["stock_objetivo_S"]) and pd.notna(r["stock_proyectado"]):
                card.write(f"Favorita suele reponer hasta **{U.fmt_num(r['stock_objetivo_S'])} cj**. "
                         f"Al día del pedido tendría ~**{U.fmt_num(r['stock_proyectado'])} cj** "
                         f"(hoy {U.fmt_num(r['stock_actual'])}, consume {U.fmt_num(r['consumo_dia'], 1)} cj/día).")
            if pd.notna(r["tendencia_4s"]):
                card.write(f"**Tendencia 4 semanas:** {r['tendencia_4s'] * 100:+.0f} %")
            modelos = ["PM4", "SES", "Croston", "Reposición", "Ensamble"]
            st.dataframe(pd.DataFrame({"Modelo": modelos, "Predicción (cj)": [r.get(f"pred_{mm}", np.nan) for mm in modelos]}),
                         hide_index=True, width="stretch",
                         column_config={"Predicción (cj)": st.column_config.NumberColumn(format="%.1f")})

        with st.expander("📐 ¿Cómo predice? · precisión de cada modelo"):
            st.markdown("""
- **PM4** – promedio de las últimas 4 semanas (la referencia).
- **SES** – suavizamiento exponencial: da más peso a las semanas recientes.
- **Croston-SBA** – especializado en pedidos intermitentes (semanas sin pedido).
- **Reposición** – imita cómo compra Favorita: aprende su *stock objetivo* por SKU (stock antes del pedido + cajas pedidas),
  proyecta su stock al día del pedido con el consumo actual y predice la diferencia. **Es el que usa el reporte del bot.**
- **Ensamble** – promedio de SES, Croston y Reposición.

Para cada SKU se simulan las últimas 8 semanas (predecir cada semana solo con datos anteriores) y se elige el modelo con menor error.
""")
            if not met.empty:
                fig = go.Figure(go.Bar(x=met["modelo"], y=met["Precisión"] * 100, marker=dict(color=U.AZUL, cornerradius=4),
                                       text=[f"{v * 100:.0f}%" for v in met["Precisión"]], textposition="outside",
                                       hovertemplate="%{x}: %{y:.1f}% de precisión<extra></extra>"))
                fig.update_yaxes(range=[0, 100], title="Precisión (1 − WAPE) %")
                U.plot(fig, 280, "Precisión por modelo · backtest 8 semanas", leyenda=False)


# =============================================================================
# TAB 5 · CUMPLIMIENTO
# =============================================================================
with tabs[4]:
    cu = A.cumplimiento(P, E)
    if cu.empty:
        st.info("Se necesita historial de stock diario para estimar tiempos de entrega.")
    else:
        ok = cu.dropna(subset=["lead_dias"])
        k = st.columns(4)
        k[0].metric("Pedidos analizados", f"{len(cu):,}".replace(",", " "))
        k[1].metric("Lead time mediano", U.fmt_num(ok["lead_dias"].median(), 0, " días"),
                    help="Días entre el pedido y la primera subida de stock en el CD")
        k[2].metric("Pedidos con recepción detectada", U.fmt_num(len(ok) / len(cu) * 100, 0, " %"))
        k[3].metric("Recepción neta / pedido (mediana)", U.fmt_num(ok["pct_recibido"].median() * 100, 0, " %"),
                    help="Subida neta de stock ÷ cajas pedidas. Es aproximado: si el mismo día hubo ventas, la subida neta es menor.")
        c1, c2 = st.columns(2)
        with c1:
            h = ok["lead_dias"].value_counts().sort_index()
            fig = go.Figure(go.Bar(x=h.index, y=h.values, marker=dict(color=U.AZUL, cornerradius=4),
                                   hovertemplate="%{x} días: %{y} pedidos<extra></extra>"))
            fig.update_xaxes(title="Días desde el pedido hasta la recepción", dtick=1)
            U.plot(fig, 300, "Tiempo de entrega", leyenda=False)
        with c2:
            g = cu.groupby("codigo").agg(pedidos=("cajas", "size"), cajas=("cajas", "sum"),
                                         lead=("lead_dias", "median"), pct=("pct_recibido", "median")).reset_index()
            g["producto"] = g["codigo"].map(NOMBRE)
            g["pct"] = g["pct"] * 100
            st.dataframe(g.sort_values("cajas", ascending=False)[["producto", "pedidos", "cajas", "lead", "pct"]],
                         hide_index=True, width="stretch", height=300,
                         column_config={"producto": st.column_config.TextColumn("Producto", width="large"),
                                        "cajas": st.column_config.NumberColumn("Cajas pedidas", format="%.0f"),
                                        "lead": st.column_config.NumberColumn("Lead (días)", format="%.0f"),
                                        "pct": st.column_config.ProgressColumn("Recepción/pedido", format="%.0f%%",
                                                                               min_value=0, max_value=120)})
        st.caption("Estimado a partir de las subidas del stock diario del CD. Úsalo como indicador, no como conciliación contable.")


# =============================================================================
# TAB 6 · DATOS
# =============================================================================
with tabs[5]:
    st.markdown("##### Fuentes cargadas")
    st.dataframe(pd.DataFrame(estado_fuentes, columns=["Fuente", "Filas de pedidos", "Filas de stock"]),
                 hide_index=True, width="stretch")
    if gs_error:
        st.error(gs_error)
    c1, c2 = st.columns(2)
    c1.markdown(f"**Pedidos consolidados:** {len(PEDIDOS):,} filas · {PEDIDOS['fecha'].min():%d-%b-%Y} → {PEDIDOS['fecha'].max():%d-%b-%Y}"
                if not PEDIDOS.empty else "**Pedidos:** —")
    c2.markdown(f"**Stock consolidado:** {len(EXIST):,} filas · {EXIST['fecha'].min():%d-%b-%Y} → {EXIST['fecha'].max():%d-%b-%Y}"
                if not EXIST.empty else "**Stock:** —")
    sub = st.segmented_control("Ver", ["Pedidos", "Stock", "Productos", "Historial_Pedidos (crudo)"], default="Pedidos", key="ver_datos")
    d = {"Pedidos": PEDIDOS.assign(producto=PEDIDOS["codigo"].map(NOMBRE)),
         "Stock": EXIST, "Productos": MAESTRO,
         "Historial_Pedidos (crudo)": raw_hist if raw_hist is not None else pd.DataFrame()}[sub or "Pedidos"]
    st.dataframe(d, hide_index=True, width="stretch", height=420)
    st.download_button("⬇️ Descargar datos consolidados (Excel)",
                       data=U.excel_bytes({"Pedidos": PEDIDOS, "Stock": EXIST, "Productos": MAESTRO}),
                       file_name=f"datos_favorita_{hoy:%Y-%m-%d}.xlsx")
