"""
src/utils/conditions_marche.py
Conditions de marché : un filtre d'entrée qui s'AJOUTE aux indicateurs techniques
(page Backtest › Stratégies). Le moteur de backtest reste celui des autres pages
(src/controllers/backtest.py) : ce module ne fait que fabriquer, pour chaque
actif, une Series booléenne « la condition est vraie sur cette bougie ».

    condition                      données                    temporalités
    BTC par rapport à sa MM        bougies BTC-USD            toutes
    compression de l'actif         bougies de l'actif         toutes
    perf de l'actif sur N bougies  bougies de l'actif         toutes
    tendance longue / rebond       bougies journalières       jour
    z OI 24 h / 4 h                photos horaires de l'app   jour, heure (depuis oct. 2026)

Toutes les longueurs sont en bougies de la temporalité choisie, comme les
indicateurs techniques. Aucune donnée future : tout est glissant.
"""

import pandas as pd

from src.utils import indicateurs as I
from src.utils import strategies as S

MM_CHOIX = [10, 20, 50, 100, 200]
_TOUTES = {"jour", "heure", "semaine", "mois"}

# champs : (nom, type, choix ou défaut, libellé)
CONDITIONS = {
    "btc_mm":      {"libelle": "BTC par rapport à sa MM",
                    "champs": [("mm", "choix", MM_CHOIX, "MM"), ("cote", "choix", ["au-dessus", "en dessous"], "Côté")],
                    "temporalites": _TOUTES},
    "compression": {"libelle": "Compression de l'actif (5 bougies ÷ sa médiane sur 30)",
                    "champs": [("op", "choix", ["<", ">"], "Opérateur"), ("valeur", "nombre", 1.0, "Valeur")],
                    "temporalites": _TOUTES},
    "perf":        {"libelle": "Perf de l'actif sur N bougies (%)",
                    "champs": [("n", "entier", 7, "Bougies"), ("op", "choix", ["<", ">"], "Opérateur"),
                               ("valeur", "nombre", 0.0, "Valeur (%)")],
                    "temporalites": _TOUTES},
    "tendance":    {"libelle": "Tendance longue propre (règles du Screening) · jour",
                    "champs": [("sens", "choix", ["haussière", "baissière"], "Sens")],
                    "temporalites": {"jour"}},
    "moment":      {"libelle": "Rebond / repli dans la tendance · jour",
                    "champs": [("sens", "choix", ["haussière", "baissière"], "Tendance"),
                               ("moment", "choix", ["se retourne (entrée)", "en cours"], "Moment")],
                    "temporalites": {"jour"}},
    "z_oi_24":     {"libelle": "z OI 24 h de l'actif · OI depuis oct.",
                    "champs": [("op", "choix", [">", "<"], "Opérateur"), ("valeur", "nombre", 2.0, "Valeur")],
                    "oi": True, "temporalites": {"jour", "heure"}},
    "z_oi_4":      {"libelle": "z OI 4 h de l'actif · OI depuis oct.",
                    "champs": [("op", "choix", [">", "<"], "Opérateur"), ("valeur", "nombre", 1.0, "Valeur")],
                    "oi": True, "temporalites": {"jour", "heure"}},
}


def defaut(type_: str) -> dict:
    """Condition de ce type avec ses valeurs par défaut."""
    c = {"type": type_}
    for nom, genre, choix, _ in CONDITIONS[type_]["champs"]:
        c[nom] = choix[0] if genre == "choix" else choix
    return c


def utilise_oi(conditions: list[dict]) -> bool:
    return any(CONDITIONS[c["type"]].get("oi") for c in conditions)


def invalides(conditions: list[dict], temporalite: str) -> list[str]:
    return [CONDITIONS[c["type"]]["libelle"] for c in conditions
            if temporalite not in CONDITIONS[c["type"]]["temporalites"]]


def decrire(conditions: list[dict]) -> str:
    morceaux = []
    for c in conditions:
        t = c["type"]
        if t == "btc_mm":
            morceaux.append(f"BTC {c['cote']} MM{c['mm']}")
        elif t in ("compression", "z_oi_24", "z_oi_4"):
            nom = {"compression": "compression", "z_oi_24": "z OI 24 h", "z_oi_4": "z OI 4 h"}[t]
            morceaux.append(f"{nom} {c['op']} {c['valeur']:g}")
        elif t == "perf":
            morceaux.append(f"perf {c['n']} bougies {c['op']} {c['valeur']:g} %")
        elif t == "tendance":
            morceaux.append(f"tendance {c['sens']}")
        elif t == "moment":
            morceaux.append(f"{'rebond' if c['sens'] == 'baissière' else 'repli'} {c['moment']}")
    return " · ".join(morceaux)


# ---------------------------------------------------------------------------
# Données nécessaires aux conditions (chargées une fois par lancement)
# ---------------------------------------------------------------------------

def charger_oi(temporalite: str) -> dict[str, pd.DataFrame]:
    """{"z_oi_24": DataFrame bougie × symbol, "z_oi_4": …}, alignés sur la CLÔTURE des bougies.
    La photo de l'heure H est rattachée à la bougie qui se termine à H : c'est
    l'information disponible au moment où la décision est prise."""
    if temporalite not in ("jour", "heure"):
        return {}
    from src.utils import backtest_oi as O
    from src.utils.market_data import get_screening_coins
    photos = O.charger_photos()
    if photos.empty:
        return {}
    oi = O.grille(photos, "oi")
    z = {"z_oi_24": O.zscore(oi / oi.shift(24) - 1), "z_oi_4": O.zscore(oi / oi.shift(4) - 1)}
    vers_symbole = {c["hl_name"]: c["symbol"] for c in get_screening_coins()}
    sortie = {}
    for cle, g in z.items():
        if temporalite == "jour":
            g = g[g.index.hour == 0]
            g.index = g.index.normalize() - pd.Timedelta(days=1)
        else:
            g = g.copy()
            g.index = g.index - pd.Timedelta(hours=1)
        sortie[cle] = g.rename(columns=vers_symbole)
    return sortie


def contexte(conditions: list[dict], temporalite: str) -> dict:
    """Bougies du BTC et historique d'OI, seulement si une condition en a besoin."""
    from src.utils.data_loader import fetch_ohlcv
    ctx = {"btc": None, "oi": {}}
    if any(c["type"] == "btc_mm" for c in conditions):
        ctx["btc"] = fetch_ohlcv("BTC-USD", temporalite)
    if utilise_oi(conditions):
        ctx["oi"] = charger_oi(temporalite)
    return ctx


def debut_oi(ctx: dict):
    """Première bougie où l'OI existe (None si aucune condition OI)."""
    dates = [g.dropna(how="all").index.min() for g in ctx["oi"].values() if len(g)]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# Le filtre
# ---------------------------------------------------------------------------

def _aligner(serie: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    return serie.reindex(serie.index.union(index)).ffill().reindex(index)


def _une(df: pd.DataFrame, c: dict, ctx: dict, symbol: str, cache: dict) -> pd.Series:
    t, close = c["type"], df["close"]

    def op(serie):
        return (serie < c["valeur"]) if c["op"] == "<" else (serie > c["valeur"])

    if t == "btc_mm":
        btc = ctx.get("btc")
        if btc is None:
            return pd.Series(False, index=df.index)
        mm = btc["close"].rolling(c["mm"]).mean()
        m = ((btc["close"] > mm) if c["cote"] == "au-dessus" else (btc["close"] < mm)) & mm.notna()
        return _aligner(m.astype(float), df.index).fillna(0).astype(bool)
    if t == "compression":
        ohlc = df.rename(columns={"high": "High", "low": "Low", "close": "Close"})
        return op(I.compression(ohlc)).fillna(False)
    if t == "perf":
        return op((close / close.shift(int(c["n"])) - 1) * 100).fillna(False)
    if t in ("tendance", "moment"):
        if "metriques" not in cache:
            cache["metriques"] = S.metriques_series(close)
        m = cache["metriques"]
        sens = "short" if c["sens"] == "baissière" else "long"
        ok = S.qualifie(m["perf_1an"], m["pct_sous_mm"], m["pente_mm100"], m["pire_rebond"], sens)
        ok = ok.reindex(df.index, fill_value=False)
        if t == "tendance":
            return ok
        mom = S.moment_series(close, sens).reindex(df.index)
        return ok & (mom == ("entree" if c["moment"].startswith("se retourne") else "contre"))
    if t in ("z_oi_24", "z_oi_4"):
        g = ctx["oi"].get(t)
        if g is None or symbol not in g.columns:
            return pd.Series(False, index=df.index)
        return op(g[symbol].reindex(df.index)).fillna(False)
    raise ValueError(f"condition inconnue : {t}")


def filtre(df: pd.DataFrame, conditions: list[dict], ctx: dict, symbol: str) -> pd.Series | None:
    """Series booléenne (toutes les conditions vraies) sur l'index de df (colonnes
    open/high/low/close, format de data_loader). None s'il n'y a aucune condition."""
    if not conditions:
        return None
    cache, m = {}, pd.Series(True, index=df.index)
    for c in conditions:
        m &= _une(df, c, ctx, symbol, cache)
    return m
