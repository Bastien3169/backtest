"""
start.py — version mémoire optimisée
====================================

À placer à la RACINE du projet (à côté de app.py), en remplacement de start.py.

Ce qui change par rapport à la version précédente
-------------------------------------------------
Avant : 3 bots lancés via subprocess.Popen([sys.executable, "bot_mainnet.py"]).
        → 3 interpréteurs Python complets, chacun rechargeant sa propre copie
          de pandas, numpy, eth_account et du SDK Hyperliquid.
        → ~140 Mo par bot, soit ~420 Mo tenus 24h/24.

Après : les bibliothèques lourdes sont importées UNE SEULE FOIS dans le process
        parent, puis les bots sont lancés par fork (multiprocessing).
        Sous Linux, le fork partage les pages mémoire du parent en
        copy-on-write : les enfants ne recopient que ce qu'ils modifient.
        → ~150-200 Mo au total au lieu de ~420 Mo.

Ce qui NE change PAS
--------------------
- bot_mainnet.py n'est pas modifié d'une ligne.
- Chaque bot reste dans SON PROPRE process : son bot_state_*.json, ses globales
  (BOT_PREFIX, _hl_side), son crash isolé des autres. Un bot qui tombe ne
  touche pas les deux autres, et il est relancé automatiquement comme avant.
- Streamlit reste un subprocess séparé (il lui faut son propre interpréteur).

Ajouts de robustesse
--------------------
- Arrêt propre sur SIGTERM (c'est le signal que Railway envoie à chaque
  redéploiement) : les bots sont terminés proprement au lieu d'être orphelins.
- Backoff sur les relances : un bot qui crashe en boucle n'est plus relancé
  toutes les 10 s à l'infini.
- Rapport mémoire dans les logs toutes les 10 min, pour vérifier le gain réel.

Sur Railway : Start Command = python start.py
"""

import os
import sys
import gc
import json
import time
import signal
import importlib
import subprocess
import multiprocessing as mp

# Force tout le monde à travailler depuis le même dossier
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# Garde-fou : ce fichier est prévu pour la racine du projet, pas pour _Claude/
if os.path.basename(BASE_DIR) == "_Claude":
    sys.exit(
        "[start.py] ❌ Ce fichier doit être déplacé à la racine du projet "
        "(à côté de app.py), pas exécuté depuis _Claude/."
    )

DEFAULT_BOTS = [
    # ── Local (simulation) ────────────────────────────────────────────────
    # {"bot_file": "bot_local.py",   "config": "bot_state_local_long.json",    "active": True},
    # {"bot_file": "bot_local.py",   "config": "bot_state_local_short.json",   "active": True},

    # ── Testnet Binance ───────────────────────────────────────────────────
    # {"bot_file": "bot_testnet.py", "config": "bot_state_testnet_long.json",  "active": True},
    # {"bot_file": "bot_testnet.py", "config": "bot_state_testnet_short.json", "active": True},

    # ── Mainnet Hyperliquid — VRAI ARGENT ─────────────────────────────────
    {"bot_file": "bot_mainnet.py", "config": "bot_state_mainnet_long.json",  "active": True},
    {"bot_file": "bot_mainnet.py", "config": "bot_state_mainnet_short.json", "active": True},
    {"bot_file": "bot_mainnet.py", "config": "bot_state_mainnet_free.json",  "active": True},
]

POLL_SEC          = 10     # cadence de la boucle de surveillance
MEM_REPORT_SEC    = 600    # rapport mémoire toutes les 10 min
BACKOFF_MAX_SEC   = 900    # 15 min max entre deux relances d'un bot qui crashe


# ---------------------------------------------------------------------------
# Préchargement des bibliothèques lourdes dans le PARENT
# ---------------------------------------------------------------------------
def preload_heavy_modules():
    """
    Importe une seule fois tout ce qui pèse. Les enfants forkés hériteront de
    ces modules déjà chargés en mémoire, au lieu de les réimporter chacun.

    On importe volontairement les modules internes du bot (indicators,
    backtest, hyperliquid_client) : ce sont eux qui tirent pandas, numpy,
    eth_account et le SDK Hyperliquid.

    On N'IMPORTE PAS bot_mainnet ici : ce module lit sys.argv au moment de
    l'import pour déterminer sa config, son préfixe de log et son side.
    Il doit donc être importé DANS chaque enfant, après le fork.
    """
    print("[start.py] Préchargement des bibliothèques lourdes...")
    t0 = time.time()

    import pandas            # noqa: F401
    import numpy             # noqa: F401
    import requests          # noqa: F401

    from src.utils import bot_state                  # noqa: F401
    from src.utils import hyperliquid_client         # noqa: F401
    from src.controllers import indicators           # noqa: F401
    from src.controllers import backtest             # noqa: F401

    # gc.freeze() sort les objets déjà alloués du périmètre du ramasse-miettes.
    # Sans ça, le GC des enfants viendrait toucher les en-têtes des objets
    # hérités, ce qui déclencherait la copie des pages et annulerait une bonne
    # partie du partage copy-on-write.
    gc.collect()
    gc.freeze()

    print(f"[start.py] Préchargement terminé en {time.time() - t0:.1f}s "
          f"({_fmt_mb(_process_rss())} résidents dans le parent)")


# ---------------------------------------------------------------------------
# Point d'entrée exécuté DANS chaque process enfant
# ---------------------------------------------------------------------------
def bot_entrypoint(bot_file: str, config_path: str):
    """
    Tourne dans l'enfant forké. Reproduit exactement ce que faisait
    `python bot_mainnet.py --config <path>` : bot_mainnet lit sys.argv à
    l'import, on le positionne donc avant d'importer le module.
    """
    # L'enfant ne doit pas hériter du gestionnaire SIGTERM du parent :
    # on remet le comportement par défaut pour que terminate() fonctionne.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sys.argv = [bot_file, "--config", config_path]
    module_name = os.path.splitext(os.path.basename(bot_file))[0]

    mod = importlib.import_module(module_name)
    mod.run()


# ---------------------------------------------------------------------------
# Enregistreur du radar (photos Hyperliquid + journal de nuit + e-mail)
# ---------------------------------------------------------------------------
def radar_entrypoint():
    """Tourne dans un enfant forké, comme un bot : démarre avec le serveur,
    sans attendre qu'une page de l'app soit ouverte. Imports faits APRÈS le
    fork pour que l'enfant ait sa propre connexion à la base."""
    from src.utils.hl_snapshots import boucle_enregistreur
    boucle_enregistreur()


def launch_radar():
    p = mp.Process(target=radar_entrypoint, name="radar", daemon=False)
    p.start()
    return p


# ---------------------------------------------------------------------------
# Mesure mémoire — pour vérifier le gain dans les logs Railway
# ---------------------------------------------------------------------------
def _process_rss(pid: str = "self") -> int:
    """RSS d'un process en octets (Linux). 0 si indisponible (macOS)."""
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return 0


def _container_memory() -> int:
    """
    Mémoire réellement facturée par Railway : celle du conteneur entier
    (cgroup v2), qui compte les pages partagées UNE SEULE FOIS.
    C'est ce chiffre-là qu'il faut comparer avant/après, pas la somme des RSS.
    """
    for path in ("/sys/fs/cgroup/memory.current",
                 "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            with open(path) as f:
                return int(f.read().strip())
        except Exception:
            continue
    return 0


def _fmt_mb(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} Mo" if n else "n/a"


def report_memory(active, streamlit_proc, radar_proc=None):
    total = _container_memory()
    detail = []
    for config, proc in active.items():
        tag = config.replace("bot_state_", "").replace(".json", "")
        detail.append(f"{tag}={_fmt_mb(_process_rss(proc.pid))}")
    if streamlit_proc and streamlit_proc.poll() is None:
        detail.append(f"streamlit={_fmt_mb(_process_rss(streamlit_proc.pid))}")
    if radar_proc and radar_proc.is_alive():
        detail.append(f"radar={_fmt_mb(_process_rss(radar_proc.pid))}")

    print(f"[start.py] 📊 Conteneur : {_fmt_mb(total)} facturés "
          f"| parent={_fmt_mb(_process_rss())} | " + " ".join(detail))
    print("[start.py]    (les RSS par process se recouvrent : les pages "
          "partagées par fork y sont comptées plusieurs fois)")


# ---------------------------------------------------------------------------
# Fichiers d'état
# ---------------------------------------------------------------------------
def init_files():
    """Crée les fichiers JSON d'état manquants au démarrage."""
    data_dir = os.getenv("DATA_DIR", os.path.abspath("."))
    os.makedirs(data_dir, exist_ok=True)

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


def launch_streamlit():
    port = os.getenv("PORT", "8501")
    print(f"[start.py] Lancement Streamlit sur port {port}")
    return subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ])


# ---------------------------------------------------------------------------
# Boucle de supervision
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_sigterm(signum, frame):
    global _shutdown
    print(f"[start.py] 🛑 Signal {signum} reçu — arrêt propre en cours...")
    _shutdown = True


def start_services():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    init_files()
    preload_heavy_modules()

    # Dit à app.py (lancé par Streamlit, qui hérite de l'environnement) de ne
    # PAS démarrer son propre enregistreur : c'est start.py qui s'en charge.
    os.environ["RADAR_PAR_START"] = "1"
    streamlit_process = launch_streamlit()
    radar_process     = launch_radar()
    radar_retry       = 0.0     # timestamp avant lequel on ne relance pas le radar

    active = {}                 # {config: mp.Process}
    failures = {}               # {config: nb de crashs consécutifs}
    next_retry = {}             # {config: timestamp avant lequel on ne relance pas}
    started_at = {}             # {config: timestamp du dernier démarrage}
    last_mem_report = 0.0

    while not _shutdown:
        data_dir = os.getenv("DATA_DIR", os.path.abspath("."))

        # ── Arrêter les bots devenus inactifs ─────────────────────────────
        for config, proc in list(active.items()):
            bot_cfg = next((b for b in DEFAULT_BOTS if b["config"] == config), None)
            if not bot_cfg or not bot_cfg.get("active"):
                print(f"[start.py] Arrêt {config}...")
                proc.terminate()
                proc.join(timeout=10)
                del active[config]

        # ── Démarrer / relancer les bots actifs ───────────────────────────
        for bot_cfg in DEFAULT_BOTS:
            if not bot_cfg.get("active"):
                continue

            config      = bot_cfg["config"]
            config_path = os.path.join(data_dir, config)
            proc        = active.get(config)
            now         = time.time()

            if proc is not None and proc.is_alive():
                continue

            if proc is not None:
                # Le bot était lancé et il est mort. On ne compte le crash
                # qu'UNE fois, au moment où on le constate.
                if config not in next_retry:
                    proc.join(timeout=1)
                    # Un bot qui a tourné plus d'une heure repart d'un
                    # compteur neuf : un incident isolé ne doit pas laisser
                    # un backoff de 15 min derrière lui pendant des semaines.
                    if now - started_at.get(config, now) > 3600:
                        failures[config] = 1
                    else:
                        failures[config] = failures.get(config, 0) + 1
                    wait = min(60 * (2 ** (failures[config] - 1)), BACKOFF_MAX_SEC)
                    next_retry[config] = now + wait
                    print(f"[start.py] ⚠️ {config} arrêté (code {proc.exitcode}, "
                          f"crash n°{failures[config]}) — relance dans {wait}s")
                if now < next_retry[config]:
                    continue
                del next_retry[config]
                print(f"[start.py] ↻ Relance {bot_cfg['bot_file']} --config {config_path}")
            else:
                print(f"[start.py] Lancement {bot_cfg['bot_file']} --config {config_path}")

            p = mp.Process(
                target=bot_entrypoint,
                args=(bot_cfg["bot_file"], config_path),
                name=config,
                daemon=False,
            )
            p.start()
            active[config]     = p
            started_at[config] = time.time()

        # ── Surveiller Streamlit ──────────────────────────────────────────
        if streamlit_process.poll() is not None:
            print("[start.py] ⚠️ Streamlit crashé — relancement...")
            streamlit_process = launch_streamlit()

        # ── Surveiller le radar ───────────────────────────────────────────
        if not radar_process.is_alive():
            if not radar_retry:
                print(f"[start.py] ⚠️ radar arrêté (code {radar_process.exitcode}) "
                      "— relance dans 60s")
                radar_retry = time.time() + 60
            elif time.time() >= radar_retry:
                radar_process.join(timeout=1)
                radar_process = launch_radar()
                radar_retry   = 0.0

        # ── Rapport mémoire ───────────────────────────────────────────────
        if time.time() - last_mem_report > MEM_REPORT_SEC:
            report_memory(active, streamlit_process, radar_process)
            last_mem_report = time.time()

        time.sleep(POLL_SEC)

    # ── Arrêt propre ──────────────────────────────────────────────────────
    print("[start.py] Arrêt des bots...")
    for config, proc in active.items():
        if proc.is_alive():
            proc.terminate()
    for config, proc in active.items():
        proc.join(timeout=15)
        if proc.is_alive():
            print(f"[start.py] {config} ne répond pas — kill")
            proc.kill()

    if radar_process.is_alive():
        radar_process.terminate()
        radar_process.join(timeout=10)

    if streamlit_process.poll() is None:
        streamlit_process.terminate()
        try:
            streamlit_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            streamlit_process.kill()

    print("[start.py] ✅ Arrêt terminé")


if __name__ == "__main__":
    # Le partage mémoire par copy-on-write n'existe qu'avec la méthode "fork"
    # (Linux, donc Railway). Sur macOS la valeur par défaut est "spawn" :
    # le code fonctionne à l'identique, mais sans gain mémoire — c'est normal
    # en test local.
    if sys.platform.startswith("linux"):
        try:
            mp.set_start_method("fork")
        except RuntimeError:
            pass
    print(f"[start.py] Méthode de démarrage des process : {mp.get_start_method()}")

    start_services()
