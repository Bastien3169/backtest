"""
app.py
Application Streamlit de backtest de stratégies crypto.
Lancement : streamlit run app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd

from src.utils.data_loader import get_top100_coins, fetch_ohlcv, fetch_btc_mm
from src.controllers.backtest import run_strategy
from src.controllers.results import build_result_table, build_comparison_table
from src.controllers.charts import (
    chart_price_trades,
    chart_rendement_comparison,
    chart_equity_curves,
    chart_drawdown_comparison,
)
from src.controllers.indicators import MM_PERIODS

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
    st.session_state.btc_mm_cache = {}  # {period: pd.Series}
    with st.spinner("Chargement du top 100 CoinGecko..."):
        try:
            st.session_state.coin_list = get_top100_coins()
        except Exception:
            st.session_state.coin_list = [
                {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"},
                {"id": "ethereum", "symbol": "ETH", "name": "Ethereum"},
            ]

coin_list = st.session_state.coin_list
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
            "Capital global (€)", min_value=1.0, value=1000.0, step=100.0
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
        ["Durées prédéfinies", "Plage de dates"],
        index=0, horizontal=True,
    )

    durees = [7, 30, 90]
    date_range = None

    if mode_duree == "Durées prédéfinies":
        durees_raw = st.text_input(
            "Durées (en nombre de bougies, séparées par des virgules)",
            value="7,30,90",
            help="Ex : 7,30,90 — définit les colonnes des résultats",
        )
        try:
            durees = sorted(set(int(x.strip()) for x in durees_raw.split(",") if x.strip().isdigit()))
        except Exception:
            durees = [7, 30, 90]
    else:
        from datetime import date, timedelta
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            date_debut = st.date_input("Du", value=date.today() - timedelta(days=90))
        with col_d2:
            date_fin = st.date_input("Au", value=date.today())
        if date_debut < date_fin:
            date_range = (date_debut, date_fin)
            delta = (date_fin - date_debut).days
            durees = [delta]
            st.caption(f"→ {delta} jours de backtest")
        else:
            st.error("La date de début doit être avant la date de fin")

    st.divider()

    # Bouton charger les données
    if st.button("🔄 Charger les données marché", use_container_width=True):
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
            st.caption(f"Capital alloué : **{capital_strat:,.2f} €**")
        else:
            capital_strat = st.number_input(
                "Capital (€)",
                min_value=1.0,
                value=strat.get("capital", 1000.0),
                step=100.0,
                key=f"capital_{i}",
            )
            alloc_pct = 100

        st.divider()

        # ── Indicateurs ───────────────────────────────────────────────────
        mm_labels = [1, 10, 20, 50, 100, 200]

        def render_indicator_bloc(side: str, key_prefix: str) -> dict:
            use_rsi        = False
            rsi_period     = 14
            rsi_threshold  = 30.0 if side == "buy" else 70.0
            mm_selected    = []
            mm_period_sel  = None
            mm_condition   = None
            mm_cross_a     = None
            mm_cross_b     = None
            btc_cross_period = None
            use_macd       = False
            use_bollinger  = False
            bollinger_band = None

            col_a, col_b = st.columns(2)

            # ── Colonne gauche : RSI + MM ─────────────────────────────────
            with col_a:
                # RSI
                st.markdown("**📉 RSI**")
                use_rsi = st.checkbox("Activer", key=f"{key_prefix}_rsi")
                if use_rsi:
                    c1, c2 = st.columns(2)
                    with c1:
                        rsi_period = st.number_input("Période", 2, 50, 14, key=f"{key_prefix}_rsi_p")
                    with c2:
                        label = "Achat si <" if side == "buy" else "Vente si >"
                        rsi_threshold = st.number_input(label, 1.0, 99.0,
                                                        30.0 if side == "buy" else 70.0,
                                                        key=f"{key_prefix}_rsi_th")
                st.write("")

                # MM
                st.markdown("**📈 Moyennes Mobiles**")
                mm_cols = st.columns(6)
                for j, p in enumerate(mm_labels):
                    with mm_cols[j]:
                        if st.checkbox(f"{p}", key=f"{key_prefix}_mm_{p}"):
                            mm_selected.append(p)
                if mm_selected:
                    c1, c2 = st.columns(2)
                    with c1:
                        mm_period_sel = st.selectbox("MM de référence",
                                                     options=mm_selected, key=f"{key_prefix}_mm_ref")
                    with c2:
                        mm_condition = st.radio("Condition",
                                                ["above", "below"],
                                                format_func=lambda x: "Au-dessus ↑" if x == "above" else "En-dessous ↓",
                                                key=f"{key_prefix}_mm_cond")

            # ── Colonne droite : Cross MM + BTC + MACD + Bollinger ────────
            with col_b:
                # Croisement MM
                st.markdown("**🔀 Croisement MM**")
                use_cross = st.checkbox(
                    "Golden cross" if side == "buy" else "Death cross",
                    key=f"{key_prefix}_cross"
                )
                if use_cross:
                    c1, c2 = st.columns(2)
                    with c1:
                        mm_cross_a = st.selectbox("Courte (A)", mm_labels, index=2, key=f"{key_prefix}_cross_a")
                    with c2:
                        mm_cross_b = st.selectbox("Longue (B)", mm_labels, index=4, key=f"{key_prefix}_cross_b")
                st.write("")

                # Croisement BTC
                st.markdown("**₿ Croisement vs BTC**")
                use_btc = st.checkbox("Activer", key=f"{key_prefix}_btc")
                if use_btc:
                    btc_cross_period = st.selectbox("Période MM", mm_labels, index=3, key=f"{key_prefix}_btc_p")
                    lbl = f"MM{btc_cross_period} actif > MM{btc_cross_period} BTC" if side == "buy" else f"MM{btc_cross_period} actif < MM{btc_cross_period} BTC"
                    st.caption(lbl)
                st.write("")

                # MACD
                st.markdown("**〰️ MACD**")
                use_macd = st.checkbox(
                    "Haussier" if side == "buy" else "Baissier",
                    key=f"{key_prefix}_macd"
                )
                st.write("")

                # Bollinger
                st.markdown("**📊 Bollinger**")
                use_bollinger = st.checkbox("Activer", key=f"{key_prefix}_boll")
                if use_bollinger:
                    bollinger_band = st.radio("Bande",
                                              ["haute", "basse"],
                                              format_func=lambda x: "Haute 🔴" if x == "haute" else "Basse 🟢",
                                              key=f"{key_prefix}_boll_band",
                                              horizontal=True)

            return {
                "use_rsi":          use_rsi,
                "rsi_period":       rsi_period,
                "rsi_threshold":    rsi_threshold,
                "mm_periods":       mm_selected,
                "mm_period":        mm_period_sel,
                "mm_condition":     mm_condition,
                "mm_cross_a":       mm_cross_a,
                "mm_cross_b":       mm_cross_b,
                "btc_cross_period": btc_cross_period,
                "use_macd":         use_macd,
                "use_bollinger":    use_bollinger,
                "bollinger_band":   bollinger_band,
            }

        st.markdown("#### 🟢 Indicateurs d'achat")
        ind_achat = render_indicator_bloc("buy", f"buy_{i}")

        st.divider()

        # ── Vente des positions — toujours visible ────────────────────────
        st.markdown("#### 🔴 Vente des positions")
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

        ind_vente = render_indicator_bloc("sell", f"sell_{i}")

        # La vente est active si TP, SL ou au moins un indicateur vente est coché
        has_sell = (tp_pct is not None or sl_pct is not None or
                    any([ind_vente.get("use_rsi"), ind_vente.get("mm_period"),
                         ind_vente.get("mm_cross_a"), ind_vente.get("use_macd"),
                         ind_vente.get("use_bollinger"), ind_vente.get("btc_cross_period")]))
        if not has_sell:
            st.caption("ℹ️ Aucun critère de vente → mode **hold** jusqu'à la fin de la période")

        # ── Assemblage config stratégie ───────────────────────────────────
        strategies_config.append({
            "name":      name,
            "capital":   capital_strat,
            "alloc_pct": alloc_pct,
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
        use_container_width=True,
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
    all_results = {}
    all_trades = {}

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
            date_range=date_range if mode_duree == "Plage de dates" else None,
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
        all_trades[strat["name"]] = [
            t for d in durees for t in res.get(d, {}).get("trades", [])
        ]
        progress.progress((idx + 1) / len(strategies_config), text=f"Calculé : {strat['name']}")

    st.session_state.results = {
        "all_results":      all_results,
        "all_trades":       all_trades,
        "durees":           durees,
        "strategies_config": strategies_config,
    }
    progress.empty()
    st.success("✅ Backtest terminé !")

# ---------------------------------------------------------------------------
# RÉSULTATS
# ---------------------------------------------------------------------------
if st.session_state.results:
    r = st.session_state.results
    all_results = r["all_results"]
    all_trades = r["all_trades"]
    durees = r["durees"]

    st.header("📊 Résultats")

    # Tableau par stratégie
    for name, results in all_results.items():
        st.subheader(f"📋 {name}")
        table = build_result_table(results, durees)
        st.dataframe(table.style.format("{:.2f}", na_rep="—"), use_container_width=True)

    st.divider()

    # Tableau comparatif global
    if len(all_results) > 1:
        st.subheader("⚖️ Comparaison globale")
        comp = build_comparison_table(all_results, durees)
        st.dataframe(comp.style.format("{:.2f}", na_rep="—"), use_container_width=True)
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
        for sname, trades in all_trades.items():
            cutoff = df_with_indicators.index[0]
            trades_slice[sname] = [t for t in trades if t["timestamp"] >= cutoff]

        fig_price = chart_price_trades(
            df_with_indicators,
            trades_slice,
            strategies_config=r.get("strategies_config"),
            title=f"Prix {coin_label} + signaux",
        )
        st.plotly_chart(fig_price, use_container_width=True)

    # Rendement comparatif
    fig_rend = chart_rendement_comparison(all_results, durees)
    st.plotly_chart(fig_rend, use_container_width=True)

    # Equity curves
    duree_eq = st.selectbox("Durée pour equity curves", options=durees, index=len(durees) - 1)
    fig_eq = chart_equity_curves(all_results, duree_eq)
    st.plotly_chart(fig_eq, use_container_width=True)

    # Drawdown
    fig_dd = chart_drawdown_comparison(all_results, durees)
    st.plotly_chart(fig_dd, use_container_width=True)
