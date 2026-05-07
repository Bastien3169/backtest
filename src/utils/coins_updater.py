"""
coins_updater.py
Récupère le top 100 CoinGecko, teste chaque ticker sur yfinance,
et met à jour coins.py avec les cryptos disponibles.
"""

import requests
import yfinance as yf
import json
import os

COINGECKO_TOP100_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false"
)

COINS_FILE = os.path.join(os.path.dirname(__file__), "coins.py")


def fetch_top100_coingecko() -> list[dict]:
    """Récupère le top 100 CoinGecko par market cap."""
    resp = requests.get(COINGECKO_TOP100_URL, timeout=15)
    resp.raise_for_status()
    return resp.json()


def test_yfinance_ticker(ticker: str) -> bool:
    """Retourne True si yfinance a des données pour ce ticker."""
    try:
        df = yf.Ticker(ticker).history(period="7d", interval="1d")
        return not df.empty
    except Exception:
        return False


def update_coins(progress_cb=None) -> tuple[list[dict], list[str]]:
    """
    Récupère le top 100 CoinGecko, teste chaque ticker sur yfinance,
    et réécrit coins.py avec les disponibles.

    Returns:
        (available, skipped) : listes des coins retenus et ignorés
    """
    raw = fetch_top100_coingecko()
    total = len(raw)
    available = []
    skipped = []

    for idx, coin in enumerate(raw):
        symbol = coin["symbol"].upper()
        name   = coin["name"]
        ticker = f"{symbol}-USD"

        if progress_cb:
            progress_cb(
                (idx + 1) / total,
                f"Test {ticker} ({idx+1}/{total})..."
            )

        if test_yfinance_ticker(ticker):
            available.append({
                "ticker": ticker,
                "symbol": symbol,
                "name":   name,
            })
        else:
            skipped.append(ticker)

    # Réécrire coins.py
    _write_coins_file(available)

    return available, skipped


def _write_coins_file(coins: list[dict]):
    """Réécrit coins.py avec la nouvelle liste."""
    lines = [
        '"""',
        'coins.py',
        'Source unique de vérité pour la liste des cryptos supportées.',
        'Généré automatiquement par coins_updater.py — ne pas éditer à la main.',
        '"""',
        '',
        'COINS = [',
    ]
    for c in coins:
        lines.append(
            f'    {{"ticker": "{c["ticker"]}", "symbol": "{c["symbol"]}", "name": "{c["name"]}"}},',
        )
    lines.append(']')
    lines.append('')

    with open(COINS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
