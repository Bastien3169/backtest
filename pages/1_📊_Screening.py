"""
pages/1_📊_Screening.py
Tableau de screening des cryptos.
"""

import sys
import os

# Remonte jusqu'à la racine du projet (dossier contenant app.py)
_HERE = os.path.abspath(__file__)                  # .../pages/1_...py
_PAGES_DIR = os.path.dirname(_HERE)                # .../pages/
_ROOT = os.path.dirname(_PAGES_DIR)               # .../app_backtest/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from src.utils.market_data import load_screening_data
from src.utils.coins_updater import update_coins
from src.utils.data_loader import get_top100_coins

st.set_page_config(page_title="Screening Crypto", page_icon="📊", layout="wide")

st.title("📊 Screening Crypto")
st.caption(
    "**Corr. BTC** : 100% = suit parfaitement le BTC  ·  "
    "**Volatilité** : agitation propre de l'alt (indépendant du BTC)  ·  "
    "**Bêta** : réactivité aux mouvements du BTC (BTC +1% → alt +β%)"
)

# Lecture fraîche à chaque run
_nb_coins = len(get_top100_coins())

# ---------------------------------------------------------------------------
# Mise à jour de la liste des cryptos
# ---------------------------------------------------------------------------
with st.expander("🔁 Mettre à jour la liste des cryptos (top 100 CoinGecko)", expanded=False):
    st.markdown(
        f"Liste actuelle : **{_nb_coins} cryptos** vérifiées sur yfinance.  \n"
        "Ce bouton récupère le top 100 CoinGecko par market cap, teste chaque ticker "
        "sur Yahoo Finance et met à jour la liste automatiquement.  \n"
        "⏱ Durée estimée : **2-4 minutes**."
    )
    if st.button("🚀 Lancer la mise à jour", type="primary", key="update_coins"):
        prog = st.progress(0, text="Connexion à CoinGecko...")
        status = st.empty()
        try:
            available, skipped = update_coins(
                progress_cb=lambda p, m: prog.progress(p, text=m)
            )
            prog.empty()
            st.success(f"✅ {len(available)} cryptos disponibles sur yfinance")
            if skipped:
                st.warning(f"⚠️ {len(skipped)} tickers ignorés : {', '.join(skipped)}")
            st.info("✅ La liste est mise à jour — elle sera active au prochain chargement de données.")
        except Exception as e:
            prog.empty()
            st.error(f"❌ Erreur : {e}")

# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
if "screening_df" not in st.session_state:
    st.session_state.screening_df = None

if st.button("🔄 Charger / Actualiser", type="primary"):
    progress = st.progress(0, text="Initialisation...")
    st.session_state.screening_df = load_screening_data(
        progress_cb=lambda p, m: progress.progress(p, text=m)
    )
    progress.empty()
    st.success(f"✅ {len(st.session_state.screening_df)} cryptos chargées")

df = st.session_state.screening_df
if df is None or df.empty:
    st.info("Cliquez sur **Charger / Actualiser** pour afficher le tableau.")
    st.stop()

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
with st.expander("🔧 Filtres", expanded=False):
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        corr_min = st.slider("Corrélation BTC min (%)", 0, 100, 0)
    with fc2:
        beta_max = st.slider("Bêta max", 1.0, 5.0, 5.0, step=0.1)
    with fc3:
        vol_max = st.slider("Volatilité max", 1.0, 5.0, 5.0, step=0.1)
    with fc4:
        perf_filter = st.radio("Perf. 7j", ["Toutes", "✅ Positives", "🔴 Négatives"], horizontal=True)

df_filtered = df[
    (df["corr_btc"]   >= corr_min) &
    (df["beta"]       <= beta_max) &
    (df["volatility"] <= vol_max)
].copy()

if perf_filter == "✅ Positives":
    df_filtered = df_filtered[df_filtered["perf_7d"] >= 0]
elif perf_filter == "🔴 Négatives":
    df_filtered = df_filtered[df_filtered["perf_7d"] < 0]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_large(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if val >= 1e9:
        return f"{val/1e9:.1f} Md€"
    if val >= 1e6:
        return f"{val/1e6:.0f} M€"
    return f"{val:,.0f} €"

def stars(v):
    filled = max(1, min(5, int(round(v))))
    return "●" * filled + "○" * (5 - filled)

def star_color(v):
    return "#EF4444" if v >= 4 else "#F59E0B" if v >= 2.5 else "#22C55E"

def sparkline_fig(values, perf):
    color = "#22C55E" if perf >= 0 else "#EF4444"
    fill  = "rgba(34,197,94,0.12)" if perf >= 0 else "rgba(239,68,68,0.12)"
    fig = go.Figure(go.Scatter(
        y=values, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=fill,
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=55, width=150,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    return fig

# ---------------------------------------------------------------------------
# En-têtes avec tri au clic
# ---------------------------------------------------------------------------
COLS = {
    "Crypto":       None,
    "Corr. BTC %":  "corr_btc",
    "Volatilité":   "volatility",
    "Bêta vs BTC":  "beta",
    "Volume 24h":   "volume_24h",
    "Perf. 7j":     "perf_7d",
    "Graphe 7j":    None,
}
WIDTHS = [2, 1.3, 1.3, 1.5, 1.5, 1.3, 1.8]

if "sort_col" not in st.session_state:
    st.session_state.sort_col = "corr_btc"
if "sort_asc" not in st.session_state:
    st.session_state.sort_asc = False

st.divider()
hcols = st.columns(WIDTHS)
for ui_col, (label, key) in zip(hcols, COLS.items()):
    with ui_col:
        if key:
            arrow = (" ↑" if st.session_state.sort_asc else " ↓") if st.session_state.sort_col == key else ""
            if st.button(f"{label}{arrow}", key=f"hdr_{key}", width='stretch'):
                if st.session_state.sort_col == key:
                    st.session_state.sort_asc = not st.session_state.sort_asc
                else:
                    st.session_state.sort_col = key
                    st.session_state.sort_asc = False
                st.rerun()
        else:
            st.markdown(f"**{label}**")

df_filtered = df_filtered.sort_values(
    st.session_state.sort_col, ascending=st.session_state.sort_asc
)

st.divider()

# ---------------------------------------------------------------------------
# Lignes
# ---------------------------------------------------------------------------
# Bêta approx pour affichage (score → bêta)
BP_INV  = [1.0, 2.0, 3.0, 4.0, 5.0]
BETA_INV = [0.5, 1.0, 2.0, 3.5, 5.0]

for _, row in df_filtered.iterrows():
    c1, c2, c3, c4, c5, c6, c7 = st.columns(WIDTHS)

    with c1:
        st.markdown(f"**{row['symbol']}**  \n<span style='color:#888;font-size:12px'>{row['name']}</span>",
                    unsafe_allow_html=True)

    with c2:
        corr = row["corr_btc"]
        bar  = "#3B82F6" if corr >= 70 else "#F59E0B" if corr >= 40 else "#6B7280"
        st.markdown(
            f"<div style='font-weight:bold'>{corr:.0f}%</div>"
            f"<div style='background:#333;border-radius:3px;height:5px;margin-top:3px'>"
            f"<div style='background:{bar};width:{corr}%;height:5px;border-radius:3px'></div></div>",
            unsafe_allow_html=True,
        )

    with c3:
        v = row["volatility"]
        sc = star_color(v)
        st.markdown(
            f"<span style='color:{sc};font-size:15px'>{stars(v)}</span>"
            f"<span style='font-size:11px;color:#666;margin-left:5px'>{v:.1f}/5</span>"
            f"<div style='font-size:10px;color:#555'>std jours. ≈ propre</div>",
            unsafe_allow_html=True,
        )

    with c4:
        b = row["beta"]
        sc = star_color(b)
        beta_approx = float(np.interp(b, BP_INV, BETA_INV))
        st.markdown(
            f"<span style='color:{sc};font-size:15px'>{stars(b)}</span>"
            f"<span style='font-size:11px;color:#666;margin-left:5px'>β≈{beta_approx:.1f}</span>"
            f"<div style='font-size:10px;color:#555'>BTC+1% → {beta_approx:+.1f}%</div>",
            unsafe_allow_html=True,
        )

    with c5:
        st.markdown(fmt_large(row["volume_24h"]))

    with c6:
        perf = row["perf_7d"]
        color = "#22C55E" if perf >= 0 else "#EF4444"
        arrow = "▲" if perf >= 0 else "▼"
        st.markdown(
            f"<span style='color:{color};font-weight:bold;font-size:15px'>{arrow} {abs(perf):.2f}%</span>",
            unsafe_allow_html=True,
        )

    with c7:
        spark = row.get("sparkline", [])
        if len(spark) >= 2:
            st.plotly_chart(sparkline_fig(spark, row["perf_7d"]),
                            width='content',
                            config={"displayModeBar": False})
        else:
            st.caption("—")

    st.divider()

st.caption(f"{len(df_filtered)} cryptos affichées · Source : yfinance · Mise à jour manuelle")
