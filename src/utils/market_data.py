"""
market_data.py
Données de marché pour le tableau de screening crypto.
Source : yfinance (pas de clé requise).
"""

import pandas as pd
import numpy as np
import yfinance as yf
import importlib.util
import os
from datetime import datetime, timedelta

_COINS_PATH = os.path.join(os.path.dirname(__file__), "coins.py")


def _load_coins_fresh() -> list[dict]:
    spec   = importlib.util.spec_from_file_location("coins_fresh", _COINS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.COINS


# Liste des cryptos — importée depuis coins.py (source unique)
def get_screening_coins() -> list[dict]:
    coins = _load_coins_fresh()
    return [{"ticker": c["ticker"], "symbol": c["symbol"], "name": c["name"]} for c in coins]


# ---------------------------------------------------------------------------
# Chargement des données 30j pour tous les calculs
# ---------------------------------------------------------------------------

def _fetch_closes(ticker: str, days: int = 30) -> pd.Series | None:
    try:
        df = yf.Ticker(ticker).history(period=f"{days}d", interval="1d")
        if df.empty:
            return None
        df.index = df.index.tz_localize(None) if df.index.tzinfo is None else df.index.tz_convert(None)
        return df["Close"]
    except Exception:
        return None


def _correlation_btc(closes: pd.Series, btc_closes: pd.Series) -> float:
    """Corrélation des rendements journaliers avec BTC, ramenée sur [0, 100]."""
    try:
        ret      = closes.pct_change().dropna()
        ret_btc  = btc_closes.pct_change().dropna()
        aligned  = pd.concat([ret, ret_btc], axis=1).dropna()
        if len(aligned) < 5:
            return 0.0
        corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
        # Ramener [-1, 1] → [0, 100]
        return round((corr + 1) / 2 * 100, 1)
    except Exception:
        return 0.0


def _volatility(closes: pd.Series, btc_closes: pd.Series) -> float:
    """
    Volatilité absolue de l'alt sur une échelle [1, 5].
    Basée sur l'écart-type des rendements journaliers, normalisé
    par rapport à la distribution observée des cryptos.

    Points de référence (rendements journaliers std) :
        < 1%  → 1  (très calme, stablecoin)
        2%    → 2  (calme, comme ETH/BTC)
        4%    → 3  (modéré)
        7%    → 4  (agité)
        ≥ 12% → 5  (très agité, petite cap)
    """
    try:
        std_pct = closes.pct_change().dropna().std() * 100  # en %
        breakpoints = [0.0, 1.0, 2.0, 4.0, 7.0, 12.0]
        scores      = [1.0, 1.0, 2.0, 3.0, 4.0,  5.0]
        scaled = float(np.interp(std_pct, breakpoints, scores))
        return round(min(scaled, 5.0), 2)
    except Exception:
        return 3.0


def _beta_vs_btc(closes: pd.Series, btc_closes: pd.Series) -> float:
    """
    Bêta de l'alt par rapport au BTC.
    Bêta = cov(alt, btc) / var(btc)
    Interprétation : quand BTC bouge de 1%, l'alt bouge de bêta %.

    Ramené sur une échelle [1, 5] :
        1   → bêta ≤ 0.5   (bouge moitié moins que BTC)
        2   → bêta ≈ 1.0   (suit BTC)
        3   → bêta ≈ 2.0
        4   → bêta ≈ 3.5
        5   → bêta ≥ 5.0   (bouge 5x plus que BTC)
    """
    try:
        ret_alt = closes.pct_change().dropna()
        ret_btc = btc_closes.pct_change().dropna()
        aligned = pd.concat([ret_alt, ret_btc], axis=1).dropna()
        aligned.columns = ["alt", "btc"]
        if len(aligned) < 5:
            return 3.0
        var_btc = aligned["btc"].var()
        if var_btc == 0:
            return 3.0
        cov = aligned["alt"].cov(aligned["btc"])
        beta = abs(cov / var_btc)          # valeur absolue pour les alts inversés
        # Échelle : bêta → [1, 5]
        # Points de référence : 0.5→1, 1→2, 2→3, 3.5→4, 5→5
        breakpoints = [0.0, 0.5, 1.0, 2.0, 3.5, 5.0]
        scores      = [1.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        scaled = float(np.interp(beta, breakpoints, scores))
        return round(min(scaled, 5.0), 2)
    except Exception:
        return 3.0


def _sparkline_data(closes: pd.Series) -> list[float]:
    """Dernières 7 valeurs normalisées [0-100] pour le mini-graphe."""
    last7 = closes.tail(7)
    if len(last7) < 2:
        return []
    mn, mx = last7.min(), last7.max()
    if mx == mn:
        return [50.0] * len(last7)
    return [(v - mn) / (mx - mn) * 100 for v in last7]


def _perf_7d(closes: pd.Series) -> float:
    """Performance sur 7 jours en %."""
    last7 = closes.tail(8)
    if len(last7) < 2:
        return 0.0
    return round((last7.iloc[-1] - last7.iloc[0]) / last7.iloc[0] * 100, 2)


# ---------------------------------------------------------------------------
# Récupération infos marché (market cap, volume) via yfinance fast_info
# ---------------------------------------------------------------------------

def _market_info(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).fast_info
        return {
            "market_cap": getattr(info, "market_cap", None),
            "volume_24h": getattr(info, "three_month_average_volume", None),
        }
    except Exception:
        return {"market_cap": None, "volume_24h": None}


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def load_screening_data(progress_cb=None) -> pd.DataFrame:
    """
    Charge toutes les données et retourne un DataFrame prêt à afficher.
    Relit coins.py à chaque appel pour refléter les mises à jour.
    """
    btc_closes = _fetch_closes("BTC-EUR", days=30)
    if btc_closes is None:
        return pd.DataFrame()

    rows  = []
    coins = get_screening_coins()
    total = len(coins)

    for idx, coin in enumerate(coins):
        if progress_cb:
            progress_cb((idx + 1) / total, f"Chargement {coin['symbol']}...")

        closes = _fetch_closes(coin["ticker"], days=30)
        if closes is None:
            continue

        minfo    = _market_info(coin["ticker"])
        corr     = _correlation_btc(closes, btc_closes)
        vol_rel  = _beta_vs_btc(closes, btc_closes)
        vol_abs  = _volatility(closes, btc_closes)
        spark    = _sparkline_data(closes)
        perf_7d  = _perf_7d(closes)

        rows.append({
            "symbol":      coin["symbol"],
            "name":        coin["name"],
            "ticker":      coin["ticker"],
            "corr_btc":    corr,
            "beta":        vol_rel,
            "volatility":  vol_abs,
            "market_cap":  minfo["market_cap"],
            "volume_24h":  minfo["volume_24h"],
            "perf_7d":     perf_7d,
            "sparkline":   spark,
            "closes_7d":   closes.tail(7).tolist(),
        })

    return pd.DataFrame(rows)
