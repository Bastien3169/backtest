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
    """Utilisateur connecté (ou None). À appeler en haut de app.py à chaque run.

    Gère aussi les écritures de cookie demandées par les callbacks de
    connexion / déconnexion : elles sont rejouées à chaque run tant que le
    navigateur ne les a pas appliquées (un run interrompu ne les perd donc pas).
    """
    _setup_une_fois()

    # Déconnexion demandée : effacer le cookie tant qu'il est encore là
    if st.session_state.get("_cookie_a_supprimer"):
        if cm.get(COOKIE):
            cm.delete(COOKIE, key="bt_del")
        else:
            st.session_state.pop("_cookie_a_supprimer", None)

    # Connexion réussie : poser le cookie tant que le navigateur ne l'a pas
    en_attente = st.session_state.get("_cookie_a_poser")
    if en_attente:
        jeton_c, expire_le = en_attente
        if cm.get(COOKIE) == jeton_c:
            st.session_state.pop("_cookie_a_poser", None)
        else:
            # Arguments identiques d'un run à l'autre (expire_le figé au login) :
            # le composant n'est pas re-déclenché en boucle.
            cm.set(COOKIE, jeton_c, key="bt_set", expires_at=expire_le,
                   secure=_HTTPS or None, same_site="strict")

    jeton = st.session_state.get("auth_token")
    if not jeton and not st.session_state.get("_cookie_a_supprimer"):
        jeton = cm.get(COOKIE)
    user = U.user_from_token(jeton)
    if user:
        st.session_state["auth_token"] = jeton
    else:
        st.session_state.pop("auth_token", None)
    st.session_state["user"] = user
    return user


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
# Les boutons passent par on_click : Streamlit exécute le callback dès réception
# du clic, AVANT le script. Sans ça, si le composant cookie relance la page au
# même moment (fréquent au premier chargement, surtout serveur à froid), le run
# qui portait le clic est interrompu et le clic est perdu : aucun message.
def _cb_login():
    ss = st.session_state
    email, mdp = ss.get("login_email", ""), ss.get("login_mdp", "")
    if not email or not mdp:
        ss["_msg_login"] = ("error", "❌ Remplis les deux champs.")
        return
    succes, msg, jeton = U.login(email, mdp, ss.get("login_rester", False))
    if succes:
        heures = U.SESSION_LONGUE_H if ss.get("login_rester") else U.SESSION_COURTE_H
        ss["auth_token"] = jeton
        ss["_cookie_a_poser"] = (jeton, datetime.now() + timedelta(hours=heures))
        ss.pop("_cookie_a_supprimer", None)
        ss.pop("_msg_login", None)
    else:
        ss["_msg_login"] = ("info" if msg == U.MSG_ATTENTE else "error", msg)


def _cb_register():
    ss = st.session_state
    if ss.get("reg_mdp") != ss.get("reg_mdp2"):
        ss["_msg_reg"] = ("error", "❌ Les deux mots de passe ne correspondent pas.")
        return
    succes, msg = U.register(ss.get("reg_email", ""), ss.get("reg_mdp", ""))
    ss["_msg_reg"] = ("success" if succes else "error", msg)


def _cb_logout():
    ss = st.session_state
    U.logout(ss.get("auth_token"))
    ss.pop("auth_token", None)
    ss.pop("_cookie_a_poser", None)
    ss["user"] = None
    ss["_cookie_a_supprimer"] = True
    ss.pop("_msg_login", None)
    ss.pop("_msg_reg", None)


def logout_button(cm: stx.CookieManager):
    """Bloc « compte » en bas de la barre latérale."""
    user = st.session_state.get("user")
    if not user:
        return
    with st.sidebar:
        st.divider()
        badge = "👑 admin" if user["role"] == "admin" else "👤"
        st.caption(f"{badge} {user['email']}")
        st.button("Se déconnecter", key="bt_logout", width="stretch", on_click=_cb_logout)


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
# Descriptions des pages, affichées sur la page de connexion (même ordre que le menu).
# Bot Live n'y figure volontairement pas : réservé à l'admin, inutile de l'annoncer.
PAGES_INFO = [
    ("📈", "Backtest",
     "Construis une ou plusieurs stratégies à partir d'indicateurs (RSI, moyennes mobiles, "
     "MACD, Bollinger) et simule-les sur un actif et une période. Rendement, drawdown et "
     "points d'achat/vente sont comparés côte à côte."),
    ("🔥", "Optimisation",
     "Teste d'un coup toutes les combinaisons de take profit et de stop loss sur plusieurs "
     "périodes, pour trouver des réglages qui tiennent partout et pas sur une seule période."),
    ("🧪", "Multi-actifs",
     "Fige une stratégie et lance-la sur plusieurs actifs et plusieurs périodes, pour vérifier "
     "qu'elle ne marche pas uniquement sur l'actif où tu l'as trouvée."),
    ("📊", "Screening",
     "Classe les cryptos selon leur volatilité, leur corrélation au BTC, leur bêta, leur volume "
     "et leur performance, pour choisir sur quoi travailler."),
]

# Adresse de contact affichée dans l'encart « bot ». Variable Railway, pas en dur :
# le dépôt a été public, pas la peine d'y remettre un email perso.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "").strip()


def _encart_bot():
    ecris_moi = "Écris-moi"
    if CONTACT_EMAIL:
        ecris_moi += f" ([{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL}?subject=Module%20bot))"
    with st.container(border=True):
        st.markdown("**🤖 Et ensuite ? Automatise ta stratégie**")
        st.markdown(
            "Tu as trouvé une stratégie qui tient la route ? Le module bot te permet de "
            "l'exécuter automatiquement sur ton propre compte, avec tes propres clés : "
            f"tu gardes le contrôle de A à Z. {ecris_moi} pour l'obtenir."
        )
        st.caption("Fonctionne aujourd'hui sur Hyperliquid. Aster et dYdX sont prévus prochainement.")


_ENTETE_HTML = """
<div style="text-align:center; border:2px solid rgba(128,128,128,.45); border-radius:14px;
            padding:22px 16px 18px; margin:0 auto 28px; max-width:620px;">
  <div style="font-size:2.6rem; font-weight:800; letter-spacing:.03em; line-height:1.2;
              text-decoration:underline; text-decoration-thickness:3px;
              text-underline-offset:10px;">📈 Backtesting</div>
  <div style="margin-top:16px; opacity:.75; font-size:1.05rem;">
    Teste tes stratégies sur l'historique d'un actif avant d'y mettre un euro.
  </div>
</div>
"""


def _afficher_message(cle: str):
    """Affiche le dernier message d'un formulaire.

    Écrit par les callbacks dans session_state, il survit aux relances de la
    page et reste affiché jusqu'au prochain envoi du formulaire.
    """
    m = st.session_state.get(cle)
    if m:
        genre, texte = m
        {"error": st.error, "success": st.success, "info": st.info}[genre](texte)


def login_page():
    st.markdown(_ENTETE_HTML, unsafe_allow_html=True)

    # Formulaire à gauche : sur téléphone les colonnes s'empilent, et la plupart
    # des visites viennent de gens qui ont déjà un compte.
    col_form, col_info = st.columns([1, 1.1], gap="large")

    with col_form:
        onglet_co, onglet_insc = st.tabs(["Connexion", "Inscription"])

        with onglet_co:
            with st.form("form_login"):
                st.text_input("Email", key="login_email", autocomplete="email")
                st.text_input("Mot de passe", type="password", key="login_mdp",
                              autocomplete="current-password")
                st.checkbox("Rester connecté 30 jours", key="login_rester")
                st.form_submit_button("Se connecter", width="stretch", type="primary",
                                      on_click=_cb_login)
            _afficher_message("_msg_login")

        with onglet_insc:
            with st.form("form_register"):
                st.text_input("Email", key="reg_email", autocomplete="email")
                st.text_input("Mot de passe", type="password", key="reg_mdp",
                              autocomplete="new-password")
                st.text_input("Confirmer le mot de passe", type="password", key="reg_mdp2",
                              autocomplete="new-password")
                st.caption(U.MDP_REGLE_USER)
                st.form_submit_button("Créer mon compte", width="stretch", type="primary",
                                      on_click=_cb_register)
            _afficher_message("_msg_reg")

    with col_info:
        st.subheader("Ce que tu trouveras dans l'app")
        for emoji, nom, texte in PAGES_INFO:
            st.markdown(f"**{emoji} {nom}** : {texte}")
        _encart_bot()
