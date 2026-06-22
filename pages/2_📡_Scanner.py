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
from datetime import date, timedelta

from src.utils.data_loader import fetch_ohlcv, get_all_assets
from src.controllers.backtest import run_backtest_single
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Scanner", page_icon="🤖", layout="wide")
st.title("🤖 Scanner — Cryptos & Indices")
st.caption("Configure une stratégie, choisis tes actifs, compare les résultats.")

# ---------------------------------------------------------------------------
# 1️⃣ Sélection des actifs
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Sélection des actifs")

_EXCLUDE = {"USDC", "USDT", "BUSD", "DAI", "TUSD", "FDUSD"}
_all     = [c for c in get_all_assets() if c["symbol"] not in _EXCLUDE]
_cryptos = [c for c in _all if not c["id"].startswith("^")]
_indices = [c for c in _all if c["id"].startswith("^")]

crypto_labels = [f"{c['symbol']} — {c['name']}" for c in _cryptos]
index_labels  = [f"{c['symbol']} — {c['name']}" for c in _indices]
all_labels    = crypto_labels + index_labels
ticker_map    = {f"{c['symbol']} — {c['name']}": c["id"] for c in _all}

col_sel1, col_sel2 = st.columns([3, 1])
with col_sel2:
    select_all   = st.checkbox("Tout sélectionner", value=False)
    show_indices = st.checkbox("Inclure indices", value=True)

with col_sel1:
    available = all_labels if show_indices else crypto_labels
    if select_all:
        default = available
    else:
        default = crypto_labels[:10] + (index_labels if show_indices else [])
    default = [d for d in default if d in available]
    selected_labels = st.multiselect(
        "Actifs à analyser",
        options=available,
        default=default,
    )

if not selected_labels:
    st.warning("Sélectionne au moins un actif.")
    st.stop()

selected_tickers = [(label, ticker_map[label]) for label in selected_labels]
st.caption(f"{len(selected_tickers)} actif(s) sélectionné(s)")

st.divider()

# ---------------------------------------------------------------------------
# 2️⃣ Paramètres généraux
# ---------------------------------------------------------------------------
st.subheader("2️⃣ Paramètres généraux")

pg1, pg2, pg3 = st.columns(3)
with pg1:
    timeframe  = st.selectbox("Temporalité", ["jour", "heure", "semaine", "mois"])
    mode_duree = st.radio("Mode période",
                          ["Durées fixes", "Plages de dates"],
                          horizontal=True, key="scan_mode_duree")
with pg2:
    capital   = st.number_input("Capital (€)", min_value=1.0, value=1000.0, step=100.0)
    frais_pct = st.number_input("Frais (%)", 0.0, 10.0, 0.1, 0.01, format="%.2f")
with pg3:
    is_short = st.radio(
        "Direction",
        ["🟢 Long", "🔴 Short"],
        horizontal=True, key="scan_direction"
    ) == "🔴 Short"
    if is_short:
        st.info("🔴 Mode Short — signal d'entrée = vente à découvert")

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
        if st.button("➕ Ajouter une plage", key="scan_add_range", width='stretch'):
            st.session_state.scan_date_ranges.append(
                (date.today() - timedelta(days=90), date.today())
            )
            st.rerun()
    with col_clear:
        if st.button("🗑️ Tout effacer", key="scan_clear_range", width='stretch'):
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
label_entry = "🟢 Indicateurs d'achat" if not is_short else "🔴 Indicateurs d'entrée short"
label_exit  = "🔴 Indicateurs de vente" if not is_short else "🟢 Indicateurs de sortie short"

st.markdown(f"#### {label_entry}")
ind_achat = render_indicator_bloc("buy" if not is_short else "sell", "scan_buy")

st.divider()

st.markdown(f"#### {label_exit}")
st.caption("Vente déclenchée si **TP/SL atteint OU indicateur de sortie actif** — laisser vide = hold")
cv1, cv2 = st.columns(2)
with cv1:
    tp_raw = st.number_input("Take Profit (%)", 0.0, 1000.0, 0.0, 0.5, help="0 = désactivé", key="scan_tp")
with cv2:
    sl_raw = st.number_input("Stop Loss (%)", 0.0, 100.0, 0.0, 0.5, help="0 = désactivé", key="scan_sl")
tp_pct = tp_raw if tp_raw > 0 else None
sl_pct = sl_raw if sl_raw > 0 else None
ind_vente = render_indicator_bloc("sell" if not is_short else "buy", "scan_sell")

st.divider()

# Construction de la stratégie
strategy = {
    "ind_achat": ind_achat,
    "ind_vente": ind_vente,
    "tp_pct":    tp_pct,
    "sl_pct":    sl_pct,
    "is_short":  is_short,
}

# ---------------------------------------------------------------------------
# 3️⃣ Lancement du scan
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
            row = {"Crypto": label, "Direction": "Short 🔴" if is_short else "Long 🟢"}

            for i, d in enumerate(durees):
                dr = date_ranges[i] if mode_duree == "Plages de dates" and i < len(date_ranges) else None
                res = run_backtest_single(
                    df=df, strategy=strategy,
                    capital=capital, frais_pct=frais_pct,
                    duree=d, date_range=dr,
                )
                if dr:
                    col_label = f"{dr[0].strftime('%d/%m/%y')}→{dr[1].strftime('%d/%m/%y')}"
                else:
                    col_label = f"{d}j"

                bnh_label = "S&H" if is_short else "B&H"
                row[f"Rendement {col_label} (%)"]       = res["rendement_pct"]
                row[f"{bnh_label} {col_label} (%)"]     = res["bnh_rendement"]
                row[f"Trades {col_label}"]               = res["nb_trades"]
                row[f"Win rate {col_label} (%)"]         = res["win_rate"]

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
        rend_cols = [c for c in df_res.columns if "Rendement" in c]
        if rend_cols:
            df_res = df_res.sort_values(rend_cols[0], ascending=False)
        st.session_state["scan_results"] = df_res
        st.success(f"✅ Scan terminé — {len(results)} actifs analysés")
    else:
        st.error("❌ Aucun résultat — tous les actifs ont échoué")

# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------
if "scan_results" in st.session_state:
    df_res = st.session_state["scan_results"]

    rend_cols = [c for c in df_res.columns if "Rendement" in c]

    # Tri
    col_sort, col_order, col_clear = st.columns([3, 2, 1])
    with col_sort:
        sort_col = st.selectbox("Trier par", df_res.columns[1:], index=0, key="scan_sort")
    with col_order:
        asc = st.radio("Ordre", ["↓ Décroissant", "↑ Croissant"],
                       horizontal=True, key="scan_asc") == "↑ Croissant"
    with col_clear:
        st.write("")
        if st.button("🗑️ Effacer", key="scan_clear_results"):
            del st.session_state["scan_results"]
            st.rerun()

    df_res = df_res.sort_values(sort_col, ascending=asc)

    def color_val(val):
        if not isinstance(val, (int, float)):
            return ""
        return f"color: {'#22C55E' if val > 0 else '#EF4444' if val < 0 else '#888'}"

    fmt_dict = {}
    for c in df_res.columns:
        if c in ("Crypto", "Direction"):
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
    # Hauteur adaptative selon le nombre de lignes
    height = min(100 + len(df_res) * 35, 800)
    st.dataframe(styled, width='stretch', height=height)

    # Top 5 — suit le tri actuel (uniquement sur colonnes numériques)
    st.subheader(f"🏆 Top 5 — {sort_col}")
    if sort_col in df_res.columns and pd.api.types.is_numeric_dtype(df_res[sort_col]):
        top_df = df_res.nlargest(5, sort_col) if not asc else df_res.nsmallest(5, sort_col)
        for _, row in top_df.iterrows():
            val   = row[sort_col]
            color = "#22C55E" if val > 0 else "#EF4444"
            st.markdown(
                f"**{row['Crypto']}** ({row.get('Direction', '')}) — "
                f"<span style='color:{color}'>{val:+.2f}%</span>",
                unsafe_allow_html=True,
            )
