"""
binance_client.py
Client Binance en class — fonctionne en testnet ET mainnet.
Utilise python-binance (pip install python-binance).

Testnet : https://testnet.binance.vision (clé gratuite, faux argent)
Mainnet : https://binance.com (clé payante, vrai argent)
"""

import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Paires disponibles sur Binance Spot (USDT comme quote)
BINANCE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT", "MATICUSDT",
    "OPUSDT",  "ARBUSDT",  "INJUSDT",  "SUIUSDT",  "AAVEUSDT",
]

# Correspondance timeframe → interval Binance
TF_MAP = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "jour": "1d",
    "heure": "1h",
}


class BinanceClient:
    """
    Client Binance réutilisable pour testnet et mainnet.
    
    Exemple d'utilisation :
        client = BinanceClient(testnet=True)
        price  = client.get_price("BTCUSDT")
        order  = client.buy("BTCUSDT", qty=0.001)
    """

    def __init__(self, testnet: bool = True):
        from binance.client import Client
        self.testnet = testnet
        if testnet:
            api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
            secret  = os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
        else:
            api_key = os.getenv("BINANCE_API_KEY", "")
            secret  = os.getenv("BINANCE_API_SECRET", "")
        self.client = Client(api_key, secret, testnet=testnet)

    # ── Prix ──────────────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> float | None:
        """Retourne le dernier prix d'un symbole."""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            print(f"Erreur get_price {symbol}: {e}")
            return None

    # ── Solde ─────────────────────────────────────────────────────────────

    def get_balance(self, asset: str = "USDT") -> float:
        """Retourne le solde disponible d'un actif."""
        try:
            bal = self.client.get_asset_balance(asset=asset)
            return float(bal["free"])
        except Exception as e:
            print(f"Erreur get_balance {asset}: {e}")
            return 0.0

    def get_all_balances(self) -> dict:
        """Retourne tous les soldes non nuls."""
        try:
            account  = self.client.get_account()
            balances = {
                b["asset"]: float(b["free"])
                for b in account["balances"]
                if float(b["free"]) > 0
            }
            return balances
        except Exception as e:
            print(f"Erreur get_all_balances: {e}")
            return {}

    # ── Ordres ────────────────────────────────────────────────────────────

    def buy(self, symbol: str, qty: float) -> dict | None:
        """Achat market."""
        try:
            order = self.client.order_market_buy(symbol=symbol, quantity=round(qty, 6))
            fill  = float(order.get("fills", [{}])[0].get("price", 0))
            return {"ok": True, "order": order, "fill_price": fill}
        except Exception as e:
            print(f"Erreur buy {symbol}: {e}")
            return {"ok": False, "message": str(e), "fill_price": 0}

    def sell(self, symbol: str, qty: float) -> dict | None:
        """Vente market."""
        try:
            order = self.client.order_market_sell(symbol=symbol, quantity=round(qty, 6))
            fill  = float(order.get("fills", [{}])[0].get("price", 0))
            return {"ok": True, "order": order, "fill_price": fill}
        except Exception as e:
            print(f"Erreur sell {symbol}: {e}")
            return {"ok": False, "message": str(e), "fill_price": 0}

    # ── Données OHLCV ─────────────────────────────────────────────────────

    def get_klines(self, symbol: str, timeframe: str = "1h", limit: int = 300) -> pd.DataFrame:
        """
        Récupère les bougies OHLCV depuis Binance.
        Retourne un DataFrame avec colonnes [open, high, low, close, volume].
        La DERNIÈRE bougie (iloc[-1]) est en cours de formation.
        La AVANT-DERNIÈRE (iloc[-2]) est la dernière bougie complète.
        """
        interval = TF_MAP.get(timeframe, "1h")
        try:
            klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
            df = pd.DataFrame(klines, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df = df.set_index("open_time")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            print(f"Erreur get_klines {symbol}: {e}")
            return pd.DataFrame()

    # ── Test connexion ────────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Ping + prix BTC."""
        try:
            self.client.ping()
            price = self.get_price("BTCUSDT")
            env   = "Testnet" if self.testnet else "Mainnet"
            return {"ok": True, "message": f"✅ Connexion {env} OK — BTC : {price:,.2f} USDT"}
        except Exception as e:
            return {"ok": False, "message": str(e)}
