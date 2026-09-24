"""Estilos, paleta y helpers visuales compartidos."""
from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Paleta validada (categórica en orden fijo, nunca ciclada)
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
AZUL, NARANJA = SERIE[0], SERIE[1]
SEQ_AZUL = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STATUS = {"Agotado": "#d03b3b", "Crítico": "#d03b3b", "Bajo": "#fab219", "OK": "#0ca30c",
          "Sobrestock": "#2a78d6", "Sin rotación": "#898781", "Sin dato": "#c3c2b7"}
GRID = "rgba(137,135,129,0.25)"

CSS = """
<style>
:root { --pq-accent:#2a78d6; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1400px; }
.pq-hero { display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap;
  padding: 1.1rem 1.3rem; border-radius: 14px; margin-bottom: 1rem;
  background: linear-gradient(120deg, rgba(42,120,214,.12), rgba(27,175,122,.10));
  border: 1px solid rgba(137,135,129,.25); }
.pq-hero h1 { font-size: 1.55rem; margin: 0; line-height: 1.2; }
.pq-hero p { margin: .2rem 0 0; opacity: .75; font-size: .92rem; }
.pq-badges { display:flex; gap:.4rem; flex-wrap:wrap; }
.pq-badge { font-size:.78rem; padding:.22rem .6rem; border-radius:999px; border:1px solid rgba(137,135,129,.35);
  background: rgba(137,135,129,.08); white-space:nowrap; }
.pq-badge.ok { border-color: rgba(12,163,12,.5); }
.pq-badge.warn { border-color: rgba(250,178,25,.7); }
div[data-testid="stMetric"] { background: rgba(137,135,129,.07); border:1px solid rgba(137,135,129,.22);
  border-radius: 12px; padding: .7rem .9rem; }
div[data-testid="stMetricLabel"] p { font-size: .82rem; opacity: .8; }
.pq-note { font-size:.85rem; opacity:.75; }
.pq-card { border:1px solid rgba(137,135,129,.25); border-radius:12px; padding: .8rem 1rem; margin-bottom:.6rem;}
</style>
"""


def estilo():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(titulo: str, subtitulo: str, badges: list[tuple[str, str]]):
    b = "".join(f'<span class="pq-badge {k}">{t}</span>' for t, k in badges)
    st.markdown(f'<div class="pq-hero"><div><h1>{titulo}</h1><p>{subtitulo}</p></div>'
                f'<div class="pq-badges">{b}</div></div>', unsafe_allow_html=True)


def layout(fig: go.Figure, h: int = 340, titulo: str | None = None, leyenda=True) -> go.Figure:
    fig.update_layout(
        height=h, margin=dict(l=8, r=8, t=36 if leyenda else 12, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=12),
        hovermode="x unified", showlegend=leyenda,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        hoverlabel=dict(font_size=12),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def fmt_num(v, dec=0, suf=""):
    try:
        if v is None or pd.isna(v):
            return "—"
        if v == float("inf"):
            return "∞"
        return f"{v:,.{dec}f}{suf}".replace(",", " ")
    except Exception:
        return "—"


def excel_bytes(hojas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nombre, df in hojas.items():
            d = df.copy()
            for c in d.columns:
                if pd.api.types.is_datetime64_any_dtype(d[c]):
                    d[c] = d[c].dt.tz_localize(None) if getattr(d[c].dt, "tz", None) else d[c]
            d.to_excel(xw, sheet_name=nombre[:31], index=False)
            ws = xw.sheets[nombre[:31]]
            for i, col in enumerate(d.columns, 1):
                ancho = min(max(len(str(col)), *(len(str(x)) for x in d[col].head(200))) + 2, 48) if len(d) else len(str(col)) + 2
                ws.column_dimensions[ws.cell(1, i).column_letter].width = ancho
            ws.freeze_panes = "A2"
    return buf.getvalue()


def plot(fig: go.Figure, h: int = 340, titulo: str | None = None, leyenda: bool = True, closest: bool = False):
    """Título como texto (no dentro de Plotly, así nunca choca con la leyenda) + gráfico."""
    if titulo:
        st.markdown(f"<div style='font-weight:600;font-size:.95rem;margin:.4rem 0 -.2rem'>{titulo}</div>",
                    unsafe_allow_html=True)
    layout(fig, h, None, leyenda)
    if closest:
        fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
