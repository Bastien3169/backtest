"""
pages/0_📈_Backtest.py
Comparateur de stratégies crypto (anciennement app.py, contenu inchangé).
app.py est désormais le routeur : authentification + liste des pages.
"""

import sys
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from src.utils.data_loader import fetch_ohlcv, fetch_btc_mm
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
from src.views import composants as C
from src.views.conditions_bloc import render_conditions_marche
from src.controllers.backtest import run_backtest_single
from src.utils import bilan as BL
from src.utils import conditions_marche as CM

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
st.caption(
    "Construis une ou plusieurs stratégies : indicateurs techniques (RSI, moyennes mobiles, "
    "MACD, Bollinger) et, si tu veux, conditions de marché (régime du BTC, open interest, "
    "compression). Teste-les sur une paire (avec graphiques), plusieurs, ou toutes. "
    "Pour régler TP et SL, va en Optimisation."
)

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


# ---------------------------------------------------------------------------
# SIDEBAR — Paramètres globaux
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Paramètres")

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

    frais_pct = C.frais("bt_")
    st.divider()
    _actifs, timeframe = C.paires("bt_")
    # Une seule paire : la page historique (données chargées, graphiques).
    # Plusieurs ou toutes : chaque paire est chargée au moment du calcul.
    une_paire = len(_actifs) == 1
    coin_id = _actifs[0]["id"] if une_paire else None
    coin_label = f"{_actifs[0]['symbol']} — {_actifs[0]['name']}" if une_paire else f"{len(_actifs)} paires"
    st.divider()
    _mode, _periodes = C.periodes("bt_")
    mode_duree = "Plages de dates" if _mode == "plages" else "Durées prédéfinies"
    durees = [p["bougies"] for p in _periodes] or [180, 360, 720]
    date_ranges = [p["plage"] for p in _periodes if p["plage"]]

    st.divider()

    if not une_paire:
        st.caption("Plusieurs paires : chacune est chargée au moment du calcul.")
    else:
        # Bouton charger les données
        if st.button("🔄 Charger les données marché", width='stretch'):
            with st.spinner(f"Récupération OHLCV {coin_label}..."):
                try:
                    df = fetch_ohlcv(coin_id, timeframe, max(durees) if durees else 365)
                    st.session_state.df_ohlcv = df
                    st.success(f"✅ {len(df)} bougies chargées")
                except Exception as e:
                    st.error(f"Erreur : {e}")

        # ── Export CSV des bougies chargées ──────────────────────────────────
        if st.session_state.df_ohlcv is not None and not st.session_state.df_ohlcv.empty:
            _df_export = st.session_state.df_ohlcv.copy()
            _df_export.index.name = "date"

            # On garde l'OHLC en priorité : high et low sont indispensables pour
            # rejouer les TP/SL intra-bougie hors de l'app.
            _cols = [c for c in ["open", "high", "low", "close", "volume"]
                     if c in _df_export.columns]
            _csv = _df_export[_cols].to_csv().encode("utf-8")

            _debut = str(_df_export.index[0])[:10]
            _fin   = str(_df_export.index[-1])[:10]

            st.download_button(
                "⬇️ Télécharger les bougies (CSV)",
                data=_csv,
                file_name=f"bougies_{coin_id}_{timeframe}_{_debut}_{_fin}.csv",
                mime="text/csv",
                width='stretch',
                help="Export OHLCV brut — réutilisable pour une analyse externe",
            )
            st.caption(
                f"{len(_df_export)} bougies · {_debut} → {_fin}  \n"
                f"Colonnes : {', '.join(_cols)}"
            )

# ---------------------------------------------------------------------------
# GESTION DES STRATÉGIES
# ---------------------------------------------------------------------------
st.header("🎯 Stratégies")
st.caption("Chaque stratégie : une entrée (analyse technique et/ou de marché) et une sortie.")

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

        # ── Réglages : direction et capital, côte à côte ──────────────────
        c_dir, c_cap = st.columns(2)
        with c_dir:
            is_short = st.radio(
                "Direction",
                ["🟢 Long", "🔴 Short"],
                horizontal=True,
                key=f"direction_{i}",
            ) == "🔴 Short"
        with c_cap:
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

        if is_short:
            st.info("🔴 **Mode Short** — tu vends à découvert en espérant racheter moins cher. "
                    "Le signal d'entrée déclenche la vente, le signal de sortie le rachat. "
                    "Le B&H affiché est un S&H (Short & Hold).")

        label_entry = "🟢 Indicateurs d'achat" if not is_short else "🔴 Indicateurs d'entrée short (vente à découvert)"
        label_exit  = "🔴 Indicateurs de vente" if not is_short else "🟢 Indicateurs de sortie short (rachat)"

        def _titre_section(texte):
            st.markdown(f"<h4 style='margin:1rem 0 0.4rem 0'>{texte}</h4>", unsafe_allow_html=True)

        def _liaison(mot):
            st.markdown(f"<p style='text-align:center; margin:0.2rem 0'>➕ <b>{mot}</b></p>",
                        unsafe_allow_html=True)

        # ══ ENTRÉE ═════════════════════════════════════════════════════════
        _titre_section("🟢 ENTRÉE")
        with st.container(border=True):
            st.markdown("##### 📈 1 · Par analyse technique")
            st.caption(label_entry)
            ind_achat = render_indicator_bloc("buy" if not is_short else "sell", f"buy_{i}")
        _liaison("ET")
        with st.container(border=True):
            st.markdown("##### 🧭 2 · Par analyse de marché (facultatif)")
            st.caption("Régime du BTC, compression, open interest, tendance longue. Vide = aucun "
                       "filtre ; sans indicateur au-dessus, ces conditions suffisent à entrer.")
            conditions = render_conditions_marche(f"cm{i}_", timeframe)

        st.divider()

        # ══ SORTIE ═════════════════════════════════════════════════════════
        _titre_section("🔴 SORTIE")
        st.caption("La première sortie atteinte ferme la position. Tout laisser vide = mode hold.")
        with st.container(border=True):
            st.markdown("##### 🚪 1 · Par analyse technique")
            st.caption(label_exit)
            ind_vente = render_indicator_bloc("sell" if not is_short else "buy", f"sell_{i}")
        _liaison("OU")
        with st.container(border=True):
            st.markdown("##### 🚪 2 · Par Take Profit / Stop Loss")
            cv1, cv2 = st.columns(2)
            with cv1:
                tp_pct = st.number_input("Take Profit (%)", 0.0, 1000.0, 0.0, 0.5, key=f"tp_{i}",
                                         help="0 = désactivé")
            with cv2:
                sl_pct = st.number_input("Stop Loss (%)", 0.0, 100.0, 0.0, 0.5, key=f"sl_{i}",
                                         help="0 = désactivé")
            tp_pct = tp_pct if tp_pct > 0 else None
            sl_pct = sl_pct if sl_pct > 0 else None

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
            "conditions": conditions,
        })

# Avertissement allocation
if mode_capital == "Capital partagé" and total_alloc > 100:
    st.error(f"⚠️ La somme des allocations est de **{total_alloc:.0f}%** — elle dépasse 100% !")

# ---------------------------------------------------------------------------
# BOUTON CALCULER
# ---------------------------------------------------------------------------
st.divider()
st.header("▶️ Calcul")

col_btn, col_status = st.columns([2, 5])
with col_btn:
    run_disabled = (
        (une_paire and st.session_state.df_ohlcv is None)
        or (mode_capital == "Capital partagé" and total_alloc > 100)
        or any(CM.invalides(s["conditions"], timeframe) for s in strategies_config)
    )
    run_clicked = st.button(
        "▶️ Calculer",
        width='stretch',
        disabled=run_disabled,
        type="primary",
    )

with col_status:
    if une_paire and st.session_state.df_ohlcv is None:
        st.warning("Chargez d'abord les données marché (sidebar).")
    elif not une_paire:
        st.caption(f"{len(_actifs)} paires × {len(strategies_config)} stratégie(s) : chaque paire est "
                   "chargée une par une, compte plusieurs minutes sur « Toutes ».")

# Toggle debug dans la sidebar
with st.sidebar:
    st.divider()
    show_debug = st.radio("Mode debug", ["Masqué", "Visible"], index=0, horizontal=True) == "Visible"

def _precharger_btc_mm(strategies_config, timeframe, durees):
    """Pré-chargement des MM BTC nécessaires (achat ET vente), injectées dans chaque bloc."""
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
    for strat in strategies_config:
        for side_key in ("ind_achat", "ind_vente"):
            cfg = strat.get(side_key, {})
            p = cfg.get("btc_cross_period")
            cfg["btc_mm"] = st.session_state.btc_mm_cache.get(p) if p else None


if run_clicked and une_paire:
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

    _precharger_btc_mm(strategies_config, timeframe, durees)

    for idx, strat in enumerate(strategies_config):
        # Conditions de marché : filtre d'entrée ajouté à la stratégie (absent = inchangé)
        strat_calc = strat
        if strat["conditions"]:
            ctx = CM.contexte(strat["conditions"], timeframe)
            strat_calc = {**strat, "filtre_marche": CM.filtre(
                st.session_state.df_ohlcv, strat["conditions"], ctx, _actifs[0]["symbol"])}

        res = run_strategy(
            df=st.session_state.df_ohlcv,
            strategy=strat_calc,
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
        "mode":              "une",
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
# CALCUL — plusieurs paires (ou toutes)
# ---------------------------------------------------------------------------
# Même moteur, mêmes stratégies, mêmes périodes que pour une paire : on boucle sur
# les paires. Une stratégie avec conditions de marché est aussi calculée SANS elles,
# pour mesurer ce qu'elles apportent.
if run_clicked and not une_paire:
    _precharger_btc_mm(strategies_config, timeframe, durees)
    contextes = {s["name"]: CM.contexte(s["conditions"], timeframe) for s in strategies_config
                 if s["conditions"]}
    lignes = {s["name"]: [] for s in strategies_config}
    gains = {s["name"]: {p["nom"]: {"avec": [], "sans": []} for p in _periodes} for s in strategies_config}
    erreurs = []
    progress = st.progress(0.0, text="Calcul en cours...")
    for n, actif in enumerate(_actifs):
        label = f"{actif['symbol']} — {actif['name']}"
        progress.progress((n + 1) / len(_actifs), text=f"{label} ({n + 1}/{len(_actifs)})")
        try:
            df = fetch_ohlcv(actif["id"], timeframe, max(durees) if durees else 365)
        except Exception as e:
            erreurs.append(f"{label} : {e}")
            continue
        for strat in strategies_config:
            avec = sans = strat
            if strat["conditions"]:
                ctx = contextes[strat["name"]]
                # « Sans conditions » à armes égales : même période (limitée au début de
                # l'historique d'OI quand une condition OI est utilisée)
                depuis = CM.debut_oi(ctx) if CM.utilise_oi(strat["conditions"]) else None
                periode_ok = pd.Series(df.index >= depuis if depuis is not None else True, index=df.index)
                avec = {**strat, "filtre_marche": CM.filtre(df, strat["conditions"], ctx, actif["symbol"]) & periode_ok}
                sans = {**strat, "filtre_marche": periode_ok}
            ligne = {"Crypto": label}
            for p in _periodes:
                kw = dict(df=df, capital=strat["capital"], frais_pct=frais_pct,
                          duree=p["bougies"], date_range=p["plage"])
                res = run_backtest_single(strategy=avec, **kw)
                ligne[f"Rendement {p['nom']} (%)"] = res["rendement_pct"]
                ligne[f"{'S&H' if strat['is_short'] else 'B&H'} {p['nom']} (%)"] = res["bnh_rendement"]
                ligne[f"Trades {p['nom']}"] = res["nb_trades"]
                ligne[f"Win rate {p['nom']} (%)"] = res["win_rate"]
                if strat["conditions"]:
                    res_sans = run_backtest_single(strategy=sans, **kw)
                    ligne[f"Sans conditions {p['nom']} (%)"] = res_sans["rendement_pct"]
                    g = gains[strat["name"]][p["nom"]]
                    g["avec"] += [t["gain_pct"] for t in res["trades"] if "gain_pct" in t]
                    g["sans"] += [t["gain_pct"] for t in res_sans["trades"] if "gain_pct" in t]
            lignes[strat["name"]].append(ligne)
    progress.empty()
    st.session_state.results = {
        "mode": "multi",
        "lignes": {k: pd.DataFrame(v) for k, v in lignes.items()},
        "gains": gains,
        "periodes": [p["nom"] for p in _periodes],
        "strategies_config": strategies_config,
        "erreurs": erreurs,
    }
    st.success(f"✅ Backtest terminé — {len(_actifs) - len(erreurs)} paires")

# ---------------------------------------------------------------------------
# RÉSULTATS
# ---------------------------------------------------------------------------
if st.session_state.results and st.session_state.results.get("mode", "une") == "une":
    r = st.session_state.results
    all_results      = r["all_results"]
    all_results_meta = r.get("all_results_meta", {})
    all_trades       = r["all_trades"]
    durees = r["durees"]

    st.divider()
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


# ---------------------------------------------------------------------------
# RÉSULTATS — plusieurs paires
# ---------------------------------------------------------------------------
if st.session_state.results and st.session_state.results.get("mode") == "multi":
    r = st.session_state.results
    noms_periodes = r["periodes"]
    st.divider()
    st.header(f"📊 Résultats — {max(len(d) for d in r['lignes'].values()) if r['lignes'] else 0} paires")
    if r["erreurs"]:
        with st.expander(f"⚠️ {len(r['erreurs'])} paire(s) non chargée(s)"):
            st.write("\n".join(f"- {e}" for e in r["erreurs"]))

    for strat in r["strategies_config"]:
        nom, df_l = strat["name"], r["lignes"].get(strat["name"])
        if df_l is None or df_l.empty:
            continue
        st.subheader(f"📋 {nom}")
        hold = "S&H" if strat["is_short"] else "B&H"

        # ── Synthèse : moyenne sur les paires, une ligne par période ─────
        synthese, couples = [], []
        for p in noms_periodes:
            rend = df_l[f"Rendement {p} (%)"]
            ligne = {"Période": p, "Rendement moyen (%)": rend.mean(),
                     f"{hold} moyen (%)": df_l[f"{hold} {p} (%)"].mean(),
                     "Paires gagnantes": f"{int((rend > 0).sum())} / {len(df_l)}",
                     "Win rate moyen (%)": df_l[f"Win rate {p} (%)"].mean(),
                     "Trades": int(df_l[f"Trades {p}"].sum())}
            if strat["conditions"]:
                sans = df_l[f"Sans conditions {p} (%)"]
                ligne["Sans conditions (%)"] = sans.mean()
                ligne["Paires améliorées"] = f"{int((rend > sans).sum())} / {len(df_l)}"
                g = r["gains"][nom][p]
                couples.append((BL.stats_gains(g["avec"]), BL.stats_gains(g["sans"])))
            synthese.append(ligne)
        if strat["conditions"]:
            v = BL.verdict(couples, CM.utilise_oi(strat["conditions"]))
            (st.success if v.startswith("✅") else st.error if v.startswith("❌") else st.warning)(
                f"**Conditions de marché ({CM.decrire(strat['conditions'])}) : {v}**")
        cols_pct = [c for c in synthese[0] if c.endswith("(%)") and "Win rate" not in c]
        st.dataframe(C.tableau(pd.DataFrame(synthese), cols_pct,
                               formats={**{c: "{:+.2f}" for c in cols_pct}, "Win rate moyen (%)": "{:.0f}"}),
                     hide_index=True, width="stretch")

        # ── Détail par paire ────────────────────────────────────────────
        with st.expander("🔎 Détail par paire"):
            rend_cols = [c for c in df_l.columns if c.startswith(("Rendement", "Sans conditions"))]
            fmt = {c: ("{:.0f}" if c.startswith("Trades") else "{:+.2f}") for c in df_l.columns if c != "Crypto"}
            st.dataframe(C.tableau(df_l.sort_values(rend_cols[0], ascending=False), rend_cols, formats=fmt),
                         hide_index=True, width="stretch")
        st.divider()

    # ── Comparaison entre stratégies ────────────────────────────────────────
    if len(r["lignes"]) > 1:
        st.subheader("⚖️ Comparaison globale")
        comp = pd.DataFrame([{"Stratégie": nom, **{f"Rendement moyen {p} (%)": d[f"Rendement {p} (%)"].mean()
                                                   for p in noms_periodes}}
                             for nom, d in r["lignes"].items() if not d.empty])
        cols = [c for c in comp.columns if c != "Stratégie"]
        st.dataframe(C.tableau(comp, cols, formats={c: "{:+.2f}" for c in cols}), hide_index=True, width="stretch")

    st.caption("📈 Les graphiques (prix et signaux, equity, drawdown) s'affichent quand une seule "
               "paire est sélectionnée.")
