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
# Exclure les stablecoins — inutiles à backtester
_EXCLUDE   = {"USDC", "USDT", "BUSD", "DAI", "TUSD", "FDUSD"}
_coins     = [c for c in _coins if c["symbol"] not in _EXCLUDE]
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

from datetime import date, timedelta

pg1, pg2 = st.columns(2)
with pg1:
    timeframe  = st.selectbox("Temporalité", ["jour", "heure", "semaine", "mois"])
    mode_duree = st.radio("Mode période",
                          ["Durées fixes", "Plages de dates"],
                          horizontal=True, key="scan_mode_duree")
with pg2:
    capital   = st.number_input("Capital (€)", min_value=1.0, value=1000.0, step=100.0)
    frais_pct = st.number_input("Frais (%)", 0.0, 10.0, 0.1, 0.01, format="%.2f")

durees      = [360]
date_ranges = []

if mode_duree == "Durées fixes":
    durees_raw = st.text_input(
        "Durées (nb bougies, séparées par des virgules)",
        value="180,360,720",
        help="Ex : 180,360,720 — chaque valeur = une colonne dans les résultats",
        key="scan_durees_raw",
    )
    try:
        durees = sorted(set(int(x.strip()) for x in durees_raw.split(",") if x.strip().isdigit()))
    except Exception:
        durees = [360]
else:
    if "scan_date_ranges" not in st.session_state:
        st.session_state.scan_date_ranges = [
            (date.today() - timedelta(days=360), date.today())
        ]

    col_add, col_clear = st.columns(2)
    with col_add:
        if st.button("➕ Ajouter une plage", key="scan_add_range", use_container_width=True):
            st.session_state.scan_date_ranges.append(
                (date.today() - timedelta(days=90), date.today())
            )
            st.rerun()
    with col_clear:
        if st.button("🗑️ Tout effacer", key="scan_clear_range", use_container_width=True):
            st.session_state.scan_date_ranges = [
                (date.today() - timedelta(days=360), date.today())
            ]
            st.rerun()

    new_ranges = []
    for idx_r, (d1, d2) in enumerate(st.session_state.scan_date_ranges):
        st.markdown(f"**Plage {idx_r + 1}**")
        r1, r2, r3 = st.columns([2, 2, 1])
        with r1:
            nd1 = st.date_input("Du", value=d1, key=f"scan_d1_{idx_r}")
        with r2:
            nd2 = st.date_input("Au", value=d2, key=f"scan_d2_{idx_r}")
        with r3:
            st.write("")
            if st.button("✕", key=f"scan_del_{idx_r}") and len(st.session_state.scan_date_ranges) > 1:
                st.session_state.scan_date_ranges.pop(idx_r)
                st.rerun()
        if nd1 < nd2:
            new_ranges.append((nd1, nd2))
            st.caption(f"→ {(nd2 - nd1).days} jours")
        else:
            st.error(f"Plage {idx_r + 1} : date début avant date fin")

    st.session_state.scan_date_ranges = new_ranges
    date_ranges = new_ranges
    durees = [max(1, (d2 - d1).days) for d1, d2 in date_ranges]

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
            df = fetch_ohlcv(ticker, timeframe)
            row = {"Crypto": label}

            for i, d in enumerate(durees):
                dr = date_ranges[i] if mode_duree == "Plages de dates" and i < len(date_ranges) else None
                res = run_backtest_single(
                    df=df, strategy=strategy,
                    capital=capital, frais_pct=frais_pct,
                    duree=d, date_range=dr,
                )
                # Label colonne
                if dr:
                    col_label = f"{dr[0].strftime('%d/%m/%y')}→{dr[1].strftime('%d/%m/%y')}"
                else:
                    col_label = f"{d}j"

                row[f"Rendement {col_label} (%)"] = res["rendement_pct"]
                row[f"B&H {col_label} (%)"]       = res["bnh_rendement"]
                row[f"Trades {col_label}"]         = res["nb_trades"]
                row[f"Win rate {col_label} (%)"]   = res["win_rate"]

            results.append(row)
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    prog.empty()

    if errors:
        with st.expander(f"⚠️ {len(errors)} erreurs de chargement", expanded=False):
            for e in errors:
                st.caption(e)

    if results:
        df_res = pd.DataFrame(results)
        # Trier par la première colonne de rendement disponible
        rend_cols = [c for c in df_res.columns if "Rendement" in c]
        if rend_cols:
            df_res = df_res.sort_values(rend_cols[0], ascending=False)
        st.session_state["scan_results"] = df_res
        st.success(f"✅ Scan terminé — {len(results)} cryptos analysées")

# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------
if "scan_results" in st.session_state:
    df_res = st.session_state["scan_results"]

    # Colonnes de rendement pour colorisation
    rend_cols = [c for c in df_res.columns if "Rendement" in c]

    sort_col = st.selectbox("Trier par", df_res.columns[1:], index=0, key="scan_sort")
    asc      = st.radio("Ordre", ["↓ Décroissant", "↑ Croissant"],
                        horizontal=True, key="scan_asc") == "↑ Croissant"
    df_res   = df_res.sort_values(sort_col, ascending=asc)

    def color_val(val):
        if not isinstance(val, (int, float)):
            return ""
        return f"color: {'#22C55E' if val > 0 else '#EF4444' if val < 0 else '#888'}"

    # Format numérique pour toutes les colonnes sauf Crypto et Trades
    fmt_dict = {}
    for c in df_res.columns:
        if c == "Crypto":
            continue
        elif "Trades" in c:
            fmt_dict[c] = "{:.0f}"
        else:
            fmt_dict[c] = "{:.2f}"

    styled = (
        df_res.style
        .format(fmt_dict)
        .map(color_val, subset=rend_cols)
    )
    st.dataframe(styled, use_container_width=True, height=600)

    st.subheader("🏆 Top 5 — Meilleur rendement")
    if rend_cols:
        top_col = rend_cols[0]
        for _, row in df_res.nlargest(5, top_col).iterrows():
            color = "#22C55E" if row[top_col] > 0 else "#EF4444"
            st.markdown(
                f"**{row['Crypto']}** — "
                f"<span style='color:{color}'>{row[top_col]:+.2f}%</span>",
                unsafe_allow_html=True,
            )
