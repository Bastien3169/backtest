"""
data_loader.py
Récupération des données OHLCV depuis CoinGecko.
Fournit la liste des top 100 cryptos et les données historiques.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

TIMEFRAME_MAP = {
    "heure":   "hourly",
    "jour":    "daily",
    "semaine": "weekly",
    "mois":    "monthly",
}

# ---------------------------------------------------------------------------
# Top 100 CoinGecko
# ---------------------------------------------------------------------------

def get_top100_coins() -> list[dict]:
    """
    Retourne la liste des 100 premières cryptos par market cap.
    Chaque élément : {"id": str, "symbol": str, "name": str}
    """
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {
        "vs_currency": "eur",
        "order": "market_cap_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": False,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [{"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"]} for c in data]


# ---------------------------------------------------------------------------
# Données OHLCV
# ---------------------------------------------------------------------------

def _days_for_timeframe(timeframe: str, duree_max: int) -> int:
    """Calcule le nombre de jours d'historique à charger."""
    multipliers = {"heure": 1, "jour": 1, "semaine": 7, "mois": 30}
    m = multipliers.get(timeframe, 1)
    return max(duree_max * m + 10, 365)


def fetch_btc_mm(timeframe: str, period: int, duree_max_jours: int = 365) -> pd.Series:
    """
    Récupère la MM{period} du BTC en EUR.
    Retourne une Series indexée par timestamp.
    """
    df = fetch_ohlcv("bitcoin", timeframe, duree_max_jours)
    return df["close"].rolling(window=period).mean().rename(f"btc_mm_{period}")


def fetch_ohlcv(coin_id: str, timeframe: str, duree_max_jours: int = 365) -> pd.DataFrame:
    """
    Récupère les données OHLCV pour une crypto donnée.

    Args:
        coin_id      : identifiant CoinGecko (ex: "bitcoin")
        timeframe    : "heure" | "jour" | "semaine" | "mois"
        duree_max_jours: nombre de jours d'historique souhaité

    Returns:
        DataFrame avec colonnes [timestamp, open, high, low, close, volume]
    """
    days = _days_for_timeframe(timeframe, duree_max_jours)
    # CoinGecko OHLC endpoint (bougies)
    url = f"{COINGECKO_BASE}/coins/{coin_id}/ohlc"
    # CoinGecko ne supporte que 1/7/14/30/90/180/365 jours
    allowed = [1, 7, 14, 30, 90, 180, 365]
    api_days = min([d for d in allowed if d >= min(days, 365)], default=365)

    params = {"vs_currency": "eur", "days": api_days}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()  # [[timestamp_ms, open, high, low, close], ...]

    df = pd.DataFrame(raw, columns=["timestamp_ms", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms")
    df = df.drop(columns=["timestamp_ms"])
    df = df.set_index("timestamp").sort_index()

    # Ré-échantillonnage selon la temporalité
    if timeframe == "semaine":
        df = df.resample("W").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    elif timeframe == "mois":
        df = df.resample("ME").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    # "heure" et "jour" : données natives CoinGecko déjà correctes

    df = df.dropna()
    return df
