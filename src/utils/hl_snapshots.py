"""
src/utils/hl_snapshots.py
Historique du contexte Hyperliquid (open interest, prix, funding, volume).

Pourquoi ce module existe
-------------------------
L'API Hyperliquid ne donne QUE la valeur instantanée de l'open interest : aucun
endpoint ne renvoie « l'OI d'il y a 24 h ». Pour mesurer une VARIATION d'OI, il
faut donc photographier l'univers à intervalle régulier et garder ces photos.

Où sont stockées les photos
---------------------------
Dans la MÊME base que les comptes utilisateurs (src/auth/db.py) :
    - Railway : PostgreSQL (DATABASE_URL)
    - local   : SQLite (DATA_DIR/users.db)
Pas de JSON : le disque d'un conteneur Railway est effacé à chaque
redéploiement (sauf volume monté), un JSON réécrit en entier toutes les
heures grossit sans fin, et deux écritures simultanées le corrompent.

Volume : ~200 actifs × 24 photos/jour × 30 jours ≈ 145 000 lignes, une
vingtaine de Mo. Les photos de plus de RETENTION_JOURS sont purgées.

Qui prend les photos
--------------------
start_recorder() lance un thread en arrière-plan dans le process Streamlit
(appelé depuis app.py, une seule fois par process grâce à st.cache_resource).
La page Screening prend aussi une photo à chaque actualisation si la
dernière date de plus de INTERVALLE_MIN : l'historique se remplit même si
le thread a été interrompu.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from sqlalchemy import (
    Column, DateTime, Float, MetaData, String, Table, delete, func, insert, select,
)

from src.auth.db import engine

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

INTERVALLE_MIN  = 60     # une photo par heure : le bot décide à la bougie
                         # journalière, une finesse de 30 min n'apporterait rien
RETENTION_JOURS = 30     # le z-score regarde 14 jours : 30 laisse de la marge

_metadata = MetaData()

hl_snapshots = Table(
    "hl_snapshots", _metadata,
    Column("ts",          DateTime,   primary_key=True),   # UTC, sans fuseau
    Column("coin",        String(40), primary_key=True),   # nom Hyperliquid (hl_name)
    # OI en UNITÉS DE L'ACTIF (nombre de BTC, de SOL...), pas en dollars :
    # en dollars, l'OI monterait mécaniquement avec le prix sans qu'aucune
    # position nouvelle ne soit ouverte.
    Column("oi",          Float),
    Column("mark_px",     Float),
    Column("funding",     Float),    # taux HORAIRE
    Column("day_ntl_vlm", Float),    # volume $ glissant sur 24 h
    Column("premium",     Float),
)

_table_ok = False


def _init_table() -> None:
    global _table_ok
    if not _table_ok:
        _metadata.create_all(engine)
        _table_ok = True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Lecture de l'état instantané
# ---------------------------------------------------------------------------

def _f(source, cle):
    try:
        return float(source.get(cle))
    except (TypeError, ValueError, AttributeError):
        return None


def fetch_hl_live() -> pd.DataFrame:
    """Photo instantanée de tout l'univers des perps Hyperliquid.

    Deux appels : metaAndAssetCtxs (tout le contexte) et perpsAtOpenInterestCap
    (actifs dont l'OI a atteint le plafond fixé par HL).

    Retourne un DataFrame indexé par nom HL, ou un DataFrame vide si HL ne
    répond pas. Jamais d'exception : le screening doit rester utilisable.
    """
    try:
        resp = requests.post(HL_INFO_URL, json={"type": "metaAndAssetCtxs"}, timeout=15)
        resp.raise_for_status()
        meta, contextes = resp.json()[:2]
        univers = meta.get("universe", [])
    except Exception as e:
        print(f"[radar] metaAndAssetCtxs indisponible : {e}")
        return pd.DataFrame()

    # Le plafond est un bonus : s'il échoue, le reste du radar fonctionne.
    try:
        r = requests.post(HL_INFO_URL, json={"type": "perpsAtOpenInterestCap"}, timeout=10)
        r.raise_for_status()
        au_plafond = set(r.json() or [])
        plafond_ok = True
    except Exception as e:
        print(f"[radar] perpsAtOpenInterestCap indisponible : {e}")
        au_plafond, plafond_ok = set(), False

    lignes = []
    for actif, ctx in zip(univers, contextes):
        nom = actif.get("name")
        if not nom or not isinstance(ctx, dict) or actif.get("isDelisted"):
            continue
        mark = _f(ctx, "markPx") or _f(ctx, "oraclePx")
        prev = _f(ctx, "prevDayPx")
        lignes.append({
            "coin":        nom,
            "oi":          _f(ctx, "openInterest"),
            "mark_px":     mark,
            "prev_day_px": prev,
            "funding":     _f(ctx, "funding"),
            "day_ntl_vlm": _f(ctx, "dayNtlVlm"),
            "premium":     _f(ctx, "premium"),
            "levier_max":  actif.get("maxLeverage"),
            "au_plafond":  (nom in au_plafond) if plafond_ok else None,
        })

    df = pd.DataFrame(lignes)
    if df.empty:
        return df
    df = df.set_index("coin")
    df.attrs["ts"] = _utcnow()
    return df


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def derniere_photo() -> datetime | None:
    try:
        _init_table()
        with engine.connect() as conn:
            return conn.execute(select(func.max(hl_snapshots.c.ts))).scalar()
    except Exception as e:
        print(f"[radar] lecture de la dernière photo impossible : {e}")
        return None


def record_snapshot(live: pd.DataFrame | None = None, force: bool = False) -> bool:
    """Enregistre une photo si la précédente a plus de INTERVALLE_MIN − 2 min.

    `live` : photo déjà téléchargée par l'appelant (évite un second appel HL).
    Retourne True si une photo a été écrite.
    """
    try:
        _init_table()
        if not force:
            derniere = derniere_photo()
            if derniere and _utcnow() - derniere < timedelta(minutes=INTERVALLE_MIN - 2):
                return False

        if live is None:
            live = fetch_hl_live()
        if live is None or live.empty:
            return False

        ts = live.attrs.get("ts") or _utcnow()
        lignes = [
            {"ts": ts, "coin": coin, "oi": r["oi"], "mark_px": r["mark_px"],
             "funding": r["funding"], "day_ntl_vlm": r["day_ntl_vlm"],
             "premium": r["premium"]}
            for coin, r in live.iterrows()
        ]
        with engine.begin() as conn:
            conn.execute(insert(hl_snapshots), lignes)
            conn.execute(delete(hl_snapshots).where(
                hl_snapshots.c.ts < _utcnow() - timedelta(days=RETENTION_JOURS)))
        return True
    except Exception as e:
        # Doublon (deux enregistreurs à la même seconde), base verrouillée...
        # Une photo manquée n'est pas grave : la suivante arrive dans une heure.
        print(f"[radar] photo non enregistrée : {e}")
        return False


# ---------------------------------------------------------------------------
# Lecture de l'historique
# ---------------------------------------------------------------------------

def load_history(jours: int = 15) -> pd.DataFrame:
    """Photos des N derniers jours : colonnes ts, coin, oi, mark_px, day_ntl_vlm."""
    try:
        _init_table()
        depuis = _utcnow() - timedelta(days=jours)
        requete = (
            select(hl_snapshots.c.ts, hl_snapshots.c.coin, hl_snapshots.c.oi,
                   hl_snapshots.c.mark_px, hl_snapshots.c.day_ntl_vlm)
            .where(hl_snapshots.c.ts >= depuis)
            .order_by(hl_snapshots.c.ts)
        )
        with engine.connect() as conn:
            df = pd.DataFrame(conn.execute(requete).fetchall(),
                              columns=["ts", "coin", "oi", "mark_px", "day_ntl_vlm"])
        df["ts"] = pd.to_datetime(df["ts"])
        return df
    except Exception as e:
        print(f"[radar] lecture de l'historique impossible : {e}")
        return pd.DataFrame(columns=["ts", "coin", "oi", "mark_px", "day_ntl_vlm"])


# ---------------------------------------------------------------------------
# Enregistreur en arrière-plan
# ---------------------------------------------------------------------------

def _journal_si_besoin(derniere_tentative: datetime | None) -> datetime | None:
    """Note les états du jour une fois par jour, entre 00:05 et 04:00 UTC (la
    bougie journalière vient de clôturer, c'est le moment où ton bot décide).
    Hors de cette fenêtre, on ne rattrape pas : un état noté à 15 h ne serait
    pas comparable aux autres. En cas d'échec, nouvel essai 30 min plus tard."""
    maintenant = _utcnow()
    if maintenant.hour >= 4 or (maintenant.hour == 0 and maintenant.minute < 5):
        return derniere_tentative
    if derniere_tentative and maintenant - derniere_tentative < timedelta(minutes=30):
        return derniere_tentative
    from src.utils import journal         # import tardif : évite une boucle d'imports
    if journal.deja_enregistre():
        return derniere_tentative
    try:
        n = journal.tache_quotidienne()
        print(f"[journal] états du {maintenant:%Y-%m-%d} notés : {n} actifs")
    except Exception as e:
        print(f"[journal] échec, nouvel essai dans 30 min : {e}")
    return maintenant


def _boucle_enregistreur() -> None:
    print(f"[radar] enregistreur démarré — une photo toutes les {INTERVALLE_MIN} min")
    derniere_tentative = None
    while True:
        try:
            if record_snapshot():
                print(f"[radar] photo enregistrée à {_utcnow():%Y-%m-%d %H:%M} UTC")
        except Exception as e:      # le thread ne doit JAMAIS mourir
            print(f"[radar] erreur enregistreur : {e}")
        try:
            derniere_tentative = _journal_si_besoin(derniere_tentative)
        except Exception as e:
            print(f"[journal] erreur : {e}")
        time.sleep(300)             # vérifie toutes les 5 min, écrit toutes les heures


def start_recorder() -> threading.Thread:
    """Démarre l'enregistreur. À appeler via st.cache_resource (une fois par process)."""
    t = threading.Thread(target=_boucle_enregistreur, name="hl_recorder", daemon=True)
    t.start()
    return t
