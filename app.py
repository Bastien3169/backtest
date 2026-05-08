"""
app.py
Application Streamlit de backtest de stratégies crypto.
Lancement : streamlit run app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from datetime import date, timedelta
import pandas as pd

from src.utils.data_loader import get_top100_coins, get_all_assets, fetch_ohlcv, fetch_btc_mm
from src.controllers.backtest import run_strategy
from src.controllers.results import build_result_table, build_comparison_table
from src.controllers.charts import (
    chart_price_trades,
    chart_rendement_comparison,
    chart_equity_curves,
    chart_drawdown_comparison,
)
from src.controllers.indicators import MM_PERIODS
from src.views.indicator_bloc import render_indicator_bloc

# ---------------------------------------------------------------------------
# Config page
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="BacktestBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📈 BacktestBot — Comparateur de stratégies crypto")

# ---------------------------------------------------------------------------
# Session state : liste des stratégies
# ---------------------------------------------------------------------------
if "strategies" not in st.session_state:
    st.session_state.strategies = [{"name": "Stratégie 1"}]

if "results" not in st.session_state:
    st.session_state.results = None

if "df_ohlcv" not in st.session_state:
    st.session_state.df_ohlcv = None

if "btc_mm_cache" not in st.session_state:
    st.session_state.btc_mm_cache = {}

# coin_list : cryptos + indices, relue dynamiquement depuis coins.py à chaque run
coin_list = get_all_assets()
coin_options = {f"{c['symbol']} — {c['name']}": c["id"] for c in coin_list}

# ---------------------------------------------------------------------------
# SIDEBAR — Paramètres globaux
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Paramètres globaux")

    # Mode de simulation
    mode_capital = st.radio(
        "Mode de simulation",
        ["Capital partagé", "Capital indépendant par stratégie"],
        index=0,
    )

    # Capital
    if mode_capital == "Capital partagé":
        capital_global = st.number_input(
            "Capital global ($)", min_value=1.0, value=1000.0, step=100.0
        )
    else:
        capital_global = None

    st.divider()

    # Frais
    frais_pct = st.number_input(
        "Frais par transaction (%)",
        min_value=0.0,
        max_value=10.0,
        value=0.1,
        step=0.01,
        format="%.2f",
    )

    st.divider()

    # Paramètres marché
    st.subheader("📊 Paramètres marché")

    coin_label = st.selectbox("Paire crypto", list(coin_options.keys()), index=0)
    coin_id = coin_options[coin_label]

    timeframe = st.selectbox(
        "Temporalité",
        ["jour", "heure", "semaine", "mois"],
        index=0,
    )

    mode_duree = st.radio(
        "Mode de période",
        ["Durées prédéfinies", "Plages de dates"],
        index=0, horizontal=True,
    )

    durees      = [180, 360, 720]
    date_ranges = []   # liste de (date_debut, date_fin, label)

    if mode_duree == "Durées prédéfinies":
        durees_raw = st.text_input(
            "Durées (en nombre de bougies, séparées par des virgules)",
            value="180,360,720",
            help="Ex : 180,360,720 — définit les colonnes des résultats",
        )
        try:
            durees = sorted(set(int(x.strip()) for x in durees_raw.split(",") if x.strip().isdigit()))
        except Exception:
            durees = [180, 360, 720]
    else:
        if "date_ranges" not in st.session_state:
            st.session_state.date_ranges = [
                (date.today() - timedelta(days=360), date.today())
            ]

        # Ajouter / supprimer des plages
        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button("➕ Ajouter une plage", width='stretch'):
                st.session_state.date_ranges.append(
                    (date.today() - timedelta(days=90), date.today())
                )
                st.rerun()
        with col_clear:
            if st.button("🗑️ Tout effacer", width='stretch'):
                st.session_state.date_ranges = [
                    (date.today() - timedelta(days=360), date.today())
                ]
                st.rerun()

        # Afficher chaque plage
        new_ranges = []
        for idx_r, (d1, d2) in enumerate(st.session_state.date_ranges):
            st.markdown(f"**Plage {idx_r + 1}**")
            r1, r2, r3 = st.columns([2, 2, 1])
            with r1:
                nd1 = st.date_input(f"Du", value=d1, key=f"dr_d1_{idx_r}")
            with r2:
                nd2 = st.date_input(f"Au", value=d2, key=f"dr_d2_{idx_r}")
            with r3:
                st.write("")
                if st.button("✕", key=f"dr_del_{idx_r}") and len(st.session_state.date_ranges) > 1:
                    st.session_state.date_ranges.pop(idx_r)
                    st.rerun()
            if nd1 < nd2:
                new_ranges.append((nd1, nd2))
                delta = (nd2 - nd1).days
                st.caption(f"→ {delta} jours")
            else:
                st.error(f"Plage {idx_r + 1} : date début doit être avant date fin")

        st.session_state.date_ranges = new_ranges
        date_ranges = new_ranges
        # durees = une entrée par plage (utilisé pour les colonnes du tableau)
        durees = [max(1, (d2 - d1).days) for d1, d2 in date_ranges]

    st.divider()

    # Bouton charger les données
    if st.button("🔄 Charger les données marché", width='stretch'):
        with st.spinner(f"Récupération OHLCV {coin_label}..."):
            try:
                df = fetch_ohlcv(coin_id, timeframe, max(durees) if durees else 365)
                st.session_state.df_ohlcv = df
                st.success(f"✅ {len(df)} bougies chargées")
            except Exception as e:
                st.error(f"Erreur : {e}")

# ---------------------------------------------------------------------------
# GESTION DES STRATÉGIES
# ---------------------------------------------------------------------------
st.header("🎯 Stratégies")

col_add, col_info = st.columns([2, 5])
with col_add:
    if st.button("➕ Ajouter une stratégie"):
        n = len(st.session_state.strategies) + 1
        st.session_state.strategies.append({"name": f"Stratégie {n}"})
        st.rerun()

with col_info:
    if mode_capital == "Capital partagé":
        st.info("Mode capital partagé : vérifiez que la somme des allocations ≤ 100%")

# ---------------------------------------------------------------------------
# Rendu de chaque bloc stratégie
# ---------------------------------------------------------------------------
strategies_config = []
total_alloc = 0.0

for i, strat in enumerate(st.session_state.strategies):
    with st.expander(f"📋 {strat['name']}", expanded=True):

        col_name, col_del = st.columns([4, 1])
        with col_name:
            name = st.text_input(
                "Nom de la stratégie",
                value=strat.get("name", f"Stratégie {i+1}"),
                key=f"name_{i}",
            )
        with col_del:
            st.write("")
            st.write("")
            if st.button("🗑️ Supprimer", key=f"del_{i}"):
                st.session_state.strategies.pop(i)
                st.rerun()

        # ── Mode Long / Short ─────────────────────────────────────────────
        is_short = st.radio(
            "Direction",
            ["🟢 Long", "🔴 Short"],
            horizontal=True,
            key=f"direction_{i}",
        ) == "🔴 Short"

        if is_short:
            st.info("🔴 **Mode Short** — tu vends à découvert en espérant racheter moins cher. "
                    "Le signal d'entrée déclenche la vente, le signal de sortie le rachat. "
                    "Le B&H affiché est un S&H (Short & Hold).")

        # ── Capital / Allocation ──────────────────────────────────────────
        if mode_capital == "Capital partagé":
            alloc_pct = st.slider(
                "% du capital alloué",
                min_value=1,
                max_value=100,
                value=strat.get("alloc_pct", 100),
                step=1,
                key=f"alloc_{i}",
            )
            total_alloc += alloc_pct
            capital_strat = capital_global * alloc_pct / 100
            st.caption(f"Capital alloué : **{capital_strat:,.2f} $**")
        else:
            capital_strat = st.number_input(
                "Capital ($)",
                min_value=1.0,
                value=strat.get("capital", 1000.0),
                step=100.0,
                key=f"capital_{i}",
            )
            alloc_pct = 100

        st.divider()

        # ── Indicateurs ───────────────────────────────────────────────────
        label_entry = "🟢 Indicateurs d'achat" if not is_short else "🔴 Indicateurs d'entrée short (vente à découvert)"
        label_exit  = "🔴 Indicateurs de vente" if not is_short else "🟢 Indicateurs de sortie short (rachat)"

        st.markdown(f"#### {label_entry}")
        ind_achat = render_indicator_bloc("buy" if not is_short else "sell", f"buy_{i}")

        st.divider()

        st.markdown(f"#### {label_exit}")
        st.caption("Vente déclenchée si **TP/SL atteint OU indicateur de vente actif** — laisser vide = mode hold")

        cv1, cv2 = st.columns(2)
        with cv1:
            tp_pct = st.number_input("Take Profit (%)", 0.0, 1000.0, 0.0, 0.5, key=f"tp_{i}",
                                     help="0 = désactivé")
        with cv2:
            sl_pct = st.number_input("Stop Loss (%)", 0.0, 100.0, 0.0, 0.5, key=f"sl_{i}",
                                     help="0 = désactivé")

        tp_pct = tp_pct if tp_pct > 0 else None
        sl_pct = sl_pct if sl_pct > 0 else None

        ind_vente = render_indicator_bloc("sell" if not is_short else "buy", f"sell_{i}")

        has_sell = (tp_pct is not None or sl_pct is not None or
                    any([ind_vente.get("use_rsi"), ind_vente.get("mm_period"),
                         ind_vente.get("mm_cross_a"), ind_vente.get("use_macd"),
                         ind_vente.get("use_bollinger"), ind_vente.get("btc_cross_period"),
                         ind_vente.get("mm_align_periods")]))
        if not has_sell:
            label_hold = "mode **hold** jusqu'à la fin" if not is_short else "**short ouvert** jusqu'à la fin"
            st.caption(f"ℹ️ Aucun critère de sortie → {label_hold} de la période")

        strategies_config.append({
            "name":      name,
            "capital":   capital_strat,
            "alloc_pct": alloc_pct,
            "is_short":  is_short,
            "ind_achat": ind_achat,
            "ind_vente": ind_vente,
            "tp_pct":    tp_pct,
            "sl_pct":    sl_pct,
        })

# Avertissement allocation
if mode_capital == "Capital partagé" and total_alloc > 100:
    st.error(f"⚠️ La somme des allocations est de **{total_alloc:.0f}%** — elle dépasse 100% !")

# ---------------------------------------------------------------------------
# BOUTON CALCULER
# ---------------------------------------------------------------------------
st.divider()

col_btn, col_status = st.columns([2, 5])
with col_btn:
    run_disabled = (
        st.session_state.df_ohlcv is None
        or (mode_capital == "Capital partagé" and total_alloc > 100)
    )
    run_clicked = st.button(
        "▶️ Calculer",
        width='stretch',
        disabled=run_disabled,
        type="primary",
    )

with col_status:
    if st.session_state.df_ohlcv is None:
        st.warning("Chargez d'abord les données marché (sidebar).")

# Toggle debug dans la sidebar
with st.sidebar:
    st.divider()
    show_debug = st.radio("Mode debug", ["Masqué", "Visible"], index=0, horizontal=True) == "Visible"

if run_clicked:
    all_results      = {}
    all_trades       = {}
    all_results_meta = {}  # {name: {"is_short": bool}}

    # ── DEBUG ──────────────────────────────────────────────────────────────
    if show_debug:
        st.subheader("🔍 Debug")
        df_ohlcv = st.session_state.df_ohlcv
        st.write(f"**df_ohlcv** : `{type(df_ohlcv)}` — shape : `{df_ohlcv.shape if df_ohlcv is not None else 'None'}`")
        if df_ohlcv is not None and not df_ohlcv.empty:
            st.write(f"Index : `{df_ohlcv.index[0]}` → `{df_ohlcv.index[-1]}`")
            st.dataframe(df_ohlcv.tail(5))
        else:
            st.error("❌ df_ohlcv est vide ou None — le chargement des données a échoué")
        st.write(f"**Durées** : `{durees}`")
        st.write(f"**Nb stratégies** : `{len(strategies_config)}`")
        for s in strategies_config:
            st.write(f"- `{s['name']}` | capital={s['capital']} | achat={s['ind_achat']} | vente={s['ind_vente']}")
    # ── FIN DEBUG ──────────────────────────────────────────────────────────

    progress = st.progress(0, text="Calcul en cours...")

    # Pré-chargement des MM BTC nécessaires (achat ET vente)
    btc_periods_needed = set()
    for s in strategies_config:
        if s.get("ind_achat", {}).get("btc_cross_period"):
            btc_periods_needed.add(s["ind_achat"]["btc_cross_period"])
        if s.get("ind_vente", {}).get("btc_cross_period"):
            btc_periods_needed.add(s["ind_vente"]["btc_cross_period"])
    for p in btc_periods_needed:
        if p not in st.session_state.btc_mm_cache:
            with st.spinner(f"Chargement MM{p} BTC..."):
                try:
                    st.session_state.btc_mm_cache[p] = fetch_btc_mm(
                        timeframe, p, max(durees) if durees else 365
                    )
                except Exception as e:
                    st.warning(f"Impossible de charger MM BTC : {e}")

    for idx, strat in enumerate(strategies_config):
        # Injection MM BTC dans ind_achat et ind_vente
        for side_key in ("ind_achat", "ind_vente"):
            cfg = strat.get(side_key, {})
            p = cfg.get("btc_cross_period")
            cfg["btc_mm"] = st.session_state.btc_mm_cache.get(p) if p else None

        res = run_strategy(
            df=st.session_state.df_ohlcv,
            strategy=strat,
            capital=strat["capital"],
            frais_pct=frais_pct,
            durees=durees,
            date_range=date_ranges if mode_duree == "Plages de dates" else None,
        )

        # ── DEBUG résultats ────────────────────────────────────────────────
        if show_debug:
            st.write(f"**Résultats bruts `{strat['name']}`** :")
            for d, r in res.items():
                nb_trades = len(r.get("trades", []))
                eq = r.get("equity_curve", None)
                st.write(f"  durée={d}j → plus_value={r.get('plus_value_eur')}€ | rendement={r.get('rendement_pct')}% | trades={nb_trades} | equity_len={len(eq) if eq is not None else 0}")
        # ── FIN DEBUG ──────────────────────────────────────────────────────

        all_results[strat["name"]] = res
        all_results_meta[strat["name"]] = {"is_short": strat.get("is_short", False)}
        all_trades[strat["name"]] = [
            t for d in durees for t in res.get(d, {}).get("trades", [])
        ]
        progress.progress((idx + 1) / len(strategies_config), text=f"Calculé : {strat['name']}")

    st.session_state.results = {
        "all_results":       all_results,
        "all_results_meta":  all_results_meta,
        "all_trades":        all_trades,
        "durees":            durees,
        "strategies_config": strategies_config,
        "date_ranges":       date_ranges if mode_duree == "Plages de dates" else None,
    }
    progress.empty()
    st.success("✅ Backtest terminé !")

# ---------------------------------------------------------------------------
# RÉSULTATS
# ---------------------------------------------------------------------------
if st.session_state.results:
    r = st.session_state.results
    all_results      = r["all_results"]
    all_results_meta = r.get("all_results_meta", {})
    all_trades       = r["all_trades"]
    durees = r["durees"]

    st.header("📊 Résultats")

    # Tableau par stratégie
    for name, results in all_results.items():
        st.subheader(f"📋 {name}")
        table = build_result_table(
            results, durees,
            date_ranges=r.get("date_ranges"),
            is_short=all_results_meta.get(name, {}).get("is_short", False),
        )

        def color_rendement(val):
            try:
                v = float(val)
                if v > 0:
                    return "color: #22C55E; font-weight: bold"
                elif v < 0:
                    return "color: #EF4444; font-weight: bold"
            except (TypeError, ValueError):
                pass
            return ""

        rend_rows = ["Rendement strat (%)"]
        for lbl in ["Rendement B&H (%)", "Rendement S&H (%)"]:
            if lbl in table.index:
                rend_rows.append(lbl)

        styled = (
            table.style
            .format("{:.2f}", na_rep="—")
            .map(color_rendement, subset=pd.IndexSlice[rend_rows, :])
        )
        st.dataframe(styled, width='stretch')

    st.divider()

    # Tableau comparatif global
    if len(all_results) > 1:
        st.subheader("⚖️ Comparaison globale")
        comp = build_comparison_table(all_results, durees)

        def color_comp(val):
            try:
                v = float(val)
                if v > 0:   return "color: #22C55E; font-weight: bold"
                elif v < 0: return "color: #EF4444; font-weight: bold"
            except (TypeError, ValueError):
                pass
            return ""

        rend_comp_cols = [c for c in comp.columns if "Rendement" in c or "B&H" in c or "S&H" in c]
        styled_comp = (
            comp.style
            .format("{:.2f}", na_rep="—")
            .map(color_comp, subset=rend_comp_cols)
        )
        st.dataframe(styled_comp, width='stretch')
        st.divider()

    # ── Graphiques ────────────────────────────────────────────────────────
    st.header("📈 Graphiques")

    # Graphique principal prix + trades
    if st.session_state.df_ohlcv is not None:
        duree_chart = st.selectbox(
            "Durée affichée sur le graphique principal",
            options=durees,
            index=len(durees) - 1,
        ) if len(durees) > 1 else durees[0]
        # Récupérer le df_slice enrichi (avec colonnes indicateurs) depuis les résultats
        # On prend la durée sélectionnée de la première stratégie
        first_strat = list(all_results.keys())[0]
        df_with_indicators = all_results[first_strat].get(duree_chart, {}).get("df_slice", st.session_state.df_ohlcv.iloc[-duree_chart:])
        if df_with_indicators.empty:
            df_with_indicators = st.session_state.df_ohlcv.iloc[-duree_chart:]

        trades_slice = {}
        for sname, strat_results in all_results.items():
            trades_for_duration = strat_results.get(duree_chart, {}).get("trades", [])
            if df_with_indicators.index.empty:
                trades_slice[sname] = []
            else:
                cutoff = df_with_indicators.index[0]
                trades_slice[sname] = [t for t in trades_for_duration if t["timestamp"] >= cutoff]

        fig_price = chart_price_trades(
            df_with_indicators,
            trades_slice,
            strategies_config=r.get("strategies_config"),
            title=f"Prix {coin_label} (USD) + signaux",
        )
        st.plotly_chart(fig_price, width='stretch')

    # Rendement comparatif
    fig_rend = chart_rendement_comparison(all_results, durees)
    st.plotly_chart(fig_rend, width='stretch')

    # Equity curves
    duree_eq = st.selectbox("Durée pour equity curves", options=durees, index=len(durees) - 1)
    fig_eq = chart_equity_curves(all_results, duree_eq)
    st.plotly_chart(fig_eq, width='stretch')

    # Drawdown
    fig_dd = chart_drawdown_comparison(all_results, durees)
    st.plotly_chart(fig_dd, width='stretch')
