"""
src/utils/atelier.py
Atelier de backtest : l'utilisateur compose sa stratégie, on la teste.

    conditions d'entrée (toutes vraies)  +  sens  +  sorties (la première atteinte)

Deux sources de données, choisies automatiquement :
    prix   → bougies journalières Yahoo depuis 2020 (garde-fous de backtest_strategies)
    OI     → photos horaires Hyperliquid enregistrées par l'app depuis octobre 2026,
             lues à 00 h UTC chaque jour (= clôture de la bougie de la veille)
Dès qu'une condition porte sur l'OI, le test est restreint à la période où
l'OI existe, et le résultat le signale.

Mêmes règles de simulation que le backtest des stratégies : décision à la
clôture, exécution à l'ouverture suivante, une position par actif, frais +
glissement 0,19 % par aller-retour, sans levier.

Chaque test est comparé au MÊME SENS PRIS AU HASARD (mêmes sorties, aucune
condition) : une condition ne sert que si elle fait mieux que ça.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.utils import strategies as S

FRAIS_AR_PCT = 0.19
PART_TEST = 1 / 3
MM_CHOIX = [10, 20, 50, 100, 200]
TABLE = "atelier_tests"

# ---------------------------------------------------------------------------
# Catalogue des conditions
# ---------------------------------------------------------------------------
# champs : (nom, type, choix ou défaut, libellé)
CONDITIONS = {
    "btc_mm":      {"libelle": "BTC par rapport à sa MM",
                    "champs": [("mm", "choix", MM_CHOIX, "MM"), ("cote", "choix", ["en dessous", "au-dessus"], "Côté")]},
    "prix_mm":     {"libelle": "Prix de l'actif par rapport à sa MM",
                    "champs": [("mm", "choix", MM_CHOIX, "MM"), ("cote", "choix", ["en dessous", "au-dessus"], "Côté")]},
    "pente_mm":    {"libelle": "Pente de la MM de l'actif (sur 5 j)",
                    "champs": [("mm", "choix", MM_CHOIX, "MM"), ("sens", "choix", ["baisse", "monte"], "Sens")]},
    "compression": {"libelle": "Compression de l'actif (5 j ÷ sa médiane 30 j)",
                    "champs": [("op", "choix", ["<", ">"], "Opérateur"), ("valeur", "nombre", 1.0, "Valeur")]},
    "rsi":         {"libelle": "RSI 14 j de l'actif",
                    "champs": [("op", "choix", ["<", ">"], "Opérateur"), ("valeur", "nombre", 30.0, "Valeur")]},
    "perf":        {"libelle": "Perf de l'actif sur N jours (%)",
                    "champs": [("n", "entier", 7, "Jours"), ("op", "choix", ["<", ">"], "Opérateur"),
                               ("valeur", "nombre", 0.0, "Valeur (%)")]},
    "tendance":    {"libelle": "Tendance longue propre (règles du Screening)",
                    "champs": [("sens", "choix", ["baissière", "haussière"], "Sens")]},
    "moment":      {"libelle": "Rebond / repli dans la tendance",
                    "champs": [("sens", "choix", ["baissière", "haussière"], "Tendance"),
                               ("moment", "choix", ["se retourne (entrée)", "en cours"], "Moment")]},
    "z_oi_24":     {"libelle": "z OI 24 h de l'actif  · OI depuis oct.",
                    "champs": [("op", "choix", [">", "<"], "Opérateur"), ("valeur", "nombre", 2.0, "Valeur")], "oi": True},
    "z_oi_4":      {"libelle": "z OI 4 h de l'actif  · OI depuis oct.",
                    "champs": [("op", "choix", [">", "<"], "Opérateur"), ("valeur", "nombre", 1.0, "Valeur")], "oi": True},
}


def utilise_oi(conditions: list[dict]) -> bool:
    return any(CONDITIONS[c["type"]].get("oi") for c in conditions)


def decrire(conditions: list[dict], sens: dict, sorties: dict) -> str:
    morceaux = []
    for c in conditions:
        t = c["type"]
        if t == "btc_mm":
            morceaux.append(f"BTC {c['cote']} MM{c['mm']}")
        elif t == "prix_mm":
            morceaux.append(f"prix {c['cote']} MM{c['mm']}")
        elif t == "pente_mm":
            morceaux.append(f"MM{c['mm']} qui {c['sens']}")
        elif t in ("compression", "rsi", "z_oi_24", "z_oi_4"):
            nom = {"compression": "compression", "rsi": "RSI", "z_oi_24": "z OI 24 h", "z_oi_4": "z OI 4 h"}[t]
            morceaux.append(f"{nom} {c['op']} {c['valeur']:g}")
        elif t == "perf":
            morceaux.append(f"perf {c['n']} j {c['op']} {c['valeur']:g} %")
        elif t == "tendance":
            morceaux.append(f"tendance {c['sens']}")
        elif t == "moment":
            morceaux.append(f"{'rebond' if c['sens'] == 'baissière' else 'repli'} {c['moment']}")
    s = {"long": "LONG", "short": "SHORT"}.get(sens["type"]) or \
        "selon BTC (MM" + "/".join(map(str, sens.get("mms", []))) + ")"
    so = []
    if sorties.get("jours"):
        so.append(f"{sorties['jours']} j max")
    if sorties.get("sl"):
        so.append(f"SL {sorties['sl']:g} %")
    if sorties.get("tp"):
        so.append(f"TP {sorties['tp']:g} %")
    if sorties.get("mm"):
        so.append(f"sortie MM{sorties['mm']}")
    return f"{s} · " + " · ".join(morceaux or ["sans condition"]) + " → " + ", ".join(so)


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def charger_prix(progress_cb=None) -> tuple[dict, list]:
    """{symbol: OHLC journalier} depuis 2020, garde-fous compris (backtest_strategies)."""
    from src.utils import backtest_strategies as B
    from src.utils.market_data import get_screening_coins
    ecartes = []
    donnees = B.telecharger(get_screening_coins(), B.DEPUIS, progress_cb, ecartes)
    return donnees, ecartes


def charger_oi_journalier() -> dict[str, pd.DataFrame]:
    """{"z_oi_24": DataFrame jour × symbol, "z_oi_4": …}, lus à 00 h UTC.

    Le z de 00 h UTC du jour J est indexé sur J−1 : c'est la clôture de la
    bougie journalière Yahoo de J−1, moment où la décision est prise."""
    from src.utils import backtest_oi as O
    from src.utils.market_data import get_screening_coins
    photos = O.charger_photos()
    if photos.empty:
        return {}
    oi = O._grille(photos, "oi")
    z = {"z_oi_24": O._z(oi / oi.shift(24) - 1), "z_oi_4": O._z(oi / oi.shift(4) - 1)}
    vers_symbole = {c["hl_name"]: c["symbol"] for c in get_screening_coins()}
    sortie = {}
    for cle, g in z.items():
        g = g[g.index.hour == 0]
        g.index = g.index.normalize() - pd.Timedelta(days=1)
        sortie[cle] = g.rename(columns=vers_symbole)
    return sortie


# ---------------------------------------------------------------------------
# Indicateurs et conditions
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    h = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    b = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + h / b.replace(0, np.nan))


def _compression(df: pd.DataFrame) -> pd.Series:
    amp = (df["High"] - df["Low"]) / df["Close"]
    return amp.rolling(5).mean() / amp.rolling(30).median()


def _masque(df: pd.DataFrame, c: dict, btc: pd.DataFrame | None, oi: dict, symbol: str,
            cache: dict) -> pd.Series:
    t = c["type"]
    close = df["Close"]

    def op(serie):
        return (serie < c["valeur"]) if c["op"] == "<" else (serie > c["valeur"])

    if t == "btc_mm":
        if btc is None:
            return pd.Series(False, index=df.index)
        mm = btc["Close"].rolling(c["mm"]).mean()
        m = (btc["Close"] < mm) if c["cote"] == "en dessous" else (btc["Close"] > mm)
        return m.where(mm.notna(), False).reindex(df.index, method="ffill").fillna(False).astype(bool)
    if t == "prix_mm":
        mm = close.rolling(c["mm"]).mean()
        return ((close < mm) if c["cote"] == "en dessous" else (close > mm)) & mm.notna()
    if t == "pente_mm":
        mm = close.rolling(c["mm"]).mean()
        p = mm / mm.shift(5) - 1
        return (p < 0) if c["sens"] == "baisse" else (p > 0)
    if t == "compression":
        return op(_compression(df)).fillna(False)
    if t == "rsi":
        return op(_rsi(close)).fillna(False)
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
        voulu = "entree" if c["moment"].startswith("se retourne") else "contre"
        return ok & (mom == voulu)
    if t in ("z_oi_24", "z_oi_4"):
        g = oi.get(t)
        if g is None or symbol not in g.columns:
            return pd.Series(False, index=df.index)
        z = g[symbol].reindex(df.index)
        return op(z).fillna(False)
    raise ValueError(f"condition inconnue : {t}")


def _sens_series(df: pd.DataFrame, sens: dict, btc: pd.DataFrame | None) -> pd.Series:
    """+1 long, −1 short, 0 pas de trade, pour chaque jour."""
    if sens["type"] == "long":
        return pd.Series(1, index=df.index)
    if sens["type"] == "short":
        return pd.Series(-1, index=df.index)
    if btc is None:
        return pd.Series(0, index=df.index)
    c = btc["Close"]
    dessus = pd.Series(True, index=c.index)
    dessous = pd.Series(True, index=c.index)
    valide = pd.Series(True, index=c.index)
    for n in sens.get("mms", [100]):
        mm = c.rolling(n).mean()
        dessus &= c > mm
        dessous &= c < mm
        valide &= mm.notna()
    s = pd.Series(0, index=c.index)
    s[dessus & valide] = 1
    s[dessous & valide] = -1
    return s.reindex(df.index, method="ffill").fillna(0).astype(int)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _simuler(symbol: str, df: pd.DataFrame, signal: np.ndarray, sens: np.ndarray,
             sorties: dict, debut: pd.Timestamp) -> list[dict]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    dates = df.index
    n = len(df)
    jours, sl, tp = sorties.get("jours") or 0, sorties.get("sl") or 0, sorties.get("tp") or 0
    mm = df["Close"].rolling(sorties["mm"]).mean().to_numpy() if sorties.get("mm") else None
    trades, pos, entrer = [], None, 0

    def fermer(t, prix, motif):
        brut = pos["s"] * (prix / pos["px"] - 1) * 100
        trades.append({"symbol": symbol, "sens": "long" if pos["s"] > 0 else "short",
                       "entree": dates[pos["t"]], "sortie": dates[t], "motif": motif,
                       "rend_pct": brut - FRAIS_AR_PCT, "mae_pct": pos["mae"],
                       "jours": int((dates[t] - dates[pos["t"]]).days)})

    for t in range(n):
        if pos is None and entrer:
            pos = {"t": t, "px": o[t], "s": entrer, "mae": 0.0, "sortir": None}
        entrer = 0
        if pos is not None:
            s = pos["s"]
            if pos["sortir"]:
                fermer(t, o[t], pos["sortir"])
                pos = None
            elif jours and t - pos["t"] >= jours:
                fermer(t, o[t], f"{jours} jours")
                pos = None
            else:
                adverse = (1 - l[t] / pos["px"]) if s > 0 else (h[t] / pos["px"] - 1)
                pos["mae"] = max(pos["mae"], adverse * 100)
                px_sl = pos["px"] * (1 - s * sl / 100) if sl else None
                px_tp = pos["px"] * (1 + s * tp / 100) if tp else None
                touche_sl = px_sl is not None and ((s > 0 and l[t] <= px_sl) or (s < 0 and h[t] >= px_sl))
                touche_tp = px_tp is not None and ((s > 0 and h[t] >= px_tp) or (s < 0 and l[t] <= px_tp))
                if touche_sl:                    # les deux le même jour : on suppose le pire
                    prix = min(o[t], px_sl) if s > 0 else max(o[t], px_sl)
                    fermer(t, prix, "stop")
                    pos = None
                    continue
                if touche_tp:
                    prix = max(o[t], px_tp) if s > 0 else min(o[t], px_tp)
                    fermer(t, prix, "objectif")
                    pos = None
                    continue
                if mm is not None and not np.isnan(mm[t]) and s * (c[t] - mm[t]) < 0:
                    pos["sortir"] = f"croisement MM{sorties['mm']}"
            if pos is not None:
                continue
        if t < n - 1 and dates[t] >= debut and signal[t] and sens[t] != 0:
            entrer = int(sens[t])
    if pos is not None:
        fermer(n - 1, c[n - 1], "ouvert")
    return trades


def lancer(prix: dict, oi: dict, conditions: list[dict], sens: dict, sorties: dict) -> dict:
    """Retourne {"trades", "ref", "periodes", "debut", "coupure", "avec_oi"}."""
    avec_oi = utilise_oi(conditions)
    btc = prix.get("BTC")
    debut = pd.Timestamp("2020-01-01")
    if avec_oi:
        dates_oi = [g.dropna(how="all").index.min() for g in oi.values() if g is not None and len(g)]
        if not dates_oi or pd.isna(min(dates_oi)):
            raise RuntimeError("aucun historique d'OI disponible")
        debut = max(dates_oi)
    fin = max(df.index.max() for df in prix.values())
    coupure = None if avec_oi else debut + (fin - debut) * (1 - PART_TEST)

    trades, ref = [], []
    for symbol, df in prix.items():
        cache = {}
        signal = pd.Series(True, index=df.index)
        for c in conditions:
            signal &= _masque(df, c, btc, oi, symbol, cache)
        s = _sens_series(df, sens, btc).to_numpy()
        trades += _simuler(symbol, df, signal.to_numpy(bool), s, sorties, debut)
        ref += _simuler(symbol, df, np.ones(len(df), bool), s, sorties, debut)
    return {"trades": pd.DataFrame(trades), "ref": pd.DataFrame(ref), "debut": debut,
            "fin": fin, "coupure": coupure, "avec_oi": avec_oi}


# ---------------------------------------------------------------------------
# Bilan et verdict
# ---------------------------------------------------------------------------

def _stats(t: pd.DataFrame) -> dict:
    if t is None or t.empty:
        return {"trades": 0}
    r = t["rend_pct"]
    pertes = -r[r < 0].sum()
    mae90 = float(t["mae_pct"].quantile(0.9))
    return {
        "trades": len(r), "gagnants": round((r > 0).mean() * 100, 1),
        "gain_moy": round(r.mean(), 2), "gain_med": round(r.median(), 2),
        "pf": round(r[r > 0].sum() / pertes, 2) if pertes > 0 else None,
        "levier_max": max(1, int(min(100 / mae90, 50) / 2)) if mae90 > 0 else None,
        "jours_moy": round(t["jours"].mean(), 1),
    }


def bilan(res: dict) -> dict:
    t, ref, coupure = res["trades"], res["ref"], res["coupure"]

    def part(df, periode):
        if df.empty or coupure is None:
            return df
        e = pd.to_datetime(df["entree"])
        return df[e < coupure] if periode == "app" else df[e >= coupure]

    b = {"strat": _stats(t), "ref": _stats(ref)}
    if coupure is not None:
        for p in ("app", "test"):
            b[f"strat_{p}"] = _stats(part(t, p))
            b[f"ref_{p}"] = _stats(part(ref, p))
    b["verdict"] = verdict(b, res["avec_oi"])
    return b


def verdict(b: dict, avec_oi: bool) -> str:
    s, r = b["strat"], b["ref"]
    if s.get("trades", 0) < 30:
        return "⏳ Trop peu de trades pour juger"
    if not s.get("pf") or s["pf"] <= 1 or s["gain_moy"] <= r.get("gain_moy", -1e9):
        return "❌ Ne marche pas"
    if avec_oi:
        return "⚠️ Prometteur, mais période trop courte (OI depuis octobre)"
    a, te, rt = b.get("strat_app", {}), b.get("strat_test", {}), b.get("ref_test", {})
    if (a.get("pf") or 0) >= 1.2 and (te.get("pf") or 0) >= 1.2 and te.get("trades", 0) >= 30 \
            and te.get("gain_moy", -1e9) > rt.get("gain_moy", -1e9):
        return "✅ Tient sur les deux périodes"
    return "⚠️ À confirmer"


# ---------------------------------------------------------------------------
# Historique des tests
# ---------------------------------------------------------------------------

def _colonne_user(engine) -> None:
    """Table créée avant l'ouverture aux clients : ajoute la colonne user_id."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    if insp.has_table(TABLE) and "user_id" not in {c["name"] for c in insp.get_columns(TABLE)}:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN user_id INTEGER"))


def enregistrer(description: str, config: dict, b: dict, user_id=None) -> None:
    """Chaque utilisateur a son propre historique (colonne user_id)."""
    from src.auth.db import engine
    _colonne_user(engine)
    ligne = pd.DataFrame([{
        "user_id": user_id,
        "quand": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "description": description, "verdict": b["verdict"],
        "trades": b["strat"].get("trades"), "gain_moy": b["strat"].get("gain_moy"),
        "gagnants": b["strat"].get("gagnants"), "ref_gain_moy": b["ref"].get("gain_moy"),
        "pf": b["strat"].get("pf"), "config": json.dumps(config, ensure_ascii=False),
    }])
    ligne.to_sql(TABLE, engine, if_exists="append", index=False)


def historique(user_id=None) -> pd.DataFrame:
    """Les tests de CET utilisateur, du plus récent au plus ancien."""
    from src.auth.db import engine
    try:
        _colonne_user(engine)
        with engine.connect() as conn:
            return pd.read_sql(text(f"SELECT * FROM {TABLE} WHERE user_id = :u ORDER BY quand DESC"),
                               conn, params={"u": user_id})
    except Exception:
        return pd.DataFrame()
