"""
data_loader.py
Récupération des données OHLCV via yfinance (Yahoo Finance).
Pas de clé API requise.
"""

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Liste des principales cryptos (symbol Yahoo Finance → label affiché)
# ---------------------------------------------------------------------------
TOP_COINS = [
    {"id": "BTC-EUR",  "symbol": "BTC",  "name": "Bitcoin"},
    {"id": "ETH-EUR",  "symbol": "ETH",  "name": "Ethereum"},
    {"id": "BNB-EUR",  "symbol": "BNB",  "name": "BNB"},
    {"id": "SOL-EUR",  "symbol": "SOL",  "name": "Solana"},
    {"id": "XRP-EUR",  "symbol": "XRP",  "name": "XRP"},
    {"id": "ADA-EUR",  "symbol": "ADA",  "name": "Cardano"},
    {"id": "AVAX-EUR", "symbol": "AVAX", "name": "Avalanche"},
    {"id": "DOGE-EUR", "symbol": "DOGE", "name": "Dogecoin"},
    {"id": "DOT-EUR",  "symbol": "DOT",  "name": "Polkadot"},
    {"id": "LINK-EUR", "symbol": "LINK", "name": "Chainlink"},
    {"id": "LTC-EUR",  "symbol": "LTC",  "name": "Litecoin"},
    {"id": "UNI-EUR",  "symbol": "UNI",  "name": "Uniswap"},
    {"id": "ATOM-EUR", "symbol": "ATOM", "name": "Cosmos"},
    {"id": "XLM-EUR",  "symbol": "XLM",  "name": "Stellar"},
    {"id": "NEAR-EUR", "symbol": "NEAR", "name": "NEAR Protocol"},
    {"id": "OP-EUR",   "symbol": "OP",   "name": "Optimism"},
    {"id": "FIL-EUR",  "symbol": "FIL",  "name": "Filecoin"},
    {"id": "VET-EUR",  "symbol": "VET",  "name": "VeChain"},
    {"id": "ALGO-EUR", "symbol": "ALGO", "name": "Algorand"},
    {"id": "EOS-EUR",  "symbol": "EOS",  "name": "EOS"},
]

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


def get_top100_coins() -> list[dict]:
    return TOP_COINS


def fetch_ohlcv(coin_id: str, timeframe: str, duree_max_jours: int = 365) -> pd.DataFrame:
    """
    Récupère les données OHLCV via yfinance.

    Args:
        coin_id   : ticker Yahoo Finance (ex: "BTC-EUR")
        timeframe : "heure" | "jour" | "semaine" | "mois"

    Returns:
        DataFrame colonnes [open, high, low, close] indexé par datetime naïf
    """
    interval = INTERVAL_MAP.get(timeframe, "1d")
    period   = PERIOD_MAP.get(timeframe, "max")

    ticker = yf.Ticker(coin_id)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"Aucune donnée reçue pour {coin_id} (intervalle={interval})")

    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    df = df[["open", "high", "low", "close"]].copy()

    # Supprimer timezone pour éviter les conflits lors des joins
    if df.index.tzinfo is not None:
        df.index = df.index.tz_convert(None)

    df = df.sort_index().dropna()
    return df


def fetch_btc_mm(timeframe: str, period: int, duree_max_jours: int = 365) -> pd.Series:
    """Retourne la MM{period} du BTC-EUR sous forme de Series."""
    df = fetch_ohlcv("BTC-EUR", timeframe, duree_max_jours)
    return df["close"].rolling(window=period).mean().rename(f"btc_mm_{period}")
