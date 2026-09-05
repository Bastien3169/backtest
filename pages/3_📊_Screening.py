"""
pages/3_📊_Screening.py
Tableau de screening — choisir les actifs à trader sur Hyperliquid.

Rendu en st.dataframe natif plutôt qu'en lignes st.columns dessinées à la
main : tri par clic sur les 14 colonnes, largeurs ajustables, et la sparkline
rendue par LineChartColumn au lieu d'une figure Plotly par ligne (171 figures
par rerun, c'était le poste le plus lourd de la page).
"""

import sys
import os

_HERE = os.path.abspath(__file__)
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from src.utils.market_data import load_screening_data, perf_sur, FENETRE_RISQUE
from src.utils.coins_updater import update_coins
from src.utils.data_loader import get_top100_coins

st.set_page_config(page_title="Screening Crypto", page_icon="📊", layout="wide")

st.title("📊 Screening Crypto")
st.caption(
    "Survole le titre d'une colonne pour savoir ce qu'elle mesure et comment la lire. "
    f"Risque et tendance calculés sur les {FENETRE_RISQUE} derniers jours, en dollars."
)

_nb_coins = len(get_top100_coins())

# ---------------------------------------------------------------------------
# Mise à jour de la liste des actifs
# ---------------------------------------------------------------------------
with st.expander("🔁 Mettre à jour la liste des actifs (univers Hyperliquid)", expanded=False):
    st.markdown(
        f"Liste actuelle : **{_nb_coins} actifs**, tradables sur Hyperliquid "
        "**et** historisés sur Yahoo Finance.  \n"
        "Ce bouton lit l'univers des perps Hyperliquid, résout le ticker Yahoo de "
        "chacun — y compris les tickers suffixés type `HYPE32196-USD` — et ne garde "
        "que ceux qui ont un historique exploitable.  \n"
        "CoinGecko n'est plus utilisé que pour les noms lisibles.  \n"
        "⏱ Durée estimée : **5-10 minutes** (l'univers HL compte ~200 actifs)."
    )
    if st.button("🚀 Lancer la mise à jour", type="primary", key="update_coins"):
        prog = st.progress(0, text="Lecture de l'univers Hyperliquid...")
        try:
            available, skipped = update_coins(
                progress_cb=lambda p, m: prog.progress(p, text=m)
            )
            prog.empty()
            st.success(f"✅ {len(available)} actifs retenus (Hyperliquid ∩ Yahoo Finance)")
            if skipped:
                st.warning(
                    f"⚠️ {len(skipped)} actifs HL sans historique Yahoo, donc non "
                    f"backtestables : {', '.join(skipped)}"
                )
            st.info("✅ La liste est mise à jour — active au prochain chargement de données.")
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
    st.success(f"✅ {len(st.session_state.screening_df)} actifs chargés")

df = st.session_state.screening_df
if df is None or df.empty:
    st.info("Cliquez sur **Charger / Actualiser** pour afficher le tableau.")
    st.stop()

_ecartes = df.attrs.get("ecartes") or []
if _ecartes:
    st.warning(
        f"⚠️ {len(_ecartes)} actifs écartés — série de prix figée ou absente chez "
        f"Yahoo, donc chiffres non exploitables : {', '.join(_ecartes)}"
    )

if not df.attrs.get("hl_ok", True):
    st.info(
        "ℹ️ Contexte Hyperliquid indisponible pour ce chargement : funding, open "
        "interest et volume HL sont vides. Le reste du tableau est valide."
    )

# ---------------------------------------------------------------------------
# Perf sur N jours, recalculée à la volée depuis les clôtures déjà chargées
# ---------------------------------------------------------------------------
_cp1, _cp2 = st.columns([1, 3])
with _cp1:
    _n_jours = st.number_input(
        "Colonne perf. personnalisée (jours)", min_value=1, max_value=89, value=14, step=1,
        help="Ajoute une colonne de performance sur la durée de ton choix. "
             "Calculée depuis les clôtures déjà en mémoire — aucun rechargement.",
    )
df = df.copy()
df["perf_custom"] = df["closes"].apply(lambda c: perf_sur(pd.Series(c), int(_n_jours)))

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
PRESETS = {
    "Aucun": {},
    "Momentum liquide": {
        "perf_7d_min": 5.0, "amplitude_min": 3.0, "volume_min": 5.0,
        "position_min": 60, "funding_max": 40.0,
    },
    "Calme et profond": {
        "perf_7d_min": -100.0, "amplitude_min": 0.0, "volume_min": 50.0,
        "position_min": 0, "funding_max": 20.0,
    },
}

with st.expander("🔧 Filtres", expanded=True):
    _preset = st.radio("Préréglage", list(PRESETS), horizontal=True, key="scr_preset")
    _p = PRESETS[_preset]

    f1, f2, f3 = st.columns(3)
    with f1:
        perf_min = st.number_input(
            "Perf. 7 j minimum (%)", value=float(_p.get("perf_7d_min", -100.0)), step=1.0,
            key=f"scr_perf_{_preset}",
        )
        amplitude_min = st.number_input(
            "Amplitude quotidienne minimum (%)", 0.0, 30.0,
            float(_p.get("amplitude_min", 0.0)), 0.5, key=f"scr_ampl_{_preset}",
        )
    with f2:
        volume_min = st.number_input(
            "Volume 24 h minimum (M$)", 0.0, 5000.0,
            float(_p.get("volume_min", 0.0)), 1.0, key=f"scr_vol_{_preset}",
        )
        position_min = st.slider(
            "Position minimum dans le range 30 j", 0, 100,
            int(_p.get("position_min", 0)), key=f"scr_pos_{_preset}",
        )
    with f3:
        funding_max = st.number_input(
            "Funding annualisé maximum (%)", 0.0, 500.0,
            float(_p.get("funding_max", 500.0)), 5.0, key=f"scr_fund_{_preset}",
            help="Coût annualisé de porter un LONG. Au-delà de ~50 %, le portage "
                 "mange une grande partie du mouvement attendu.",
        )

# Un filtre ne doit jamais écarter une ligne parce que la donnée est absente :
# fillna avec la valeur qui laisse passer.
masque = (
    (df["perf_7d"].fillna(-1e9)       >= perf_min) &
    (df["amplitude_med"].fillna(1e9)  >= amplitude_min) &
    (df["volume_24h"].fillna(1e18)    >= volume_min * 1e6) &
    (df["position_range"].fillna(100) >= position_min) &
    (df["funding_annuel"].fillna(0).abs() <= funding_max)
)
df_filtre = df[masque].copy()

if df_filtre.empty:
    st.warning("Aucun actif ne passe ces filtres. Assouplis un critère.")
    st.stop()

df_filtre = df_filtre.sort_values("perf_7d", ascending=False, na_position="last")
df_filtre["volume_m"]    = df_filtre["volume_24h"] / 1e6
df_filtre["oi_m"]        = df_filtre["open_interest"] / 1e6
df_filtre["volume_hl_m"] = df_filtre["volume_hl_24h"] / 1e6

# ---------------------------------------------------------------------------
# Tableau
# ---------------------------------------------------------------------------
COLONNES = {
    "symbol": st.column_config.TextColumn(
        "Actif", width="small", pinned=True,
        help="Symbole. Seuls les actifs tradables sur Hyperliquid ET historisés "
             "sur Yahoo Finance sont listés — donc tous backtestables.",
    ),
    "name": st.column_config.TextColumn(
        "Nom", width="small",
        help="Nom lisible du token, tel que renvoyé par CoinGecko lors de la "
             "dernière mise à jour de la liste.",
    ),
    "closes": st.column_config.LineChartColumn(
        "90 j", width="small", color="auto",
        help="Clôtures des 90 derniers jours. Vert si la série monte sur la "
             "fenêtre affichée, rouge si elle descend — la couleur décrit donc "
             "la tendance 90 jours, pas la perf 7 j. La FORME est lisible, pas "
             "l'échelle : chaque tracé est normalisé sur son propre range.",
    ),
    "perf_24h": st.column_config.NumberColumn(
        "24 h", format="%+.2f %%", help="Variation depuis la clôture de la veille.",
    ),
    "perf_7d": st.column_config.NumberColumn(
        "7 j", format="%+.2f %%", help="Variation sur 7 jours.",
    ),
    "perf_custom": st.column_config.NumberColumn(
        f"{int(_n_jours)} j", format="%+.2f %%",
        help="Perf sur la durée choisie au-dessus du tableau.",
    ),
    "perf_30d": st.column_config.NumberColumn(
        "30 j", format="%+.2f %%",
        help="Variation sur 30 jours. Comparée à la perf 7 j, elle dit si le "
             "mouvement démarre ou s'il s'essouffle.",
    ),
    "position_range": st.column_config.ProgressColumn(
        "Position 30 j", min_value=0, max_value=100, format="%.0f",
        help="Où se situe le prix entre son plus bas et son plus haut des 30 "
             "derniers jours. 100 = sur ses sommets, tendance intacte. 40 = le "
             "mouvement a déjà rendu la moitié du terrain, même si la perf 7 j "
             "est belle.",
    ),
    "amplitude_med": st.column_config.NumberColumn(
        "Amplit. j.", format="%.2f %%",
        help="Amplitude quotidienne médiane : (haut − bas) / clôture, sur 30 jours. "
             "C'est le PLANCHER de stop loss exploitable. Un SL plus serré que "
             "cette valeur se fait toucher par le bruit ordinaire de la journée, "
             "sans que la thèse de trade soit invalidée.",
    ),
    "beta": st.column_config.NumberColumn(
        "β vs BTC", format="%.2f",
        help="Amplitude relative : quand le BTC bouge de 1 %, l'actif bouge de β %. "
             "β = 2 amplifie le double, dans les deux sens.",
    ),
    "corr_btc": st.column_config.ProgressColumn(
        "Corr. BTC", min_value=0, max_value=100, format="%.0f %%",
        help="À quel point l'actif bouge EN MÊME TEMPS que le BTC. 100 % = ils "
             "montent et descendent ensemble, 50 % = aucun lien. Dit le SENS "
             "commun, pas l'amplitude — c'est le rôle du bêta.",
    ),
    "volume_m": st.column_config.NumberColumn(
        "Vol. 24 h", format="%.1f M$",
        help="Volume échangé sur la dernière bougie journalière (source Yahoo).",
    ),
    "volume_rel": st.column_config.NumberColumn(
        "Vol. rel.", format="%.2f ×",
        help="Volume 24 h rapporté à la moyenne 30 jours. 3,00 × = trois fois "
             "l'activité habituelle. Une hausse sans volume et une hausse avec "
             "volume ne racontent pas la même histoire.",
    ),
    "volume_hl_m": st.column_config.NumberColumn(
        "Vol. HL", format="%.1f M$",
        help="Volume notionnel 24 h sur Hyperliquid — le marché où tes ordres "
             "partent réellement. C'est lui qui détermine ton slippage.",
    ),
    "oi_m": st.column_config.NumberColumn(
        "Open int.", format="%.1f M$",
        help="Positions ouvertes sur le perp HL. Mesure la profondeur réelle du "
             "marché, mieux que le market cap du token.",
    ),
    "funding_annuel": st.column_config.NumberColumn(
        "Funding /an", format="%+.1f %%",
        help="Coût annualisé de porter un LONG (un SHORT l'encaisse). Positif "
             "et élevé = tout le monde est déjà long, et tu paies pour les "
             "rejoindre. Au-delà de ~50 %/an, le portage mange une grande partie "
             "du mouvement attendu.",
    ),
}

st.dataframe(
    df_filtre[list(COLONNES)],
    column_config=COLONNES,
    hide_index=True,
    width="stretch",
    height=min(720, 40 * len(df_filtre) + 45),
)

st.caption(
    f"{len(df_filtre)} actifs affichés sur {len(df)} chargés · "
    "Clique sur un en-tête pour trier · Prix : yfinance (bougies journalières) · "
    "Funding, open interest et volume HL : Hyperliquid"
)
