"""
src/utils/journal.py
Journal des états du radar — pour savoir si le radar MARCHE.

Chaque jour, peu après la nouvelle bougie journalière (00:05 UTC), on note
pour chaque actif son état radar et son prix. Le prix des jours suivants est
lu dans le journal lui-même : pas besoin d'autre source, et rien n'expire.

Après quelques semaines, resultats() répond à la seule question qui compte :
« quand un actif était en 🔵 Démarrage, qu'a fait son prix 1, 3 et 7 jours
plus tard — et est-ce mieux que la moyenne du marché ? »

Volume : ~170 lignes par jour, ~62 000 par an. Pas de purge.
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import Column, Date, DateTime, Float, MetaData, String, Table, func, insert, select

from src.auth.db import engine

HORIZONS_J = (1, 3, 7)

_metadata = MetaData()

hl_etats = Table(
    "hl_etats", _metadata,
    Column("jour",     Date,       primary_key=True),   # jour UTC de la bougie
    Column("coin",     String(40), primary_key=True),
    Column("ts",       DateTime),                       # heure exacte de la photo
    Column("etat",     String(40)),
    Column("prix",     Float),                          # prix Hyperliquid à ce moment
    Column("oi_z",     Float),
    Column("alpha_7d", Float),
    Column("score_7d", Float),
    Column("meteo",    String(40)),                     # météo du marché ce jour-là
)

_table_ok = False


def _init_table() -> None:
    global _table_ok
    if not _table_ok:
        _metadata.create_all(engine)
        _table_ok = True


def _aujourd_hui_utc() -> date:
    return datetime.now(timezone.utc).date()


def deja_enregistre(jour: date | None = None) -> bool:
    try:
        _init_table()
        jour = jour or _aujourd_hui_utc()
        with engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(hl_etats)
                             .where(hl_etats.c.jour == jour)).scalar()
        return bool(n)
    except Exception as e:
        print(f"[journal] lecture impossible : {e}")
        return True        # dans le doute, on n'écrit pas


def enregistrer(df: pd.DataFrame, live: pd.DataFrame, meteo: str) -> int:
    """Écrit l'état du jour de chaque actif. Retourne le nombre de lignes écrites."""
    _init_table()
    jour = _aujourd_hui_utc()
    if deja_enregistre(jour):
        return 0
    ts = live.attrs.get("ts") or datetime.now(timezone.utc).replace(tzinfo=None)

    def _f(v):
        try:
            v = float(v)
            return None if np.isnan(v) else v
        except (TypeError, ValueError):
            return None

    lignes = []
    for _, r in df.iterrows():
        coin = r["hl_name"]
        prix = _f(live["mark_px"].get(coin)) if coin in live.index else None
        if prix is None:
            continue
        lignes.append({
            "jour": jour, "coin": coin, "ts": ts, "etat": r.get("etat"), "prix": prix,
            "oi_z": _f(r.get("oi_z")), "alpha_7d": _f(r.get("alpha_7d")),
            "score_7d": _f(r.get("score_7d")), "meteo": meteo,
        })
    if lignes:
        with engine.begin() as conn:
            conn.execute(insert(hl_etats), lignes)
    return len(lignes)


def tache_quotidienne() -> int:
    """Appelée par l'enregistreur après 00:05 UTC : charge tout, classe, note.

    Recharge les bougies Yahoo (2-5 min, une fois par jour) car les états ont
    besoin de l'amplitude, de l'alpha et de la compression.
    """
    from src.utils.market_data import load_screening_data
    from src.utils.hl_snapshots import fetch_hl_live, load_history
    from src.utils import radar as R

    live = fetch_hl_live()
    if live is None or live.empty:
        raise RuntimeError("Hyperliquid indisponible")
    df = load_screening_data()
    if df is None or df.empty:
        raise RuntimeError("données Yahoo indisponibles")
    df = R.ajouter_scores(df)
    df = R.compute_radar(df, live, load_history(jours=R.Z_FENETRE_JOURS + 1))
    meteo = R.meteo_marche(df)
    n = enregistrer(df, live, meteo["verdict"])
    if n:
        # Un seul e-mail par jour : uniquement quand les états viennent d'être notés
        from src.utils.alertes import signaux_du_jour
        signaux_du_jour(df, meteo, R.ETATS)
    return n


# ---------------------------------------------------------------------------
# Lecture et résultats
# ---------------------------------------------------------------------------

def charger() -> pd.DataFrame:
    try:
        _init_table()
        with engine.connect() as conn:
            rows = conn.execute(select(hl_etats.c.jour, hl_etats.c.coin, hl_etats.c.etat,
                                       hl_etats.c.prix, hl_etats.c.meteo)).fetchall()
        df = pd.DataFrame(rows, columns=["jour", "coin", "etat", "prix", "meteo"])
        df["jour"] = pd.to_datetime(df["jour"])
        return df
    except Exception as e:
        print(f"[journal] lecture impossible : {e}")
        return pd.DataFrame(columns=["jour", "coin", "etat", "prix", "meteo"])


def resultats(journal: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Pour chaque état : nombre de cas, variation moyenne du prix et % de
    hausses à 1, 3 et 7 jours. Première ligne = tous les actifs (la référence
    à battre : un état n'a de valeur que s'il fait mieux que la moyenne).
    """
    j = charger() if journal is None else journal
    info = {"jours": int(j["jour"].nunique()) if len(j) else 0,
            "debut": j["jour"].min() if len(j) else None}
    if j.empty:
        return pd.DataFrame(), info

    j = j.copy()
    for n in HORIZONS_J:
        futur = j[["jour", "coin", "prix"]].copy()
        futur["jour"] = futur["jour"] - pd.Timedelta(days=n)
        futur = futur.rename(columns={"prix": f"prix_{n}"})
        j = j.merge(futur, on=["jour", "coin"], how="left")
        j[f"perf_{n}"] = (j[f"prix_{n}"] / j["prix"] - 1) * 100

    def _bloc(g: pd.DataFrame) -> dict:
        ligne = {"cas": len(g)}
        for n in HORIZONS_J:
            p = g[f"perf_{n}"].dropna()
            ligne[f"moy_{n}"]    = round(p.mean(), 2) if len(p) else None
            ligne[f"hausse_{n}"] = round((p > 0).mean() * 100) if len(p) else None
            # Ampleur = taille du mouvement QUEL QUE SOIT son sens. C'est la
            # mesure qui compte pour 🟢 Accumulation (« ça va bouger, sens
            # inconnu ») et pour une stratégie à deux ordres de part et d'autre.
            ligne[f"ampleur_{n}"] = round(p.abs().mean(), 2) if len(p) else None
            ligne[f"n_{n}"]      = len(p)
        return ligne

    from src.utils.radar import ORDRE_ETATS
    lignes = [{"etat": "Tous les actifs (référence)", **_bloc(j)}]
    for etat, g in sorted(j.groupby("etat"), key=lambda kv: ORDRE_ETATS.get(kv[0], 99)):
        lignes.append({"etat": etat, **_bloc(g)})
    return pd.DataFrame(lignes), info
