"""
src/utils/backtest_strategies.py
Backtest des stratégies de tendance du Screening — est-ce que ça MARCHE ?

Teste chaque stratégie de src/utils/strategies.py sur tout l'univers
(Hyperliquid ∩ Yahoo), sur les bougies journalières depuis 2020, avec deux
sorties possibles, contre une RÉFÉRENCE au hasard dans le même sens.

Règles de simulation (identiques pour toutes les stratégies) :
  - décision à la clôture du jour t, exécution à l'OUVERTURE de t+1 :
    aucune information future n'est utilisée
  - une seule position à la fois par actif, sans levier (le levier tenable
    se lit dans la colonne MAE : le pire mouvement contre toi pendant le trade)
  - entrée seulement si le prix est du bon côté de la MM de sortie
    (sinon le trade serait coupé dès le lendemain)
  - sortie : clôture de l'autre côté de la MM de sortie (MM100 = laisser
    courir, MM20 = sortir plus vite), exécutée à l'ouverture suivante
  - Rebond / Repli : stop en plus, posé sur le plus haut (short) ou le plus bas
    (long) des 10 derniers jours, c'est-à-dire au-delà du contre-mouvement
  - frais : 0,045 % (taker Hyperliquid) + 0,05 % de glissement, par côté
  - funding NON compté : pas d'historique de funding dans Yahoo

Les résultats sont découpés en Apprentissage (2/3 les plus anciens) et Test
(le dernier tiers) : une stratégie qui ne marche que sur la première partie
n'est pas une stratégie, c'est un hasard.

Biais connu : l'univers = les actifs encore cotés AUJOURD'HUI. Les tokens
morts entre-temps manquent → les longs sont un peu flattés, les shorts un peu
pénalisés (un token mort aurait été un excellent short).

Lancement : bouton de la page Historique, ou en ligne de commande depuis la
racine du projet :  python -m src.utils.backtest_strategies
"""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.utils import strategies as S

DEPUIS        = "2020-01-01"
FRAIS_PCT     = 0.045      # par côté (taker Hyperliquid)
GLISSEMENT_PCT = 0.05      # par côté
PART_TEST     = 1 / 3
JOURS_STOP    = 10         # stop des Rebond / Repli : extrême des 10 derniers jours
JOURS_REF     = 20         # référence : positions de 20 jours enchaînées, sans aucun critère

SORTIES = {
    "mm100": {"libelle": "Sortie MM100 (laisser courir)", "mm": 100},
    "mm20":  {"libelle": "Sortie MM20 (plus rapide)",     "mm": 20},
}
REFERENCES = {
    "ref_short": {"libelle": "🎲 Référence short (au hasard)", "sens": "short"},
    "ref_long":  {"libelle": "🎲 Référence long (au hasard)",  "sens": "long"},
}

# Filtre de régime : la même chose que la référence (positions de 20 jours sur
# tous les actifs, sans critère sur l'actif), mais seulement quand le marché va
# dans le bon sens — BTC sous sa MM100 pour shorter, au-dessus pour acheter.
# Deux règles, aucun réglage optimisé : c'est la version « robuste » à tester
# contre la référence sans filtre, sur les deux périodes.
MM_REGIME = 100
REGIMES = {
    "regime_short": {"libelle": "🧭 Short quand BTC < MM100 (tenue 20 j)", "sens": "short",
                     "btc_haussier": False},
    "regime_long":  {"libelle": "🧭 Long quand BTC > MM100 (tenue 20 j)",  "sens": "long",
                     "btc_haussier": True},
}

# Système complet = les deux côtés du filtre de régime réunis : long quand le
# BTC est au-dessus de sa MM100, short quand il est en dessous. Chaque côté
# gagne quand son régime domine ; la question est de savoir si l'ENSEMBLE
# gagne sur les deux périodes. Calculé dans le bilan, à partir des trades.
COMBINES = {
    "regime_combine": {"libelle": "🧭 Système complet : long si BTC > MM100, short sinon",
                       "sens": "les deux", "membres": list(REGIMES)},
}

_FRAIS_AR = 2 * (FRAIS_PCT + GLISSEMENT_PCT)

TABLE_RESUME = "bt_resume"
TABLE_TRADES = "bt_trades"


def definition(cle: str) -> dict:
    return (S.STRATEGIES.get(cle) or REFERENCES.get(cle) or REGIMES.get(cle)
            or COMBINES.get(cle) or {})


def libelle(cle: str) -> str:
    return definition(cle).get("libelle", cle)


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def telecharger(coins: list[dict], depuis: str = DEPUIS, progress_cb=None,
                ecartes: list | None = None, intervalle: str = "1d") -> dict:
    """{symbol: DataFrame Open/High/Low/Close} en bougies journalières COMPLÈTES.

    Deux garde-fous (voir strategies.py) :
      - ticker Yahoo qui ne cote pas le même actif qu'Hyperliquid → écarté
      - saut de prix impossible (×10 en un jour) → on ne garde que l'après
    `ecartes` reçoit la liste des actifs écartés, avec le motif.
    """
    import yfinance as yf
    from src.utils.market_data import _bougies_completes, fetch_hl_context

    ecartes = [] if ecartes is None else ecartes
    contexte = fetch_hl_context()
    if not contexte:
        print("[backtest] Hyperliquid indisponible : contrôle des tickers impossible")
    donnees = {}
    paquets = [coins[i:i + 25] for i in range(0, len(coins), 25)]
    for k, paquet in enumerate(paquets):
        if progress_cb:
            progress_cb(0.6 * k / len(paquets), f"Téléchargement Yahoo {k * 25}/{len(coins)}…")
        tickers = [c["ticker"] for c in paquet]
        try:
            if intervalle == "1h":           # Yahoo : 730 jours maximum en horaire
                brut = yf.download(tickers, period="730d", interval="1h", group_by="ticker",
                                   auto_adjust=False, threads=True, progress=False)
            else:
                brut = yf.download(tickers, start=depuis, interval=intervalle, group_by="ticker",
                                   auto_adjust=False, threads=True, progress=False)
        except Exception as e:
            print(f"[backtest] paquet ignoré : {e}")
            continue
        for c in paquet:
            try:
                df = brut[c["ticker"]] if len(tickers) > 1 else brut
                df = df[["Open", "High", "Low", "Close"]].dropna()
                df.index = pd.to_datetime(df.index).tz_localize(None)
                # bougie en cours retirée : la journée du jour en journalier, la dernière heure sinon
                df = _bougies_completes(df) if intervalle == "1d" else df.iloc[:-1]
                if df.empty:
                    continue
                hl_px = contexte.get(c.get("hl_name") or c["symbol"], {}).get("mark_px")
                if S.meme_actif(df["Close"].iloc[-1], hl_px, c.get("hl_name") or "") is False:
                    ecartes.append(f"{c['symbol']} (mauvais ticker {c['ticker']})")
                    continue
                debut = S.debut_propre(df["Close"])
                if debut:
                    ecartes.append(f"{c['symbol']} (historique coupé avant le "
                                   f"{df.index[debut].date()} : changement de token)")
                    df = df.iloc[debut:]
                if len(df) >= S.MM_TENDANCE + S.JOURS_MIN_MM + 10:
                    donnees[c["symbol"]] = df
            except Exception:
                continue
    return donnees


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _indicateurs(df: pd.DataFrame, btc_haussier: pd.Series | None = None) -> pd.DataFrame:
    d = df.copy()
    # Régime du jour (connu à la clôture : aucune donnée future)
    d["btc_haussier"] = (btc_haussier.reindex(d.index, method="ffill")
                         if btc_haussier is not None else np.nan)
    m = S.metriques_series(d["Close"])
    d = d.join(m)
    for sens in ("short", "long"):
        d[f"qual_{sens}"] = S.qualifie(d["perf_1an"], d["pct_sous_mm"], d["pente_mm100"],
                                       d["pire_rebond"], sens)
        d[f"mom_{sens}"] = S.moment_series(d["Close"], sens)
    for cle, s in SORTIES.items():
        d[f"mm_{cle}"] = d["Close"].rolling(s["mm"]).mean()
    d["haut_10"] = d["High"].rolling(JOURS_STOP).max()
    d["bas_10"] = d["Low"].rolling(JOURS_STOP).min()
    return d


_MOTIFS = {"stop": "stop", "duree": f"{JOURS_REF} jours", "fin": "ouvert"}


def _simuler(symbol: str, d: pd.DataFrame, cle: str, sortie: str | None) -> list[dict]:
    """Une stratégie (ou une référence) sur un actif, via le moteur partagé (simulation.py)."""
    from src.utils.simulation import simuler
    ref = cle in REFERENCES or cle in REGIMES          # positions de 20 jours, sans critère
    sens = definition(cle)["sens"]
    signe = -1 if sens == "short" else 1
    if ref:
        signal = d["perf_1an"].notna().to_numpy()
        if cle in REGIMES:
            signal = signal & (d["btc_haussier"] == REGIMES[cle]["btc_haussier"]).to_numpy()
        trades = simuler(d, signal, signe, bougies=JOURS_REF, frais_ar=_FRAIS_AR)
    else:
        moment = S.STRATEGIES[cle]["moment"]
        mm = d[f"mm_{sortie}"]
        # entrée seulement du bon côté de la MM de sortie (sinon coupé dès le lendemain)
        signal = (d[f"qual_{sens}"] & (signe * (d["Close"] - mm) > 0)).to_numpy(bool)
        if moment == "entree":
            signal &= (d[f"mom_{sens}"] == "entree").to_numpy()
        stop = (d["haut_10"] if sens == "short" else d["bas_10"]).to_numpy(float) \
            if moment == "entree" else None
        trades = simuler(d, signal, signe, mm=mm.to_numpy(float), stop_niveau=stop, frais_ar=_FRAIS_AR)
    libelle_mm = f"clôture {'au-dessus' if sens == 'short' else 'sous'} MM"
    return [{
        "symbol": symbol, "strategie": cle, "sortie": sortie or "20j", "sens": sens,
        "entree_date": t["entree"], "entree_px": t["entree_px"],
        "sortie_date": t["sortie"], "sortie_px": t["sortie_px"],
        "motif": libelle_mm if t["motif"] == "mm" else _MOTIFS.get(t["motif"], t["motif"]),
        "rend_pct": t["rend_pct"], "mae_pct": t["mae_pct"], "jours": t["jours"],
    } for t in trades]


def simuler_tout(donnees: dict, progress_cb=None) -> pd.DataFrame:
    combinaisons = ([(k, s) for k in S.STRATEGIES for s in SORTIES]
                    + [(k, None) for k in REFERENCES] + [(k, None) for k in REGIMES])
    btc = donnees.get("BTC")
    btc_haussier = None
    if btc is not None:
        mm = btc["Close"].rolling(MM_REGIME).mean()
        btc_haussier = (btc["Close"] > mm).where(mm.notna())
    else:
        combinaisons = [c for c in combinaisons if c[0] not in REGIMES]
        print("[backtest] BTC absent : filtre de régime non testé")
    trades = []
    for i, (symbol, df) in enumerate(donnees.items()):
        if progress_cb:
            progress_cb(0.6 + 0.35 * i / max(len(donnees), 1), f"Simulation {symbol}…")
        try:
            d = _indicateurs(df, btc_haussier)
        except Exception as e:
            print(f"[backtest] {symbol} ignoré : {e}")
            continue
        for cle, sortie in combinaisons:
            trades.extend(_simuler(symbol, d, cle, sortie))
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Bilan
# ---------------------------------------------------------------------------

def date_coupure(depuis: str = DEPUIS, fin=None) -> pd.Timestamp:
    debut = pd.Timestamp(depuis)
    fin = pd.Timestamp(fin) if fin is not None else pd.Timestamp.now().normalize()
    return debut + (fin - debut) * (1 - PART_TEST)


def bilan(trades: pd.DataFrame, coupure: pd.Timestamp) -> pd.DataFrame:
    """Une ligne par stratégie × sortie × période (Tout / Apprentissage / Test)."""
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    for cle, c in COMBINES.items():
        membres = t[t["strategie"].isin(c["membres"])].copy()
        if not membres.empty:
            membres["strategie"], membres["sortie"] = cle, "20j"
            t = pd.concat([t, membres], ignore_index=True)
    t["periode"] = np.where(pd.to_datetime(t["entree_date"]) < coupure, "Apprentissage", "Test")
    from src.utils.bilan import stats
    lignes = []
    for (cle, sortie), g in t.groupby(["strategie", "sortie"]):
        for periode, gg in [("Tout", g)] + list(g.groupby("periode")):
            st_ = stats(gg, entree="entree_date", duree="jours")
            # Noms des colonnes de la table bt_resume (inchangés : anciens lancements lisibles)
            lignes.append({
                "strategie": cle, "sortie": sortie, "periode": periode,
                "trades": st_["trades"], "actifs": st_["actifs"],
                "gagnants_pct": st_["gagnants"], "rend_moy": st_["rend_moy"], "rend_med": st_["rend_med"],
                "gain_moy": st_["gain_gagnants"], "perte_moy": st_["perte_perdants"],
                "profit_factor": st_["pf"], "mae_med": st_["mae_med"], "mae_p90": st_["mae_p90"],
                "levier_tenable": st_["levier_tenable"], "jours_moy": st_["duree_moy"],
            })
    return pd.DataFrame(lignes)


# ---------------------------------------------------------------------------
# Stockage (PostgreSQL sur Railway, SQLite en local)
# ---------------------------------------------------------------------------

def _engine():
    from src.auth.db import engine
    return engine


def enregistrer(run: str, params: dict, resume: pd.DataFrame, trades: pd.DataFrame) -> None:
    eng = _engine()
    r = resume.copy()
    r.insert(0, "run", run)
    r["params"] = json.dumps(params, ensure_ascii=False)
    r.to_sql(TABLE_RESUME, eng, if_exists="append", index=False)
    if not trades.empty:
        tr = trades.copy()
        tr.insert(0, "run", run)
        tr.to_sql(TABLE_TRADES, eng, if_exists="append", index=False, chunksize=2000)


def _lire(sql: str, **params) -> pd.DataFrame:
    try:
        with _engine().connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)
    except Exception:
        return pd.DataFrame()          # table pas encore créée : aucun backtest lancé


def charger_runs() -> pd.DataFrame:
    return _lire(f"SELECT run, MIN(params) AS params, SUM(trades) AS trades FROM {TABLE_RESUME} "
                 f"WHERE periode = 'Tout' GROUP BY run ORDER BY run DESC")


def charger_resume(run: str | None = None) -> pd.DataFrame:
    if run is None:
        return _lire(f"SELECT * FROM {TABLE_RESUME} ORDER BY run")
    return _lire(f"SELECT * FROM {TABLE_RESUME} WHERE run = :run", run=run)


def charger_trades(run: str) -> pd.DataFrame:
    return _lire(f"SELECT * FROM {TABLE_TRADES} WHERE run = :run", run=run)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def lancer(progress_cb=None, depuis: str = DEPUIS) -> tuple[str, pd.DataFrame]:
    from src.utils.market_data import get_screening_coins

    coins = get_screening_coins()
    ecartes = []
    donnees = telecharger(coins, depuis, progress_cb, ecartes)
    if not donnees:
        raise RuntimeError("aucune donnée Yahoo téléchargée")
    trades = simuler_tout(donnees, progress_cb)
    coupure = date_coupure(depuis)
    resume = bilan(trades, coupure)
    run = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    params = {
        "depuis": depuis, "coupure_test": str(coupure.date()), "actifs": len(donnees),
        "frais_pct_cote": FRAIS_PCT, "glissement_pct_cote": GLISSEMENT_PCT,
        "seuils": S.SEUILS, "mm_courte": S.MM_COURTE, "jours_rebond": S.JOURS_REBOND,
        "ecartes": ecartes, "mm_regime_btc": MM_REGIME,
    }
    if progress_cb:
        progress_cb(0.97, "Enregistrement…")
    enregistrer(run, params, resume, trades)
    return run, resume


if __name__ == "__main__":
    def _p(x, msg):
        print(f"{x:4.0%}  {msg}", flush=True)
    run, resume = lancer(_p)
    pd.set_option("display.width", 200)
    print(f"\nRun {run}")
    print(resume[resume["periode"] != "Tout"].to_string(index=False))
