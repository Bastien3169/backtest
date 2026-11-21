"""
src/views/conditions_bloc.py
Bloc Streamlit « Conditions de marché » — le pendant de indicator_bloc.py pour
les conditions de src/utils/conditions_marche.py. Facultatif : vide = aucun filtre.
"""

import streamlit as st

from src.utils import conditions_marche as CM


def render_conditions_marche(prefixe: str, temporalite: str) -> list[dict]:
    """Affiche le bloc et retourne la liste des conditions (dicts sans identifiant)."""
    cle = f"{prefixe}conds"
    st.session_state.setdefault(cle, [])
    st.session_state.setdefault(f"{prefixe}conds_n", 0)

    def _ajouter():
        st.session_state[f"{prefixe}conds_n"] += 1
        st.session_state[cle].append({"id": st.session_state[f"{prefixe}conds_n"], **CM.defaut("btc_mm")})

    types = list(CM.CONDITIONS)
    for c in list(st.session_state[cle]):
        cid = c["id"]
        champs = CM.CONDITIONS[c["type"]]["champs"]
        cols = st.columns([4] + [2] * len(champs) + [1])
        nouveau = cols[0].selectbox("Condition", types, index=types.index(c["type"]),
                                    format_func=lambda k: CM.CONDITIONS[k]["libelle"],
                                    key=f"{prefixe}cond_type_{cid}", label_visibility="collapsed")
        if nouveau != c["type"]:                   # type changé : valeurs par défaut du nouveau type
            c.clear()
            c.update({"id": cid, **CM.defaut(nouveau)})
            for k in [k for k in st.session_state if str(k).startswith(f"{prefixe}cond_") and
                      str(k).endswith(f"_{cid}") and not str(k).startswith(f"{prefixe}cond_type_")]:
                del st.session_state[k]
            st.rerun()
        for col, (nom, genre, choix, lib) in zip(cols[1:], champs):
            k = f"{prefixe}cond_{nom}_{cid}"
            if genre == "choix":
                c[nom] = col.selectbox(lib, choix, index=choix.index(c[nom]) if c[nom] in choix else 0,
                                       key=k, label_visibility="collapsed",
                                       format_func=lambda v, n=nom: f"MM{v}" if n == "mm" else str(v))
            elif genre == "entier":
                c[nom] = int(col.number_input(lib, 1, 5000, int(c[nom]), 1, key=k,
                                              label_visibility="collapsed"))
            else:
                c[nom] = float(col.number_input(lib, value=float(c[nom]), step=0.5, key=k,
                                                label_visibility="collapsed"))
        if cols[-1].button("🗑️", key=f"{prefixe}btn_cond_del_{cid}", help="Retirer cette condition"):
            st.session_state[cle] = [x for x in st.session_state[cle] if x["id"] != cid]
            st.rerun()
    st.button("➕ Ajouter une condition de marché", key=f"{prefixe}btn_cond_add", on_click=_ajouter)

    conditions = [{k: v for k, v in c.items() if k != "id"} for c in st.session_state[cle]]
    hors = CM.invalides(conditions, temporalite)
    if hors:
        st.error(f"Ces conditions n'existent pas en temporalité « {temporalite} » : " + ", ".join(hors))
    if CM.utilise_oi(conditions):
        st.caption("⚠️ Condition sur l'OI : historique seulement depuis octobre 2026, le test est "
                   "limité à cette période.")
    return conditions
