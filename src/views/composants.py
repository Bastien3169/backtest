"""
src/views/composants.py
Briques d'interface partagées par les pages de backtest, pour qu'elles se
ressemblent toutes :

    barre de gauche   ⚙️ Paramètres · 📊 Marché · 📅 Périodes testées
    couleurs          vert / rouge selon le signe, couleur des verdicts
    tableaux          mise en forme commune (formats + couleurs)

Chaque page passe un PRÉFIXE de clés (« bt_ », « opti_ », « scan_ », « at_ ») :
les réglages d'une page ne se mélangent pas avec ceux d'une autre.
Les valeurs par défaut sont posées une fois dans st.session_state puis lues par
les widgets (jamais de `value=` en plus) : app.py peut conserver ces réglages
d'une page à l'autre sans que Streamlit signale un widget à double valeur.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.utils.data_loader import get_all_assets

TEMPORALITES = ["jour", "heure", "semaine", "mois"]
DUREES_DEFAUT = "180,360,720,1080"
# Les trois régimes de marché de référence (mêmes dates sur toutes les pages)
PLAGES_DEFAUT = [
    ("Bull", date(2024, 10, 1), date(2025, 10, 1)),
    ("Range", date(2024, 4, 15), date(2024, 9, 30)),
    ("Bear", date(2025, 10, 1), date(2026, 6, 3)),
]

VERT, ROUGE, ORANGE, GRIS = "#22C55E", "#EF4444", "#d98e04", "#888"


# ---------------------------------------------------------------------------
# Couleurs et tableaux
# ---------------------------------------------------------------------------

def couleur_signe(v) -> str:
    if not isinstance(v, (int, float)) or pd.isna(v):
        return ""
    return f"color: {VERT if v > 0 else ROUGE if v < 0 else GRIS}"


def couleur_verdict(v) -> str:
    if not isinstance(v, str):
        return ""
    if v.startswith("✅"):
        return f"color: {VERT}; font-weight: 600"
    if v.startswith("❌"):
        return f"color: {ROUGE}; font-weight: 600"
    if v.startswith(("⚠️", "⏳")):
        return f"color: {ORANGE}; font-weight: 600"
    return ""


def tableau(df: pd.DataFrame, signes=(), verdicts=(), formats: dict | None = None):
    """Styler commun : formats, vert/rouge sur `signes`, couleur des verdicts sur `verdicts`."""
    sty = df.style.format(formats or {}, na_rep="—")
    appliquer = getattr(sty, "map", None) or sty.applymap      # pandas < 2.1 : applymap
    if signes:
        sty = appliquer(couleur_signe, subset=list(signes))
        appliquer = getattr(sty, "map", None) or sty.applymap
    if verdicts:
        sty = appliquer(couleur_verdict, subset=list(verdicts))
    return sty


# ---------------------------------------------------------------------------
# Barre de gauche
# ---------------------------------------------------------------------------

def _defaut(cle: str, valeur):
    st.session_state.setdefault(cle, valeur)
    return cle


def frais(prefixe: str) -> float:
    return float(st.number_input("Frais par transaction (%)", 0.0, 10.0, step=0.01, format="%.2f",
                                 key=_defaut(f"{prefixe}frais", 0.1),
                                 help="Comptés à l'entrée ET à la sortie de chaque trade."))


def capital(prefixe: str) -> float:
    return float(st.number_input("Capital ($)", min_value=1.0, step=100.0,
                                 key=_defaut(f"{prefixe}capital", 1000.0)))


TOUTES = "Toutes"


def marche(prefixe: str, multi: bool = False, indices: bool = False) -> tuple[list[dict], str]:
    """📊 Marché : paire + temporalité. Retourne ([actifs], temporalité).
    multi=True : la liste commence par « Toutes », choisie par défaut."""
    st.subheader("📊 Marché")
    tous_actifs = [c for c in get_all_assets() if c["symbol"] not in {"USDC", "USDT", "DAI"}]
    cryptos = [c for c in tous_actifs if not c["id"].startswith("^")]
    if multi and indices:
        offre = tous_actifs if st.checkbox("Inclure les indices", key=_defaut(f"{prefixe}indices", False)) \
            else cryptos
    else:
        offre = tous_actifs if not multi else cryptos
    par_libelle = {f"{c['symbol']} — {c['name']}": c for c in offre}
    options = ([TOUTES] if multi else []) + list(par_libelle)
    cle = _defaut(f"{prefixe}paire", options[0])
    if st.session_state[cle] not in options:          # liste des actifs changée depuis
        st.session_state[cle] = options[0]
    nom = st.selectbox("Paire", options, key=cle)
    choisis = offre if nom == TOUTES else [par_libelle[nom]]
    if nom == TOUTES:
        st.caption(f"{len(offre)} actifs")
    temporalite = st.selectbox("Temporalité", TEMPORALITES, key=_defaut(f"{prefixe}temporalite", "jour"),
                               help="Toutes les longueurs (MM, durées) sont en bougies de cette "
                                    "temporalité. Heure : 730 jours maximum (limite Yahoo).")
    return choisis, temporalite


def paires(prefixe: str) -> tuple[list[dict], str]:
    """📊 Marché pour la page Stratégies : BTC par défaut ; une, plusieurs ou « Toutes ».
    Retourne ([actifs], temporalité)."""
    st.subheader("📊 Marché")
    tous_actifs = [c for c in get_all_assets() if c["symbol"] not in {"USDC", "USDT", "DAI"}]
    cryptos = [c for c in tous_actifs if not c["id"].startswith("^")]
    par_libelle = {f"{c['symbol']} — {c['name']}": c for c in tous_actifs}
    options = [TOUTES] + list(par_libelle)
    # Par défaut : BTC (une paire = la page complète, graphiques compris)
    btc = next((n for n, c in par_libelle.items() if c["symbol"] == "BTC"), options[1])
    cle = _defaut(f"{prefixe}paires", [btc])
    st.session_state[cle] = [n for n in st.session_state[cle] if n in options] or [btc]
    precedent = list(st.session_state[cle])

    def _exclusif():
        # « Toutes » et une sélection ne vont pas ensemble : le dernier choix l'emporte
        noms = st.session_state[cle]
        if TOUTES in noms and len(noms) > 1:
            st.session_state[cle] = [TOUTES] if TOUTES not in precedent else [n for n in noms if n != TOUTES]

    noms = st.multiselect("Paires", options, key=cle, on_change=_exclusif,
                          help="Une paire : résultats détaillés avec graphiques. Plusieurs : ajoute-les "
                               "une à une. « Toutes » = toutes les cryptos (sans les indices).")
    if TOUTES in noms:
        choisis = cryptos
        st.caption(f"{len(cryptos)} cryptos")
    elif noms:
        choisis = [par_libelle[n] for n in noms]
    else:                                   # sélection vidée : on revient sur BTC
        choisis = [par_libelle[btc]]
        st.caption("Aucune paire choisie : BTC par défaut.")
    temporalite = st.selectbox("Temporalité", TEMPORALITES, key=_defaut(f"{prefixe}temporalite", "jour"),
                               help="Toutes les longueurs (MM, durées) sont en bougies de cette "
                                    "temporalité. Heure : 730 jours maximum (limite Yahoo).")
    return choisis, temporalite


def periodes(prefixe: str, durees_defaut: str = DUREES_DEFAUT) -> tuple[str, list[dict]]:
    """📅 Périodes testées. Retourne (mode, [{"nom", "bougies", "plage"}]).

    mode = "durees" : les N dernières bougies ; plage = None
    mode = "plages" : plage = (début, fin) ; bougies = nombre de jours de la plage"""
    st.subheader("📅 Périodes testées")
    choix = st.radio("Mode", ["Durées prédéfinies", "Plages de dates"], horizontal=True,
                     key=_defaut(f"{prefixe}mode", "Durées prédéfinies"))
    if choix == "Durées prédéfinies":
        brut = st.text_input("Durées (nb de bougies, séparées par des virgules)",
                             key=_defaut(f"{prefixe}durees", durees_defaut),
                             help="Ex : 180,360,720 — une ligne de résultats par durée")
        durees = sorted({int(x) for x in (y.strip() for y in brut.split(",")) if x.isdigit() and int(x) > 1})
        if not durees:
            st.error("Indique au moins une durée.")
        return "durees", [{"nom": f"{d} bougies", "bougies": d, "plage": None} for d in durees]

    cle = f"{prefixe}plages"
    st.session_state.setdefault(cle, list(PLAGES_DEFAUT))
    sortie, garder = [], []
    for i, (nom, d1, d2) in enumerate(st.session_state[cle]):
        with st.container(border=True):
            h1, h2 = st.columns([5, 1])
            nom = h1.text_input("Nom", value=nom, key=f"{prefixe}plage_nom_{i}", label_visibility="collapsed")
            supprimer = h2.button("✕", key=f"{prefixe}btn_plage_del_{i}", help="Retirer cette plage")
            c1, c2 = st.columns(2)
            d1 = c1.date_input("Du", value=d1, key=f"{prefixe}plage_d1_{i}")
            d2 = c2.date_input("Au", value=d2, key=f"{prefixe}plage_d2_{i}")
            if supprimer and len(st.session_state[cle]) > 1:
                continue
            garder.append((nom, d1, d2))
            if d1 < d2:
                sortie.append({"nom": nom, "bougies": max(1, (d2 - d1).days), "plage": (d1, d2)})
                st.caption(f"→ {(d2 - d1).days} jours")
            else:
                st.error("Début doit précéder fin")
    ajout = st.button("➕ Ajouter une plage", key=f"{prefixe}btn_plage_add", width="stretch")
    if ajout:
        garder.append((f"Plage {len(garder) + 1}", date.today() - timedelta(days=90), date.today()))
    if ajout or len(garder) != len(st.session_state[cle]):
        st.session_state[cle] = garder
        # Les widgets sont numérotés : après un ajout ou une suppression, on efface leur
        # état pour qu'ils se recréent depuis la liste (sinon la plage 2 garderait les
        # dates de l'ancienne plage 2).
        for k in [k for k in st.session_state if str(k).startswith(f"{prefixe}plage_")]:
            del st.session_state[k]
        st.rerun()
    st.session_state[cle] = garder
    return "plages", sortie
