"""
src/auth/ui.py
Partie Streamlit de l'authentification : cookie, page de connexion/inscription,
bouton de déconnexion, garde-fou admin.

Le jeton de session vit à deux endroits :
- st.session_state["auth_token"] : effet immédiat dans l'onglet courant ;
- un cookie navigateur "bt_session" : pour survivre à un F5 / une réouverture.
Le cookie ne contient qu'un jeton aléatoire, vérifié en base à chaque run :
impossible à forger (contrairement à l'ancien cookie bot_auth="ok").
"""

import os
import time
from datetime import datetime, timedelta

import extra_streamlit_components as stx
import streamlit as st

from src.auth import users as U

COOKIE = "bt_session"
_HTTPS = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PUBLIC_DOMAIN"))


@st.cache_resource(show_spinner=False)
def _setup_une_fois():
    """Création des tables + synchro du compte admin : une fois par process."""
    U.setup()
    return True


def cookie_manager() -> stx.CookieManager:
    """À appeler UNE fois par run, en haut de app.py.

    Le composant doit être rendu à CHAQUE run (sinon son iframe disparaît et
    les écritures de cookie ne partent jamais) → jamais de cache ici. On range
    juste la référence du run courant pour que login_page() la retrouve.
    """
    cm = stx.CookieManager(key="bt_cookie_manager")
    st.session_state["_cookie_manager"] = cm
    return cm


def current_user(cm: stx.CookieManager) -> dict | None:
    """Utilisateur connecté (ou None). À appeler en haut de app.py à chaque run."""
    _setup_une_fois()

    jeton = st.session_state.get("auth_token") or cm.get(COOKIE)
    user = U.user_from_token(jeton)
    if user:
        st.session_state["auth_token"] = jeton
    else:
        st.session_state.pop("auth_token", None)
    st.session_state["user"] = user
    return user


def _poser_cookie(cm, jeton: str, rester_connecte: bool):
    heures = U.SESSION_LONGUE_H if rester_connecte else U.SESSION_COURTE_H
    cm.set(COOKIE, jeton, key="bt_set",
           expires_at=datetime.now() + timedelta(hours=heures),
           secure=_HTTPS or None, same_site="strict")


def logout_button(cm: stx.CookieManager):
    """Bloc « compte » en bas de la barre latérale."""
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        st.divider()
        badge = "👑 admin" if user["role"] == "admin" else "👤"
        st.caption(f"{badge} {user['email']}")
        if st.button("Se déconnecter", key="bt_logout", width="stretch"):
            U.logout(st.session_state.get("auth_token"))
            st.session_state.pop("auth_token", None)
            st.session_state["user"] = None
            if cm.get(COOKIE):
                cm.delete(COOKIE, key="bt_del")
            time.sleep(0.5)          # laisser le navigateur effacer le cookie
            st.rerun()


def require_admin():
    """Garde-fou à mettre en haut des pages sensibles (défense en profondeur :
    app.py ne les route déjà pas pour un non-admin)."""
    user = st.session_state.get("user")
    if not user or user.get("role") != "admin":
        st.error("⛔ Accès réservé à l'administrateur.")
        st.stop()


# ---------------------------------------------------------------------------
# Page « Mon compte »
# ---------------------------------------------------------------------------
def account_page():
    user = st.session_state.get("user")
    st.title("👤 Mon compte")
    st.write(f"**Email :** {user['email']}  \n**Rôle :** {user['role']}")

    if user["role"] == "admin":
        st.info("Le mot de passe admin se change dans la variable ADMIN_PASSWORD sur Railway "
                "(puis redéploiement).")
        return

    st.subheader("Changer mon mot de passe")
    with st.form("form_mdp", clear_on_submit=True):
        ancien = st.text_input("Mot de passe actuel", type="password")
        nouveau = st.text_input("Nouveau mot de passe", type="password")
        nouveau2 = st.text_input("Confirmer", type="password")
        st.caption(U.MDP_REGLE_USER)
        ok = st.form_submit_button("Modifier")
    if ok:
        if nouveau != nouveau2:
            st.error("❌ Les deux mots de passe ne correspondent pas.")
        else:
            succes, msg = U.changer_mon_mdp(user["id"], ancien, nouveau, est_admin=False)
            (st.success if succes else st.error)(msg)


# ---------------------------------------------------------------------------
# Page de connexion / inscription (seule page visible sans être connecté)
# ---------------------------------------------------------------------------
def login_page():
    cm = st.session_state["_cookie_manager"]

    st.title("🔐 BacktestBot")
    onglet_co, onglet_insc = st.tabs(["Connexion", "Inscription"])

    with onglet_co:
        with st.form("form_login"):
            email = st.text_input("Email", autocomplete="email")
            mdp = st.text_input("Mot de passe", type="password", autocomplete="current-password")
            rester = st.checkbox("Rester connecté 30 jours", value=False)
            ok = st.form_submit_button("Se connecter", width="stretch")
        if ok:
            if not email or not mdp:
                st.error("❌ Remplis les deux champs.")
            else:
                succes, msg, jeton = U.login(email, mdp, rester)
                if succes:
                    st.session_state["auth_token"] = jeton
                    _poser_cookie(cm, jeton, rester)
                    st.success(msg)
                    # Ne pas relancer tout de suite : laisser au composant le temps
                    # d'écrire le cookie (sinon il est perdu au premier F5).
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)

    with onglet_insc:
        with st.form("form_register", clear_on_submit=False):
            email_i = st.text_input("Email", key="reg_email", autocomplete="email")
            mdp_i = st.text_input("Mot de passe", type="password", key="reg_mdp",
                                  autocomplete="new-password")
            mdp_i2 = st.text_input("Confirmer le mot de passe", type="password", key="reg_mdp2",
                                   autocomplete="new-password")
            st.caption(U.MDP_REGLE_USER)
            ok_i = st.form_submit_button("Créer mon compte", width="stretch")
        if ok_i:
            if mdp_i != mdp_i2:
                st.error("❌ Les deux mots de passe ne correspondent pas.")
            else:
                succes, msg = U.register(email_i, mdp_i)
                (st.success if succes else st.error)(msg)
