"""
src/utils/screening_cache.py
Dernier chargement du Screening, gardé CÔTÉ SERVEUR (une seule copie pour tout
le process Streamlit), et non plus dans la session du navigateur.

Pourquoi : une session Streamlit meurt au moindre F5, nouvel onglet, veille du
Mac ou coupure réseau — et avec elle un chargement Yahoo de 2-5 min. Ici, le
tableau survit à tout ça ; seul un redémarrage du serveur (redéploiement) le
perd.

Effet de bord voulu : le tableau est partagé entre tous les utilisateurs (ce
sont des données de marché, identiques pour tous), et l'historique d'OI
(~300 000 lignes) n'est plus copié dans chaque session ouverte.
"""

import threading
from datetime import datetime, timezone

_verrou = threading.Lock()
_etat = {
    "df": None,         # tableau Yahoo (load_screening_data)
    "live": None,       # photo Hyperliquid instantanée
    "hist": None,       # historique des photos (load_history)
    "ts_yahoo": None,   # heure UTC du dernier chargement Yahoo
    "ts_hl": None,      # heure UTC de la dernière lecture Hyperliquid
}


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def lire() -> dict:
    with _verrou:
        return dict(_etat)


def poser_yahoo(df) -> None:
    with _verrou:
        _etat["df"] = df
        _etat["ts_yahoo"] = _maintenant()


def poser_hl(live, hist) -> None:
    with _verrou:
        _etat["live"] = live
        _etat["hist"] = hist
        _etat["ts_hl"] = _maintenant()
