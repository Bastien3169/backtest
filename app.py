"""
app.py — point d'entrée Streamlit (routeur).
Lancement : streamlit run app.py   (start.py le fait déjà sur Railway)

1. Lit le cookie de session et identifie l'utilisateur.
2. Construit la liste des pages SELON LE RÔLE avec st.navigation :
   - non connecté ou compte non validé → uniquement la page de connexion / inscription
   - user         → Accueil (page d'arrivée), Backtest, Optimisation, Multi-actifs,
                    Screening, Mon compte
   - admin        → + Bot Live + Admin
   Une page absente de la liste n'existe pas pour cet utilisateur : ni lien dans
   le menu, ni accès en tapant son URL.

Avec st.navigation, le dossier pages/ n'est plus découvert automatiquement :
toute nouvelle page doit être ajoutée ci-dessous.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

from src.auth.users import nb_en_attente
from src.auth.ui import (account_page, cookie_manager, current_user, home_page, login_page,
                         logout_button)

st.set_page_config(
    page_title="BacktestBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Enregistreur des photos Hyperliquid (radar du Screening).
# Sur Railway, start.py le lance dans son propre process dès le démarrage du
# serveur et pose RADAR_PAR_START=1 : on ne le relance surtout pas ici (deux
# enregistreurs = photos en double et journal noté deux fois).
# En local (`streamlit run app.py` sans start.py), on garde l'ancien thread,
# démarré UNE fois par process grâce à cache_resource.
@st.cache_resource(show_spinner=False)
def _enregistreur_hl():
    from src.utils.hl_snapshots import start_recorder
    return start_recorder()


try:
    if os.getenv("RADAR_PAR_START") != "1":
        _enregistreur_hl()
except Exception as _e:          # le radar ne doit jamais empêcher l'app de démarrer
    print(f"[app] enregistreur Hyperliquid non démarré : {_e}")

cm = cookie_manager()
user = current_user(cm)

if user is None:
    pg = st.navigation([st.Page(login_page, title="Connexion", icon="🔐", url_path="login")],
                       position="hidden")
else:
    pages = {
        "": [
            st.Page(home_page, title="Accueil", icon="🏠", url_path="accueil", default=True),
        ],
        "Analyse": [
            st.Page("pages/0_📈_Backtest.py", title="Backtest", icon="📈"),
            st.Page("pages/1_🔥_Optimisation.py", title="Optimisation", icon="🔥"),
            st.Page("pages/2_🧪_Multi-actifs.py", title="Multi-actifs", icon="🧪"),
            st.Page("pages/3_📊_Screening.py", title="Screening", icon="📊"),
        ],
        "Compte": [
            st.Page(account_page, title="Mon compte", icon="👤", url_path="compte"),
        ],
    }
    if user["role"] == "admin":
        attente = nb_en_attente()
        titre_admin = f"Utilisateurs ({attente} en attente)" if attente else "Utilisateurs"
        pages["Admin"] = [
            st.Page("pages/4_📈_BotLive.py", title="Bot Live", icon="🤖"),
            st.Page("pages/5_👑_Admin.py", title=titre_admin, icon="👑"),
        ]
    pg = st.navigation(pages)
    logout_button(cm)

# Streamlit efface l'état d'un widget dès qu'une page s'affiche sans lui : les
# filtres et l'entonnoir du Screening revenaient à zéro à chaque changement de
# page. Les réécrire ici, sur les AUTRES pages, les transforme en simples
# valeurs de session qui survivent ; de retour sur Screening, chaque widget les
# reprend (ses clés commencent toutes par « scr_ »).
if pg.title != "Screening":
    for _k in [k for k in st.session_state if str(k).startswith("scr_")]:
        st.session_state[_k] = st.session_state[_k]

pg.run()
