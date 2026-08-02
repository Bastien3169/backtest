"""
pages/4_🔥_Optimisation.py
Optimisation par grille : teste toutes les combinaisons TP x SL sur PLUSIEURS
périodes à la fois, et identifie les réglages robustes.

Principe :
- Tu définis un range de TP (min, max, pas) et un range de SL (min, max, pas)
- Tu choisis des durées (180/360/720/1080 bougies) OU des plages (Bull/Range/Bear)
- Chaque combinaison TP/SL est backtestée sur CHAQUE période
- Un onglet "Robustesse" croise les périodes : une combinaison qui tient partout
  vaut mieux qu'une combinaison excellente sur une seule période (sur-ajustement)

Note perf : les indicateurs et signaux ne dépendent ni du TP/SL ni de la période.
Ils sont donc calculés UNE SEULE FOIS via precompute() et réutilisés partout.
"""

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date

from src.utils.data_loader import get_all_assets, fetch_ohlcv, fetch_btc_mm
from src.controllers.backtest import run_backtest_single, precompute
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Optimisation TP/SL", page_icon="🔥", layout="wide")

st.title("🔥 Optimisation — Grille TP × SL")
st.caption(
    "Teste toutes les combinaisons TP/SL sur plusieurs périodes d'un coup. "
    "La stratégie d'indicateurs reste identique — seuls TP et SL varient."
)

# Plages par défaut — identiques à celles de app.py
PLAGES_DEFAUT = [
    ("Bull",  date(2024, 10, 1), date(2025, 10, 1)),
    ("Range", date(2024, 4, 15), date(2024, 9, 30)),
    ("Bear",  date(2025, 10, 1), date(2026, 6, 3)),
]
DUREES_DEFAUT = "180,360,720,1080"

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "opti_df_ohlcv" not in st.session_state:
    st.session_state.opti_df_ohlcv = None
if "opti_results" not in st.session_state:
    st.session_state.opti_results = None
if "opti_periodes" not in st.session_state:
    st.session_state.opti_periodes = []

# ---------------------------------------------------------------------------
# SIDEBAR — Marché, capital, périodes
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Paramètres")

    capital = st.number_input("Capital ($)", min_value=1.0, value=1000.0, step=100.0)
    frais_pct = st.number_input(
        "Frais par transaction (%)", min_value=0.0, max_value=10.0,
        value=0.1, step=0.01, format="%.2f",
    )

    st.divider()
    st.subheader("📊 Marché")

    _assets = get_all_assets()
    coin_options = {f"{c['symbol']} — {c['name']}": c["id"] for c in _assets}
    coin_label = st.selectbox("Paire", list(coin_options.keys()), index=0)
    coin_id = coin_options[coin_label]

    timeframe = st.selectbox("Temporalité", ["jour", "heure", "semaine", "mois"], index=0)

    st.divider()
    st.subheader("📅 Périodes testées")

    mode_periode = st.radio(
        "Mode", ["Durées prédéfinies", "Plages de dates"],
        index=0, horizontal=True, key="opti_mode_periode",
    )

    # periodes = liste de (label, duree_bougies, date_range_ou_None)
    periodes = []

    if mode_periode == "Durées prédéfinies":
        durees_raw = st.text_input(
            "Durées (nb de bougies, séparées par des virgules)",
            value=DUREES_DEFAUT,
            help="Ex : 180,360,720,1080 — une heatmap par durée",
        )
        try:
            durees = sorted({
                int(x.strip()) for x in durees_raw.split(",")
                if x.strip().isdigit() and int(x.strip()) > 1
            })
        except Exception:
            durees = [180, 360, 720, 1080]
        if not durees:
            durees = [180, 360, 720, 1080]
        periodes = [(f"{d}j", d, None) for d in durees]

    else:
        st.caption("Les 3 régimes de marché par défaut — modifiables")
        for i, (nom_defaut, d1_defaut, d2_defaut) in enumerate(PLAGES_DEFAUT):
            with st.container(border=True):
                nom = st.text_input(
                    "Nom", value=nom_defaut, key=f"opti_plage_nom_{i}",
                    label_visibility="collapsed",
                )
                c1, c2 = st.columns(2)
                with c1:
                    d1 = st.date_input("Du", value=d1_defaut, key=f"opti_plage_d1_{i}")
                with c2:
                    d2 = st.date_input("Au", value=d2_defaut, key=f"opti_plage_d2_{i}")
                if d1 < d2:
                    nb_jours = (d2 - d1).days
                    periodes.append((nom, max(1, nb_jours), (d1, d2)))
                    st.caption(f"→ {nb_jours} jours")
                else:
                    st.error("Début doit précéder fin")

    st.divider()

    # Nombre de bougies à charger : la plus longue période demandée
    duree_max_chargement = max([p[1] for p in periodes], default=365)

    if st.button("🔄 Charger les données", width="stretch"):
        with st.spinner(f"Récupération OHLCV {coin_label}..."):
            try:
                st.session_state.opti_df_ohlcv = fetch_ohlcv(
                    coin_id, timeframe, max(duree_max_chargement, 365)
                )
                st.success(f"✅ {len(st.session_state.opti_df_ohlcv)} bougies chargées")
            except Exception as e:
                st.error(f"Erreur : {e}")

# ---------------------------------------------------------------------------
# 1. Stratégie (indicateurs)
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Stratégie")

is_short = st.radio(
    "Direction", ["🟢 Long", "🔴 Short"], horizontal=True, key="opti_dir"
) == "🔴 Short"

label_entry = "🟢 Indicateurs d'achat" if not is_short else "🔴 Indicateurs d'entrée short"
label_exit = "🔴 Indicateurs de vente" if not is_short else "🟢 Indicateurs de sortie short"

with st.container(border=True):
    st.markdown(f"#### {label_entry}")
    ind_achat = render_indicator_bloc("buy" if not is_short else "sell", "opti_buy")

st.write("")

with st.container(border=True):
    st.markdown(f"#### {label_exit}")
    st.caption(
        "Indicateurs de sortie **optionnels** — la sortie se fait sur TP/SL "
        "OU sur signal si tu en configures un ici."
    )
    ind_vente = render_indicator_bloc("sell" if not is_short else "buy", "opti_sell")

st.divider()

# ---------------------------------------------------------------------------
# 2. Ranges TP et SL
# ---------------------------------------------------------------------------
st.subheader("2️⃣ Grille TP × SL")

col_tp, col_sl = st.columns(2)

with col_tp:
    st.markdown("**🎯 Take Profit (%)**")
    t1, t2, t3 = st.columns(3)
    with t1:
        tp_min = st.number_input("TP min", 0.5, 100.0, 3.0, 0.5, key="tp_min")
    with t2:
        tp_max = st.number_input("TP max", 0.5, 100.0, 8.0, 0.5, key="tp_max")
    with t3:
        tp_pas = st.number_input("Pas TP", 0.1, 10.0, 0.5, 0.1, key="tp_pas")

with col_sl:
    st.markdown("**🛑 Stop Loss (%)**")
    s1, s2, s3 = st.columns(3)
    with s1:
        sl_min = st.number_input("SL min", 0.1, 50.0, 0.5, 0.5, key="sl_min")
    with s2:
        sl_max = st.number_input("SL max", 0.1, 50.0, 4.0, 0.5, key="sl_max")
    with s3:
        sl_pas = st.number_input("Pas SL", 0.1, 10.0, 0.5, 0.1, key="sl_pas")


def _build_range(vmin: float, vmax: float, pas: float) -> list[float]:
    """Construit la liste des valeurs de vmin à vmax inclus, par incréments de pas."""
    if vmax < vmin or pas <= 0:
        return []
    n = int(round((vmax - vmin) / pas)) + 1
    return [round(vmin + i * pas, 4) for i in range(n)]


tp_values = _build_range(tp_min, tp_max, tp_pas)
sl_values = _build_range(sl_min, sl_max, sl_pas)
nb_combos = len(tp_values) * len(sl_values)
nb_periodes = len(periodes)
nb_total = nb_combos * nb_periodes

if not tp_values or not sl_values:
    st.error("⚠️ Range invalide — vérifie que max ≥ min et que le pas est positif.")
    st.stop()

if nb_periodes == 0:
    st.error("⚠️ Aucune période valide — vérifie tes durées ou tes plages de dates.")
    st.stop()

col_i1, col_i2, col_i3 = st.columns([1, 1, 3])
with col_i1:
    st.metric("Combinaisons", f"{nb_combos}")
    st.caption(f"{len(tp_values)} TP × {len(sl_values)} SL")
with col_i2:
    st.metric("Périodes", f"{nb_periodes}")
    st.caption(", ".join(p[0] for p in periodes))
with col_i3:
    # ~0.12 s par backtest sur 1000 bougies (mesuré)
    duree_estimee = nb_total * 0.12
    st.metric("Backtests au total", f"{nb_total}")
    if nb_total > 1500:
        st.error(f"⚠️ ≈ **{duree_estimee/60:.0f} min** de calcul. Augmente le pas.")
    elif nb_total > 600:
        st.warning(f"⏱️ ≈ **{duree_estimee/60:.1f} min** de calcul.")
    else:
        st.info(f"⏱️ ≈ **{duree_estimee:.0f} s** de calcul.")

st.divider()

# ---------------------------------------------------------------------------
# 3. Lancer
# ---------------------------------------------------------------------------
df_ohlcv = st.session_state.opti_df_ohlcv

if df_ohlcv is None:
    st.warning("👈 Charge d'abord les données marché depuis la sidebar.")
    st.stop()

if st.button("▶️ Lancer l'optimisation", type="primary", width="stretch"):

    strategy_base = {
        "is_short": is_short,
        "ind_achat": dict(ind_achat),
        "ind_vente": dict(ind_vente),
    }

    # MM BTC si un croisement vs BTC est configuré
    for cfg in (strategy_base["ind_achat"], strategy_base["ind_vente"]):
        periode_btc = cfg.get("btc_cross_period")
        if periode_btc:
            try:
                cfg["btc_mm"] = fetch_btc_mm(
                    timeframe, periode_btc, max(duree_max_chargement, 365)
                )
            except Exception as e:
                st.warning(f"MM BTC indisponible : {e}")
                cfg["btc_mm"] = None
        else:
            cfg["btc_mm"] = None

    progress = st.progress(0.0, text="Préparation des indicateurs...")

    # Indicateurs + signaux : calculés UNE fois pour toutes les combinaisons
    # ET toutes les périodes (ils portent sur le df complet, le découpage
    # par durée/plage se fait ensuite dans run_backtest_single)
    pre = precompute(df_ohlcv, strategy_base)

    lignes = []
    fait = 0
    for label_periode, duree_p, range_p in periodes:
        for sl in sl_values:
            for tp in tp_values:
                res = run_backtest_single(
                    df=df_ohlcv,
                    strategy={**strategy_base, "tp_pct": tp, "sl_pct": sl},
                    capital=capital,
                    frais_pct=frais_pct,
                    duree=duree_p,
                    date_range=range_p,
                    precomputed=pre,
                )
                drawdown = res["drawdown_max"]
                lignes.append({
                    "Période":        label_periode,
                    "TP (%)":         tp,
                    "SL (%)":         sl,
                    "Rendement (%)":  res["rendement_pct"],
                    "B&H (%)":        res["bnh_rendement"],
                    "Alpha (%)":      round(res["rendement_pct"] - res["bnh_rendement"], 2),
                    "Plus-value ($)": res["plus_value_eur"],
                    "Win rate (%)":   res["win_rate"],
                    "Drawdown (%)":   drawdown,
                    "Nb trades":      res["nb_trades"],
                    "Détention (h)":  res["avg_hold_h"],
                    "Rendement/DD":   round(res["rendement_pct"] / drawdown, 2) if drawdown > 0 else 0.0,
                    "Ratio R/R":      round(tp / sl, 2) if sl > 0 else 0.0,
                })
                fait += 1
                progress.progress(
                    fait / nb_total,
                    text=f"{fait}/{nb_total} — {label_periode} · TP {tp}% / SL {sl}%",
                )

    progress.empty()
    st.session_state.opti_results = pd.DataFrame(lignes)
    st.session_state.opti_periodes = [p[0] for p in periodes]
    st.success(f"✅ {nb_combos} combinaisons × {nb_periodes} périodes = {nb_total} backtests")

# ---------------------------------------------------------------------------
# 4. Résultats
# ---------------------------------------------------------------------------
df_res = st.session_state.opti_results
labels_periodes = st.session_state.opti_periodes

if df_res is None or df_res.empty:
    st.stop()

st.divider()
st.header("📊 Résultats")

METRIQUES = {
    "Rendement (%)":  ("Rendement de la stratégie",              True),
    "B&H (%)":        ("Rendement du Buy & Hold sur la période", True),
    "Rendement/DD":   ("Rendement rapporté au drawdown max",     True),
    "Win rate (%)":   ("% de trades gagnants",                   True),
    "Plus-value ($)": ("Gain absolu en dollars",                 True),
    "Drawdown (%)":   ("Perte max depuis un sommet (bas = bon)", False),
    "Nb trades":      ("Nombre de trades fermés",                True),
}

col_m, col_desc = st.columns([1, 2])
with col_m:
    metrique = st.selectbox("Métrique affichée", list(METRIQUES.keys()), index=0)
with col_desc:
    description, plus_haut_mieux = METRIQUES[metrique]
    st.caption(f"↳ {description}")
    if metrique == "B&H (%)":
        st.warning(
            "⚠️ Le Buy & Hold ne dépend **pas** du TP/SL — il est identique pour "
            "toutes les cases d'une même période. La heatmap sera donc uniforme. "
            "Utilise-le pour comparer les périodes entre elles, ou consulte-le en "
            "colonne de référence dans les tableaux détaillés."
        )

echelle = "RdYlGn" if plus_haut_mieux else "RdYlGn_r"

nb_p = len(labels_periodes)


def _heatmap(pivot, titre, nom_metrique, colorscale, zmin=None, zmax=None):
    """Construit une heatmap TP (abscisse) x SL (ordonnée)."""
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[str(v) for v in pivot.columns],
        y=[str(v) for v in pivot.index],
        colorscale=colorscale,
        zmin=zmin, zmax=zmax,
        colorbar=dict(title=nom_metrique),
        hovertemplate="TP : %{x}%<br>SL : %{y}%<br>" + nom_metrique + " : %{z}<extra></extra>",
        text=pivot.values,
        texttemplate="%{text:.1f}",
        textfont={"size": 10},
    ))
    fig.update_layout(
        title=titre,
        xaxis_title="Take Profit (%)",
        yaxis_title="Stop Loss (%)",
        height=max(380, 38 * len(pivot.index) + 150),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# Échelle de couleur commune à toutes les périodes pour pouvoir les comparer
z_min = float(df_res[metrique].min())
z_max = float(df_res[metrique].max())


def _colorier(val):
    """Vert si positif, rouge si négatif."""
    try:
        v = float(val)
        if v > 0:
            return "color: #22C55E; font-weight: bold"
        if v < 0:
            return "color: #EF4444; font-weight: bold"
    except (TypeError, ValueError):
        pass
    return ""


# Colonnes signées : un gain est vert, une perte est rouge.
# Volontairement SANS le drawdown / win rate / nb trades — toujours positifs,
# les colorer en vert laisserait croire à un gain.
COLS_SIGNEES = ["Rendement (%)", "B&H (%)", "Alpha (%)", "Plus-value ($)", "Rendement/DD"]


def _afficher_tableau(df_tab: pd.DataFrame):
    """Affiche un tableau avec les colonnes signées colorées vert/rouge."""
    cols = [c for c in COLS_SIGNEES if c in df_tab.columns]
    formats = {
        c: "{:.2f}" for c in df_tab.columns
        if df_tab[c].dtype.kind == "f"
    }
    style = df_tab.style.format(formats)
    if cols:
        style = style.map(_colorier, subset=cols)
    st.dataframe(style, width="stretch", hide_index=True)


# ── Onglets : Robustesse + une heatmap par période ───────────────────────
onglets = st.tabs(["🛡️ Robustesse"] + [f"📅 {lbl}" for lbl in labels_periodes])

# ── Onglet Robustesse : croise toutes les périodes ───────────────────────
with onglets[0]:
    st.markdown(
        "**Une combinaison n'est fiable que si elle tient sur toutes les périodes.** "
        "Ce tableau agrège les résultats — le **pire** résultat compte plus que le meilleur."
    )

    agg = df_res.groupby(["TP (%)", "SL (%)"]).agg(
        pire=(metrique, "min"),
        moyenne=(metrique, "mean"),
        meilleur=(metrique, "max"),
        rendement_moyen=("Rendement (%)", "mean"),
        rendement_pire=("Rendement (%)", "min"),
        dd_pire=("Drawdown (%)", "max"),
        wr_moyen=("Win rate (%)", "mean"),
        trades_moyen=("Nb trades", "mean"),
    ).reset_index()

    # Nombre de périodes où le rendement est positif
    positifs = (
        df_res.assign(_ok=df_res["Rendement (%)"] > 0)
        .groupby(["TP (%)", "SL (%)"])["_ok"].sum()
        .reset_index(name="periodes_positives")
    )
    agg = agg.merge(positifs, on=["TP (%)", "SL (%)"])
    agg["Ratio R/R"] = (agg["TP (%)"] / agg["SL (%)"]).round(2)

    vue = st.radio(
        "Vue",
        ["Pire période", "Moyenne", "Nb périodes gagnantes"],
        horizontal=True, key="opti_vue_robustesse",
    )

    if vue == "Pire période":
        col_z = "pire"
        titre_z = f"{metrique} — pire des {nb_p} périodes"
        st.caption(
            "Le résultat le plus faible obtenu sur l'ensemble des périodes. "
            "Vue la plus sévère, et la plus honnête."
        )
        scale, zmin_v, zmax_v = echelle, z_min, z_max
    elif vue == "Moyenne":
        col_z = "moyenne"
        titre_z = f"{metrique} — moyenne des {nb_p} périodes"
        st.caption("La moyenne lisse les écarts — utile mais masque les périodes catastrophiques.")
        scale, zmin_v, zmax_v = echelle, z_min, z_max
    else:
        col_z = "periodes_positives"
        titre_z = f"Nombre de périodes en rendement positif (sur {nb_p})"
        st.caption(
            f"Combien de périodes finissent en gain. Une combinaison à {nb_p}/{nb_p} "
            "est robuste tous régimes confondus."
        )
        scale, zmin_v, zmax_v = "RdYlGn", 0, nb_p

    pivot_rob = agg.pivot(index="SL (%)", columns="TP (%)", values=col_z)
    st.plotly_chart(
        _heatmap(pivot_rob, titre_z, col_z, scale, zmin_v, zmax_v),
        width="stretch",
    )

    # ── Classement robustesse : trié sur la pire période ──────────────────
    st.subheader("🏆 Classement par robustesse")
    st.caption(
        "Trié sur la **pire** période — une combinaison en tête ici n'a jamais "
        "d'effondrement, quel que soit le régime de marché."
    )

    classement = agg.sort_values("pire", ascending=not plus_haut_mieux).head(15).copy()
    classement = classement.rename(columns={
        "pire":               f"Pire {metrique}",
        "moyenne":            f"Moy. {metrique}",
        "meilleur":           f"Best {metrique}",
        "rendement_moyen":    "Rdt moyen (%)",
        "rendement_pire":     "Rdt pire (%)",
        "dd_pire":            "DD pire (%)",
        "wr_moyen":           "WR moyen (%)",
        "trades_moyen":       "Trades moy.",
        "periodes_positives": f"Périodes + (/{nb_p})",
    })

    # On ne colore que les colonnes réellement signées : un drawdown, un win rate
    # ou un nb de trades sont toujours positifs — les afficher en vert serait trompeur
    NON_SIGNEES = ("Drawdown", "DD ", "WR ", "Win rate", "Trades", "Périodes",
                   "Nb trades", "Ratio", "TP (%)", "SL (%)")
    cols_couleur = [
        col for col in classement.columns
        if classement[col].dtype.kind in "if"
        and not any(mot in col for mot in NON_SIGNEES)
    ]
    st.dataframe(
        classement.style.map(_colorier, subset=cols_couleur).format({
            col: "{:.2f}" for col in classement.columns
            if classement[col].dtype.kind == "f"
        }),
        width="stretch", hide_index=True,
    )

    # ── Combinaison la plus robuste ──────────────────────────────────────
    best_rob = classement.iloc[0]
    st.subheader("✅ Combinaison la plus robuste")
    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("TP", f"{best_rob['TP (%)']}%")
    b2.metric("SL", f"{best_rob['SL (%)']}%")
    b3.metric("Ratio R/R", f"{best_rob['Ratio R/R']}:1")
    b4.metric("Rdt moyen", f"{best_rob['Rdt moyen (%)']:+.2f}%")
    b5.metric(
        "Périodes gagnantes",
        f"{int(best_rob[f'Périodes + (/{nb_p})'])}/{nb_p}",
    )

# ── Un onglet par période ────────────────────────────────────────────────
for idx, label_p in enumerate(labels_periodes, start=1):
    with onglets[idx]:
        sous_df = df_res[df_res["Période"] == label_p]
        if sous_df.empty:
            st.info("Aucun résultat sur cette période.")
            continue

        pivot_p = sous_df.pivot(index="SL (%)", columns="TP (%)", values=metrique)
        st.plotly_chart(
            _heatmap(
                pivot_p, f"{metrique} — {label_p} · {coin_label} / {timeframe}",
                metrique, echelle, z_min, z_max,
            ),
            width="stretch",
        )

        meilleur = (
            sous_df.loc[sous_df[metrique].idxmax()] if plus_haut_mieux
            else sous_df.loc[sous_df[metrique].idxmin()]
        )
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("TP", f"{meilleur['TP (%)']}%")
        m2.metric("SL", f"{meilleur['SL (%)']}%")
        m3.metric("Rendement", f"{meilleur['Rendement (%)']:+.2f}%")
        m4.metric("Win rate", f"{meilleur['Win rate (%)']:.1f}%")
        m5.metric("Drawdown", f"{meilleur['Drawdown (%)']:.1f}%")
        st.caption(
            f"Buy & Hold sur la période : {meilleur['B&H (%)']:+.2f}% · "
            f"alpha {meilleur['Alpha (%)']:+.2f}% · "
            f"{int(meilleur['Nb trades'])} trades"
        )

        with st.expander(f"📋 Toutes les combinaisons — {label_p}", expanded=False):
            _afficher_tableau(
                sous_df.sort_values(metrique, ascending=not plus_haut_mieux)
            )

# ---------------------------------------------------------------------------
# 5. Export
# ---------------------------------------------------------------------------
st.divider()
st.download_button(
    "⬇️ Télécharger tous les résultats (CSV)",
    data=df_res.to_csv(index=False).encode("utf-8"),
    file_name=f"optimisation_tp_sl_{coin_id}_{timeframe}.csv",
    mime="text/csv",
)

st.info(
    "💡 **Comment lire ces heatmaps.** Ne prends pas la meilleure case d'une période "
    "isolée — c'est presque toujours du sur-ajustement. Cherche une **zone verte "
    "contiguë présente sur toutes les périodes** : si les combinaisons voisines "
    "tiennent aussi et que l'onglet Robustesse la confirme, le réglage est solide. "
    "Une case verte isolée entourée de rouge est un signal d'alerte, pas une trouvaille."
)
