"""
bot_state.py
État partagé entre les bots et Streamlit via un fichier JSON.
Simple et lisible — pas besoin de SQLite pour un bot solo.
"""

import json
import os
from datetime import datetime

# os.path.abspath(".") = transforme "." (dossier relatif actuel) en chemin absolu complet
# ex: "." devient "/app/code/" — toujours le même chemin peu importe le contexte
#
# Sans abspath, "." peut pointer vers des endroits différents selon comment
# le process est lancé — ce qui ferait que bot_local.py et Streamlit
# ne liraient/écriraient pas dans le même bot_state.json
#
# DATA_DIR = variable d'environnement Railway pour pointer vers le volume persistant
# Si DATA_DIR n'existe pas (en local sur ton Mac) → on utilise le dossier courant
_ROOT      = os.getenv("DATA_DIR", os.path.abspath("."))
STATE_FILE = os.path.join(_ROOT, "bot_state.json")

DEFAULT_STATE = {
    "status":      "stopped",   # "stopped" | "running"
    "mode":        "local",     # "local" | "testnet" | "mainnet"
    "position":    None,        # dict ou None
    "balance":     1000.0,      # capital disponible (fictif en local)
    "balance_init": 1000.0,     # capital initial pour calculer le PnL total
    "trades":      [],          # historique des trades fermés
    "log":         [],          # derniers événements (max 100)
    "strategy":    {},          # config de la stratégie active
    "last_check":  None,        # ISO timestamp du dernier check
    "last_price":  None,
    "pnl_session": 0.0,
}


def get_state() -> dict:
    """Lit l'état depuis le JSON. Retourne l'état par défaut si absent."""
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        # Compléter les clés manquantes (si le fichier est ancien)
        for k, v in DEFAULT_STATE.items():
            if k not in state:
                state[k] = v
        return state
    except Exception:
        return DEFAULT_STATE.copy()


def save_state(state: dict):
    """Écrit l'état dans le JSON."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log(message: str, max_logs: int = 100):
    """Ajoute un message au log et sauvegarde."""
    state = get_state()
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {message}"
    print(entry)
    state["log"].append(entry)
    state["log"] = state["log"][-max_logs:]
    save_state(state)


def reset():
    """Remet à zéro — garde la config strategy."""
    state    = get_state()
    strategy = state.get("strategy", {})
    mode     = state.get("mode", "local")
    bal_init = state.get("balance_init", 1000.0)
    new      = DEFAULT_STATE.copy()
    new["strategy"]     = strategy
    new["mode"]         = mode
    new["balance"]      = bal_init
    new["balance_init"] = bal_init
    save_state(new)
