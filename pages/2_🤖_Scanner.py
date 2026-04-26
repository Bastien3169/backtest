"""
pages/2_🤖_Scanner.py
Lance automatiquement une stratégie sur une sélection de cryptos.
"""

import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from src.utils.data_loader import fetch_ohlcv, get_top100_coins
from src.controllers.backtest import run_backtest_single
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Scanner", page_icon="🤖", layout="wide")
st.title("🤖 Scanner — Stratégie sur une sélection de cryptos")
st.caption("Configure une stratégie, choisis tes cryptos, lance le scan et compare les résultats.")

MM_LABELS = [1, 10, 20, 50, 100, 200]

# ---------------------------------------------------------------------------
# Sélection des cryptos — relecture fraîche de coins.py à chaque run
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Sélection des cryptos")

_coins     = get_top100_coins()
all_labels = [f"{c['symbol']} — {c['name']}" for c in _coins]
ticker_map = {f"{c['symbol']} — {c['name']}": c["id"] for c in _coins}

col_sel1, col_sel2 = st.columns([3, 1])
with col_sel2:
    select_all = st.checkbox("Tout sélectionner", value=False)

with col_sel1:
    default = all_labels if select_all else all_labels[:10]
    selected_labels = st.multiselect(
        "Cryptos à analyser",
        options=all_labels,
        default=default,
        help="Sélectionne les cryptos à inclure dans le scan",
    )

if not selected_labels:
    st.warning("Sélectionne au moins une crypto.")
    st.stop()

selected_tickers = [(label, ticker_map[label]) for label in selected_labels]
st.caption(f"{len(selected_tickers)} crypto(s) sélectionnée(s)")

st.divider()

# ---------------------------------------------------------------------------
# Paramètres généraux
# ---------------------------------------------------------------------------
st.subheader("2️⃣ Paramètres généraux")

pg1, pg2 = st.columns(2)
with pg1:
    timeframe = st.selectbox("Temporalité", ["jour", "heure", "semaine", "mois"])
    mode_duree = st.radio("Mode période", ["Durée fixe", "Plage de dates"], horizontal=True, key="scan_mode_duree")
    duree      = 360
    date_range = None
    if mode_duree == "Durée fixe":
        duree = st.number_input("Durée (nb bougies)", min_value=5, max_value=2000, value=360)
    else:
        from datetime import date, timedelta
        d1, d2 = st.columns(2)
        with d1:
            date_debut = st.date_input("Du", value=date.today() - timedelta(days=360), key="scan_d1")
        with d2:
            date_fin = st.date_input("Au", value=date.today(), key="scan_d2")
        if date_debut < date_fin:
            date_range = (date_debut, date_fin)
            duree = (date_fin - date_debut).days
            st.caption(f"→ {duree} jours")
        else:
            st.error("Date début doit être avant date fin")
with pg2:
    capital   = st.number_input("Capital (€)", min_value=1.0, value=1000.0, step=100.0)
    frais_pct = st.number_input("Frais (%)", 0.0, 10.0, 0.1, 0.01, format="%.2f")

st.divider()

# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------
st.markdown("#### 🟢 Indicateurs d'achat")
ind_achat = render_indicator_bloc("buy", "scan_buy")

st.divider()

st.markdown("#### 🔴 Indicateurs de vente")
st.caption("Laisser vide = mode hold")
cv1, cv2 = st.columns(2)
with cv1:
    tp_raw = st.number_input("Take Profit (%)", 0.0, 1000.0, 0.0, 0.5, help="0 = désactivé", key="scan_tp")
with cv2:
    sl_raw = st.number_input("Stop Loss (%)", 0.0, 100.0, 0.0, 0.5, help="0 = désactivé", key="scan_sl")
tp_pct = tp_raw if tp_raw > 0 else None
sl_pct = sl_raw if sl_raw > 0 else None
ind_vente = render_indicator_bloc("sell", "scan_sell")

st.divider()

# Construction de la stratégie
ind_achat["btc_mm"] = None
ind_vente["btc_mm"] = None
strategy = {
    "ind_achat": ind_achat,
    "ind_vente": ind_vente,
    "tp_pct":    tp_pct,
    "sl_pct":    sl_pct,
}

# ---------------------------------------------------------------------------
# Lancement du scan
# ---------------------------------------------------------------------------
st.subheader("3️⃣ Lancer le scan")

if st.button("🚀 Lancer le scan", type="primary"):
    results = []
    errors  = []
    total   = len(selected_tickers)
    prog    = st.progress(0, text="Initialisation...")

    for idx, (label, ticker) in enumerate(selected_tickers):
        prog.progress((idx + 1) / total, text=f"Analyse {ticker} ({idx+1}/{total})...")

        try:
            df  = fetch_ohlcv(ticker, timeframe)
            res = run_backtest_single(
                df=df, strategy=strategy,
                capital=capital, frais_pct=frais_pct, duree=duree,
                date_range=date_range if mode_duree == "Plage de dates" else None,
            )
            results.append({
                "Crypto":          label,
                "Rendement (%)":   res["rendement_pct"],
                "B&H (%)":        res["bnh_rendement"],
                "Alpha (%)":      round(res["rendement_pct"] - res["bnh_rendement"], 2),
                "Plus-value (€)": res["plus_value_eur"],
                "Drawdown (%)":   res["drawdown_max"],
                "Nb trades":      res["nb_trades"],
                "Win rate (%)":   res["win_rate"],
            })
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    prog.empty()

    if errors:
        with st.expander(f"⚠️ {len(errors)} erreurs de chargement", expanded=False):
            for e in errors:
                st.caption(e)

    if results:
        df_res = pd.DataFrame(results).sort_values("Rendement (%)", ascending=False)
        st.session_state["scan_results"] = df_res
        st.success(f"✅ Scan terminé — {len(results)} cryptos analysées")

# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------
if "scan_results" in st.session_state:
    df_res = st.session_state["scan_results"]

    sort_col = st.selectbox("Trier par", df_res.columns[1:], index=0, key="scan_sort")
    asc      = st.radio("Ordre", ["↓ Décroissant", "↑ Croissant"], horizontal=True, key="scan_asc") == "↑ Croissant"
    df_res   = df_res.sort_values(sort_col, ascending=asc)

    def color_val(val):
        if not isinstance(val, (int, float)):
            return ""
        return f"color: {'#22C55E' if val > 0 else '#EF4444' if val < 0 else '#888'}"

    styled = (
        df_res.style
        .format({
            "Rendement (%)":   "{:.2f}",
            "B&H (%)":        "{:.2f}",
            "Alpha (%)":      "{:.2f}",
            "Plus-value (€)": "{:.2f}",
            "Drawdown (%)":   "{:.2f}",
            "Win rate (%)":   "{:.1f}",
        })
        .map(color_val, subset=["Rendement (%)", "Alpha (%)"])
    )
    st.dataframe(styled, use_container_width=True, height=600)

    st.subheader("🏆 Top 5 — Meilleur rendement")
    for _, row in df_res.head(5).iterrows():
        color = "#22C55E" if row["Rendement (%)"] > 0 else "#EF4444"
        st.markdown(
            f"**{row['Crypto']}** — "
            f"<span style='color:{color}'>{row['Rendement (%)']:+.2f}%</span> "
            f"| Alpha : {row['Alpha (%)']:+.2f}% "
            f"| {int(row['Nb trades'])} trades",
            unsafe_allow_html=True,
        )
