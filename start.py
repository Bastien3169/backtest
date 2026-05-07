"""
start.py
Lance Streamlit + les bots configurés dans bots_config.json.
La liste des bots actifs est gérée depuis Streamlit (page BotLive).
Redémarre automatiquement si crash.

Sur Railway : Start Command = python start.py
"""

import os
import sys
import json
import time
import subprocess

# Force tout le monde à travailler depuis le même dossier
# = dossier où se trouve start.py
# Sans ça, bot_local et Streamlit peuvent avoir des dossiers courants différents
# et ne pas lire le même bot_state.json
os.chdir(os.path.dirname(os.path.abspath(__file__)))

BOTS_CONFIG_FILE = os.path.join(os.getenv("DATA_DIR", "."), "bots_config.json")

DEFAULT_BOTS = [
    {"bot_file": "bot_local.py",   "config": "bot_state_local_long.json",    "active": True},
    # Décommenter quand tu as les clés API Binance testnet
    # {"bot_file": "bot_local.py",   "config": "bot_state_local_short.json",   "active": True},
    # {"bot_file": "bot_testnet.py", "config": "bot_state_testnet_long.json",  "active": False},
    # {"bot_file": "bot_testnet.py", "config": "bot_state_testnet_short.json", "active": False},
    # Décommenter seulement quand tu es prêt pour le vrai argent
    # {"bot_file": "bot_mainnet.py", "config": "bot_state_mainnet_long.json",  "active": False},
    # {"bot_file": "bot_mainnet.py", "config": "bot_state_mainnet_short.json", "active": False},
]


def read_bots_config() -> list:
    """Lit la liste des bots depuis bots_config.json."""
    try:
        with open(BOTS_CONFIG_FILE) as f:
            return json.load(f).get("bots", DEFAULT_BOTS)
    except Exception:
        return DEFAULT_BOTS


def write_bots_config(bots: list):
    """Écrit la liste des bots dans bots_config.json."""
    with open(BOTS_CONFIG_FILE, "w") as f:
        json.dump({"bots": bots}, f, indent=2)


def init_files():
    """Crée les fichiers manquants au démarrage dans DATA_DIR."""
    data_dir = os.getenv("DATA_DIR", os.path.abspath("."))
    os.makedirs(data_dir, exist_ok=True)   # crée /data si inexistant

    # Créer bots_config.json si absent
    global BOTS_CONFIG_FILE
    BOTS_CONFIG_FILE = os.path.join(data_dir, "bots_config.json")
    if not os.path.exists(BOTS_CONFIG_FILE):
        write_bots_config(DEFAULT_BOTS)
        print(f"[start.py] bots_config.json créé dans {data_dir}")

    # Créer les fichiers JSON d'état manquants
    default_state = {
        "status": "stopped", "mode": "local", "position": None,
        "balance": 1000.0, "balance_init": 1000.0, "trades": [],
        "log": [], "strategy": {}, "last_check": None,
        "last_price": None, "pnl_session": 0.0,
    }
    for bot in DEFAULT_BOTS:
        path = os.path.join(data_dir, bot["config"])
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump(default_state, f, indent=2)
            print(f"[start.py] {bot['config']} créé dans {data_dir}")


def start_services():
    port = os.getenv("PORT", "8501")

    init_files()

    # Lancer Streamlit
    print(f"[start.py] Lancement Streamlit sur port {port}")
    streamlit_process = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ])

    # Dictionnaire des process actifs {config: process}
    active_processes = {}

    while True:
        # Relire la config à chaque cycle
        bots = read_bots_config()

        # Arrêter les bots devenus inactifs
        for config, proc in list(active_processes.items()):
            bot_cfg = next((b for b in bots if b["config"] == config), None)
            if not bot_cfg or not bot_cfg.get("active"):
                print(f"[start.py] Arrêt {config}...")
                proc.terminate()
                del active_processes[config]

        # Démarrer les nouveaux bots actifs
        for bot_cfg in bots:
            if not bot_cfg.get("active"):
                continue
            config     = bot_cfg["config"]
            data_dir   = os.getenv("DATA_DIR", os.path.abspath("."))
            config_path = os.path.join(data_dir, config)   # chemin complet
            if config not in active_processes or active_processes[config].poll() is not None:
                if config in active_processes:
                    print(f"[start.py] ⚠️ {config} crashé — relancement...")
                else:
                    print(f"[start.py] Lancement {bot_cfg['bot_file']} --config {config_path}")
                active_processes[config] = subprocess.Popen([
                    sys.executable, bot_cfg["bot_file"],
                    "--config", config_path   # chemin complet
                ])

        # Vérifier Streamlit
        if streamlit_process.poll() is not None:
            print("[start.py] ⚠️ Streamlit crashé — relancement...")
            streamlit_process = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", "app.py",
                "--server.port", port,
                "--server.address", "0.0.0.0",
                "--server.headless", "true",
            ])

        time.sleep(10)


if __name__ == "__main__":
    start_services()
