"""
pages/7_🧪_Atelier.py
Atelier de backtest : compose ta stratégie avec des boutons, teste-la.

Conditions d'entrée (toutes vraies) + sens + sorties (la première atteinte).
Moteur : src/utils/atelier.py. Chaque test est comparé au même sens pris au
hasard, et gardé dans « Mes tests ».
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import streamlit as st

from src.utils import atelier as A

st.set_page_config(page_title="Analyse marché (AM)", page_icon="🧭", layout="wide")
_user = st.session_state.get("user") or {}
_uid = _user.get("id")

st.title("🧭 Analyse marché (AM)")
st.caption("Teste une idée de marché (régime du BTC, OI, compression, tendance) sur TOUS les alts, "
           "comparée au même sens pris au hasard. Prix depuis 2020 ; conditions sur l'OI "
           "seulement depuis octobre 2026 (le test se restreint alors tout seul à cette période).")

VERT, ROUGE, ORANGE = "#2e9e5b", "#d64545", "#d98e04"

# ---------------------------------------------------------------------------
# État : liste des conditions
# ---------------------------------------------------------------------------
if "at_conds" not in st.session_state:
    st.session_state["at_conds"] = []
    st.session_state["at_n"] = 0
# Valeurs par défaut posées UNE fois dans l'état : les boutons de préréglage peuvent
# alors les changer sans que Streamlit se plaigne d'un widget à double valeur.
for _k, _v in {"at_sens": "📈 Long", "at_mms": [20, 100], "at_t_jours": True, "at_jours": 7,
               "at_t_sltp": False, "at_sl": 8.0, "at_tp": 15.0, "at_t_mm": False, "at_mm": 20}.items():
    st.session_state.setdefault(_k, _v)


def _ajouter(type_="btc_mm", **valeurs):
    st.session_state["at_n"] += 1
    c = {"id": st.session_state["at_n"], "type": type_}
    for nom, genre, choix, _ in A.CONDITIONS[type_]["champs"]:
        c[nom] = valeurs.get(nom, choix[0] if genre == "choix" else choix)
    st.session_state["at_conds"].append(c)


def _setup_compression():
    st.session_state["at_conds"] = []
    _ajouter("compression", op="<", valeur=1.0)
    _ajouter("z_oi_24", op=">", valeur=2.0)
    st.session_state["at_sens"] = "🧭 Selon le BTC"
    st.session_state["at_mms"] = [20, 100]
    st.session_state["at_t_jours"], st.session_state["at_jours"] = True, 7


def _setup_tendance_long():
    st.session_state["at_conds"] = []
    _ajouter("tendance", sens="haussière")
    st.session_state["at_sens"] = "📈 Long"
    st.session_state["at_t_jours"] = False
    st.session_state["at_t_mm"], st.session_state["at_mm"] = True, 20


# ---------------------------------------------------------------------------
# 1. Conditions
# ---------------------------------------------------------------------------
st.subheader("1. Conditions d'entrée")
p1, p2, _ = st.columns([2, 2, 3])
p1.button("⚡ Ton setup : compression + z OI, sens BTC", on_click=_setup_compression)
p2.button("📈 Tendance long (sortie MM20)", on_click=_setup_tendance_long)
st.caption("Toutes les conditions doivent être vraies le même jour pour entrer.")

_types = list(A.CONDITIONS)
for c in list(st.session_state["at_conds"]):
    cid = c["id"]
    champs = A.CONDITIONS[c["type"]]["champs"]
    cols = st.columns([4] + [2] * len(champs) + [1])
    nouveau = cols[0].selectbox("Condition", _types, index=_types.index(c["type"]),
                                format_func=lambda k: A.CONDITIONS[k]["libelle"],
                                key=f"at_type_{cid}", label_visibility="collapsed")
    if nouveau != c["type"]:                          # type changé : on repart des valeurs par défaut
        idx = st.session_state["at_conds"].index(c)
        st.session_state["at_n"] += 1
        neuf = {"id": st.session_state["at_n"], "type": nouveau}
        for nom, genre, choix, _ in A.CONDITIONS[nouveau]["champs"]:
            neuf[nom] = choix[0] if genre == "choix" else choix
        st.session_state["at_conds"][idx] = neuf
        st.rerun()
    for col, (nom, genre, choix, lib) in zip(cols[1:], champs):
        k = f"at_{nom}_{cid}"
        if genre == "choix":
            c[nom] = col.selectbox(lib, choix, index=choix.index(c[nom]) if c[nom] in choix else 0,
                                   key=k, label_visibility="collapsed",
                                   format_func=lambda v, n=nom: f"MM{v}" if n == "mm" else str(v))
        elif genre == "entier":
            c[nom] = int(col.number_input(lib, 1, 365, int(c[nom]), 1, key=k, label_visibility="collapsed"))
        else:
            c[nom] = float(col.number_input(lib, value=float(c[nom]), step=0.5, key=k,
                                            label_visibility="collapsed"))
    if cols[-1].button("🗑️", key=f"at_del_{cid}", help="Retirer cette condition"):
        st.session_state["at_conds"] = [x for x in st.session_state["at_conds"] if x["id"] != cid]
        st.rerun()

st.button("➕ Ajouter une condition", on_click=_ajouter)

# ---------------------------------------------------------------------------
# 2. Sens
# ---------------------------------------------------------------------------
st.subheader("2. Sens")
sens_choix = st.radio("Sens", ["📈 Long", "📉 Short", "🧭 Selon le BTC"], horizontal=True,
                      key="at_sens", label_visibility="collapsed")
if sens_choix == "🧭 Selon le BTC":
    mms = st.multiselect("Long si le BTC est au-dessus de toutes ces MM, short s'il est en dessous de "
                         "toutes, rien sinon", A.MM_CHOIX, key="at_mms",
                         format_func=lambda v: f"MM{v}")
    sens = {"type": "btc", "mms": sorted(mms) or [100]}
else:
    sens = {"type": "long" if sens_choix == "📈 Long" else "short"}

# ---------------------------------------------------------------------------
# 3. Sorties
# ---------------------------------------------------------------------------
st.subheader("3. Sortie")
st.caption("Active une ou plusieurs sorties : la première atteinte ferme le trade.")
s1, s2, s3 = st.columns(3)
sorties = {}
with s1:
    if st.toggle("⏱️ Durée fixe", key="at_t_jours"):
        sorties["jours"] = int(st.number_input("Sortir après (jours)", 1, 365, step=1, key="at_jours"))
with s2:
    if st.toggle("🛑 Stop et objectif", key="at_t_sltp"):
        sorties["sl"] = float(st.number_input("Stop loss (%)", 0.0, 100.0, step=0.5, key="at_sl",
                                              help="0 = pas de stop"))
        sorties["tp"] = float(st.number_input("Objectif (%)", 0.0, 1000.0, step=0.5, key="at_tp",
                                              help="0 = pas d'objectif"))
with s3:
    if st.toggle("〰️ Croisement de MM", key="at_t_mm"):
        sorties["mm"] = st.selectbox("Sortir quand le prix repasse de l'autre côté de la", A.MM_CHOIX,
                                     key="at_mm", format_func=lambda v: f"MM{v}")

# ---------------------------------------------------------------------------
# Lancer
# ---------------------------------------------------------------------------
conditions = [{k: v for k, v in c.items() if k != "id"} for c in st.session_state["at_conds"]]
description = A.decrire(conditions, sens, sorties)
st.markdown(f"**Ta stratégie :** {description}")

pret = bool(sorties) and (sorties.get("jours") or sorties.get("sl") or sorties.get("tp") or sorties.get("mm"))
if not pret:
    st.warning("Active au moins une sortie.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _prix():
    return A.charger_prix()


@st.cache_data(ttl=3600, show_spinner=False)
def _oi():
    return A.charger_oi_journalier()


if st.button("▶️ Lancer le test", type="primary", disabled=not pret):
    with st.spinner("Chargement des prix (3 à 6 min la première fois, ensuite instantané)…"):
        prix, _ecartes = _prix()
    oi = {}
    if A.utilise_oi(conditions):
        with st.spinner("Lecture de l'historique d'OI…"):
            oi = _oi()
    with st.spinner("Simulation…"):
        try:
            res = A.lancer(prix, oi, conditions, sens, sorties)
            b = A.bilan(res)
            A.enregistrer(description, {"conditions": conditions, "sens": sens, "sorties": sorties}, b, _uid)
            st.session_state["at_res"] = (description, res, b)
        except Exception as e:
            st.error(f"Test impossible : {e}")

# ---------------------------------------------------------------------------
# Résultat
# ---------------------------------------------------------------------------
if "at_res" in st.session_state:
    desc, res, b = st.session_state["at_res"]
    st.subheader("Résultat")
    v = b["verdict"]
    (st.success if v.startswith("✅") else st.error if v.startswith("❌") else st.warning)(f"**{v}**")

    def _ligne(nom, s, app=None, test=None):
        d = {"": nom, "Trades": s.get("trades"), "Gagnants": s.get("gagnants"),
             "Gain moyen / trade": s.get("gain_moy"), "Gain médian": s.get("gain_med"),
             "Profit factor": s.get("pf"), "Levier max": f"×{s['levier_max']}" if s.get("levier_max") else "—"}
        if app is not None:
            d["PF ancien"], d["PF récent"] = app.get("pf"), test.get("pf")
        return d

    lignes = [_ligne("Ta stratégie", b["strat"], b.get("strat_app"), b.get("strat_test")),
              _ligne("Même sens au hasard", b["ref"], b.get("ref_app"), b.get("ref_test"))]
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch", column_config={
        "Gagnants": st.column_config.NumberColumn(format="%.0f %%"),
        "Gain moyen / trade": st.column_config.NumberColumn(format="%+.2f %%", help="Net de frais."),
        "Gain médian": st.column_config.NumberColumn(format="%+.2f %%"),
        "Profit factor": st.column_config.NumberColumn(format="%.2f", help="Gains ÷ pertes. > 1 = gagnant."),
        "Levier max": st.column_config.TextColumn(help="Moitié du levier qui aurait survécu à 9 trades sur 10."),
        "PF ancien": st.column_config.NumberColumn(format="%.2f", help="Avant la date de coupure."),
        "PF récent": st.column_config.NumberColumn(format="%.2f", help="Le dernier tiers de la période."),
    })
    periode = f"du {res['debut']:%d/%m/%Y} au {res['fin']:%d/%m/%Y}"
    if res["avec_oi"]:
        st.caption(f"⚠️ Condition sur l'OI : test {periode} seulement, un seul type de marché.")
    else:
        st.caption(f"Test {periode} · période récente à partir du {res['coupure']:%d/%m/%Y} · "
                   "« Même sens au hasard » = mêmes sorties, sans aucune condition.")
    if not res["trades"].empty:
        with st.expander("📈 Courbe et liste des trades"):
            t = res["trades"].sort_values("sortie")
            courbe = t.set_index(pd.to_datetime(t["sortie"]))["rend_pct"].cumsum().rename("Gains cumulés (%)")
            st.line_chart(courbe)
            st.caption("Somme des gains par trade, sans levier ni réinvestissement.")
            st.dataframe(t.sort_values("entree", ascending=False), hide_index=True, width="stretch",
                         column_config={"rend_pct": st.column_config.NumberColumn("Gain", format="%+.2f %%"),
                                        "mae_pct": st.column_config.NumberColumn("Pire moment", format="%.1f %%")})

# ---------------------------------------------------------------------------
# Mes tests
# ---------------------------------------------------------------------------
st.subheader("Mes tests")
h = A.historique(_uid)
if h.empty:
    st.caption("Aucun test pour l'instant.")
else:
    def _c(v):
        if isinstance(v, str) and v.startswith("✅"):
            return f"color: {VERT}; font-weight: 600"
        if isinstance(v, str) and v.startswith("❌"):
            return f"color: {ROUGE}; font-weight: 600"
        return f"color: {ORANGE}; font-weight: 600" if isinstance(v, str) else ""
    h = h[["quand", "description", "verdict", "trades", "gagnants", "gain_moy", "ref_gain_moy"]]
    sty = h.style
    st.dataframe((getattr(sty, "map", None) or sty.applymap)(_c, subset=["verdict"]),
                 hide_index=True, width="stretch", column_config={
        "quand": "Quand", "description": st.column_config.TextColumn("Stratégie", width="large"),
        "verdict": "Verdict", "trades": "Trades",
        "gagnants": st.column_config.NumberColumn("Gagnants", format="%.0f %%"),
        "gain_moy": st.column_config.NumberColumn("Gain moyen", format="%+.2f %%"),
        "ref_gain_moy": st.column_config.NumberColumn("Au hasard", format="%+.2f %%"),
    })
