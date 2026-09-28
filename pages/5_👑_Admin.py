"""
pages/5_👑_Admin.py
Gestion de la base des utilisateurs (admin uniquement).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import streamlit as st

from src.auth import users as U
from src.auth.db import IS_SQLITE
from src.auth.ui import require_admin

st.set_page_config(page_title="Admin", page_icon="👑", layout="wide")
require_admin()

st.title("👑 Administration — utilisateurs")
if IS_SQLITE:
    st.warning("Base SQLite locale (DATABASE_URL absente). Sur Railway, c'est PostgreSQL.")

def _resultat(res):
    ok, msg = res
    if ok:
        st.session_state["_admin_msg"] = msg
        st.rerun()
    else:
        st.error(msg)


if msg := st.session_state.pop("_admin_msg", None):
    st.success(msg)

liste = U.admin_liste_users()
df = pd.DataFrame(liste)

# ---------------------------------------------------------------------------
# Inscriptions en attente de validation
# ---------------------------------------------------------------------------
en_attente = [r for r in liste if not r["approved"]]
if en_attente:
    st.subheader(f"⏳ En attente de validation ({len(en_attente)})")
    for r in en_attente:
        with st.container(border=True):
            ca, cb, cc = st.columns([4, 1, 1], vertical_alignment="center")
            ca.markdown(f"**{r['email']}**  \ninscrit le {r['created_at']:%d/%m/%Y %H:%M} (UTC)")
            if cb.button("✅ Valider", key=f"val_{r['id']}", width="stretch"):
                _resultat(U.admin_valider(r["id"], True))
            if cc.button("❌ Refuser", key=f"ref_{r['id']}", width="stretch",
                         help="Supprime la demande d'inscription"):
                _resultat(U.admin_supprimer(r["id"]))
    st.divider()

# ---------------------------------------------------------------------------
# Vue d'ensemble
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Inscrits", len(df))
c2.metric("En attente", len(en_attente))
c3.metric("Admins", int((df["role"] == "admin").sum()) if len(df) else 0)
c4.metric("Sessions actives", int(df["sessions_actives"].sum()) if len(df) else 0)

filtre = st.text_input("🔎 Filtrer par email")
vue = df[df["email"].str.contains(filtre.strip().lower(), regex=False)] if filtre and len(df) else df
st.dataframe(
    vue, hide_index=True, width="stretch",
    column_config={
        "id": st.column_config.NumberColumn("ID", width="small"),
        "email": "Email",
        "role": "Rôle",
        "created_at": st.column_config.DatetimeColumn("Inscrit le (UTC)", format="DD/MM/YYYY HH:mm"),
        "last_login": st.column_config.DatetimeColumn("Dernière connexion (UTC)", format="DD/MM/YYYY HH:mm"),
        "locked_until": st.column_config.DatetimeColumn("Bloqué jusqu'à (UTC)", format="DD/MM/YYYY HH:mm"),
        "approved": st.column_config.CheckboxColumn("Validé", width="small"),
        "sessions_actives": st.column_config.NumberColumn("Sessions", width="small"),
    },
)

# ---------------------------------------------------------------------------
# Actions sur un utilisateur
# ---------------------------------------------------------------------------
st.subheader("Actions")
if not len(df):
    st.info("Aucun utilisateur.")
    st.stop()

options = {f"{r['email']}  (#{r['id']}, {r['role']}{'' if r['approved'] else ', en attente'})": r
           for r in liste}
choix = st.selectbox("Utilisateur", list(options))
cible = options[choix]
protege = U.is_admin_email(cible["email"])
if protege:
    st.info("Compte admin principal : géré par les variables ADMIN_EMAIL / ADMIN_PASSWORD. "
            "Seule la fermeture des sessions est possible ici.")


col_a, col_b = st.columns(2)

with col_a:
    with st.container(border=True):
        st.markdown("**Statut** : " + ("✅ validé" if cible["approved"] else "⏳ en attente / suspendu"))
        if cible["approved"]:
            if st.button("⏸️ Suspendre", disabled=protege,
                         help="Bloque l'accès sans supprimer le compte"):
                _resultat(U.admin_valider(cible["id"], False))
        elif st.button("✅ Valider le compte"):
            _resultat(U.admin_valider(cible["id"], True))

    with st.container(border=True):
        st.markdown("**Rôle**")
        nouveau_role = st.radio("Rôle", ["user", "admin"], horizontal=True,
                                index=0 if cible["role"] == "user" else 1,
                                label_visibility="collapsed", disabled=protege)
        st.caption("⚠️ admin = accès au Bot Live (ordres en argent réel).")
        if st.button("Appliquer le rôle", disabled=protege or nouveau_role == cible["role"]):
            _resultat(U.admin_set_role(cible["id"], nouveau_role))

    with st.container(border=True):
        st.markdown("**Sessions / blocage**")
        b1, b2 = st.columns(2)
        if b1.button("Fermer ses sessions", width="stretch"):
            _resultat(U.admin_fermer_sessions(cible["id"]))
        if b2.button("Débloquer", width="stretch", disabled=cible["locked_until"] is None):
            _resultat(U.admin_debloquer(cible["id"]))

with col_b:
    with st.container(border=True):
        st.markdown("**Réinitialiser le mot de passe**")
        with st.form("form_reset", clear_on_submit=True):
            mdp = st.text_input("Nouveau mot de passe", type="password", disabled=protege)
            st.caption(U.MDP_REGLE_USER)
            if st.form_submit_button("Réinitialiser", disabled=protege):
                _resultat(U.admin_reset_mdp(cible["id"], mdp))

    with st.container(border=True):
        st.markdown("**Supprimer le compte**")
        confirme = st.checkbox(f"Je confirme la suppression de {cible['email']}", disabled=protege)
        if st.button("🗑️ Supprimer", type="primary", disabled=protege or not confirme):
            _resultat(U.admin_supprimer(cible["id"]))
