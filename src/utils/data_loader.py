"""
data_loader.py
Récupération des données OHLCV via yfinance.
La liste des cryptos est lue dynamiquement depuis coins.py à chaque appel
pour refléter les mises à jour sans redémarrage.
"""

import importlib
import importlib.util
import sys
import os
import pandas as pd
import yfinance as yf

INTERVAL_MAP = {
    "heure":   "1h",
    "jour":    "1d",
    "semaine": "1wk",
    "mois":    "1mo",
}

PERIOD_MAP = {
    "heure":   "730d",
    "jour":    "max",
    "semaine": "max",
    "mois":    "max",
}

_COINS_PATH = os.path.join(os.path.dirname(__file__), "coins.py")


def _load_coins_fresh() -> tuple[list[dict], list[dict]]:
    """Relit coins.py depuis le disque — retourne (COINS, INDICES)."""
    spec   = importlib.util.spec_from_file_location("coins_fresh", _COINS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    coins   = getattr(module, "COINS", [])
    indices = getattr(module, "INDICES", [])
    return coins, indices


def _expose(c: dict) -> dict:
    """Format exposé aux pages.

    hl_name = nom de l'actif sur Hyperliquid. Il NE se déduit PAS du ticker
    Yahoo : Hyperliquid est "HYPE" chez HL et "HYPE32196-USD" chez Yahoo.
    Repli sur symbol pour rester compatible avec un coins.py d'ancienne
    génération (avant l'ajout du champ).
    """
    return {
        "id":      c["ticker"],
        "symbol":  c["symbol"],
        "name":    c["name"],
        "hl_name": c.get("hl_name") or c["symbol"],
    }


def get_top100_coins() -> list[dict]:
    """Cryptos uniquement — pour le dropdown app.py et le screener."""
    coins, _ = _load_coins_fresh()
    return [_expose(c) for c in coins]


def get_all_assets() -> list[dict]:
    """Cryptos + indices — pour le backtest app.py dropdown complet."""
    coins, indices = _load_coins_fresh()
    return [_expose(c) for c in coins + indices]


def fetch_ohlcv(coin_id: str, timeframe: str, duree_max_jours: int = 365) -> pd.DataFrame:
    """
    Récupère les données OHLCV via yfinance.

    Args:
        coin_id   : ticker Yahoo Finance (ex: "BTC-USD")
        timeframe : "heure" | "jour" | "semaine" | "mois"

    Returns:
        DataFrame colonnes [open, high, low, close] indexé par datetime naïf
    """
    interval = INTERVAL_MAP.get(timeframe, "1d")
    period   = PERIOD_MAP.get(timeframe, "max")

    df = yf.Ticker(coin_id).history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"Aucune donnée reçue pour {coin_id} (intervalle={interval})")

    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    df = df[["open", "high", "low", "close"]].copy()

    if df.index.tzinfo is not None:
        df.index = df.index.tz_convert(None)

    return df.sort_index().dropna()


def fetch_btc_mm(timeframe: str, period: int, duree_max_jours: int = 365) -> pd.Series:
    """Retourne la MM{period} du BTC-EUR sous forme de Series."""
    df = fetch_ohlcv("BTC-USD", timeframe, duree_max_jours)
    return df["close"].rolling(window=period).mean().rename(f"btc_mm_{period}")
