"""
start.py
Lance Streamlit ET le bot dans le même process Railway.
Redémarre automatiquement l'un ou l'autre si crash.
"""

import os
import sys
import json
import time
import subprocess


def get_bot_file() -> str:
    """Retourne le fichier bot à lancer selon bot_state.json."""
    try:
        with open("bot_state.json") as f:
            state = json.load(f)
        mode = state.get("mode", "local")
    except Exception:
        mode = "local"

    return {
        "local":   "bot_local.py",
        "testnet": "bot_testnet.py",
        "mainnet": "bot_mainnet.py",
    }.get(mode, "bot_local.py")


def start_services():
    port     = os.getenv("PORT", "8501") # Port automatuqment donné par Railway, ou 8501 par défaut
    bot_file = get_bot_file()

    print(f"[start.py] Lancement bot : {bot_file}")
    bot_process = subprocess.Popen([sys.executable, bot_file])

    print(f"[start.py] Lancement Streamlit sur port {port}")
    streamlit_process = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ])

    while True:
        # Redémarrer le bot si crash
        if bot_process.poll() is not None:
            bot_file = get_bot_file()   # re-lire le mode au cas où il a changé
            print(f"[start.py] ⚠️ Bot crashé — relancement {bot_file}...")
            bot_process = subprocess.Popen([sys.executable, bot_file])

        # Redémarrer Streamlit si crash
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
