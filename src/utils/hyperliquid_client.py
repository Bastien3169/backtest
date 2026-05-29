"""
hyperliquid_client.py
Client Hyperliquid mainnet — perps on-chain.
Même structure que BinanceClient pour cohérence.

Utilise le SDK officiel hyperliquid-python-sdk (compatible Python 3.12 ✅)

Prérequis :
    pip install hyperliquid-python-sdk

Clés dans Railway Variables (ou .env local) :
    HL_PRIVATE_KEY    = clé privée du wallet API (0x...)
    HL_WALLET_ADDRESS = adresse MetaMask principale (0x...)
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

load_dotenv()

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
# Correspondance timeframe → interval HL
TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "heure": "1h",
    "4h": "4h",
    "1d": "1d", "jour": "1d",
    "1w": "1w", "semaine": "1w",
}

# Durée en ms par bougie
TF_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "heure": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000, "jour": 86_400_000,
    "1w": 604_800_000, "semaine": 604_800_000,
}

# Paires disponibles sur HL perps
HL_ASSETS = [
    "BTC", "ETH", "SOL", "ARB", "OP", "AVAX", "BNB",
    "LINK", "ATOM", "NEAR", "APT", "SUI", "INJ", "DOGE",
    "LTC", "XRP", "DOT", "ADA", "AAVE", "UNI",
]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class HyperliquidClient:
    """
    Client Hyperliquid mainnet — perps on-chain.

    Exemple :
        client = HyperliquidClient()
        price  = client.get_price("BTC")
        df     = client.get_klines("BTC", "1h", limit=300)
        order  = client.buy("BTC", size_usd=100)
    """

    def __init__(self):
        self.url     = constants.MAINNET_API_URL
        self.pk      = os.getenv("HL_PRIVATE_KEY", "")
        self.address = os.getenv("HL_WALLET_ADDRESS", "")
        self._wallet   = Account.from_key(self.pk) if self.pk else None
        self._exchange = Exchange(
            self._wallet,
            self.url,
            account_address=self.address
        ) if self._wallet else None

    # ── Helpers HTTP — lecture publique ──────────────────────────────────

    def _post_info(self, payload: dict) -> dict | list:
        """POST vers /info — lecture publique, pas de signature."""
        r = requests.post(
            f"{self.url}/info",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    # ── Test connexion ────────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Ping + prix BTC."""
        try:
            mids  = self._post_info({"type": "allMids"})
            price = float(mids.get("BTC", 0))
            return {"ok": True, "message": f"✅ Connexion HL Mainnet OK — BTC : {price:,.0f} $"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── Prix ──────────────────────────────────────────────────────────────

    def get_price(self, asset: str) -> float | None:
        """Retourne le dernier prix mid d'un actif."""
        try:
            mids = self._post_info({"type": "allMids"})
            return float(mids.get(asset, 0)) or None
        except Exception:
            return None

    # ── Solde ─────────────────────────────────────────────────────────────

    def get_balance(self, asset: str = "USDC") -> float:
        """
        Retourne le solde disponible en USDC.
        Utilise spotClearinghouseState car le compte est en mode Unified Account —
        les fonds spot et perps sont dans le même compte.
        """
        try:
            state    = self._post_info({"type": "spotClearinghouseState", "user": self.address})
            balances = state.get("balances", [])
            for b in balances:
                if b.get("coin") == asset:
                    return float(b.get("total", 0))
            return 0.0
        except Exception:
            return 0.0

    # ── Bougies OHLCV ─────────────────────────────────────────────────────

    def get_klines(self, asset: str, timeframe: str = "1h", limit: int = 300) -> pd.DataFrame:
        """
        Récupère les bougies OHLCV depuis Hyperliquid.
        Retourne un DataFrame avec colonnes [open, high, low, close, volume].
        La DERNIÈRE bougie (iloc[-1]) est en cours de formation.
        La AVANT-DERNIÈRE (iloc[-2]) est la dernière bougie complète.
        """
        interval = TF_MAP.get(timeframe, "1h")
        ms       = TF_MS.get(timeframe, 3_600_000)
        end_ms   = int(time.time() * 1000)
        start_ms = end_ms - limit * ms

        try:
            candles = self._post_info({
                "type": "candleSnapshot",
                "req": {
                    "coin":      asset,
                    "interval":  interval,
                    "startTime": start_ms,
                    "endTime":   end_ms,
                }
            })

            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles)
            df = df.rename(columns={
                "o": "open", "h": "high", "l": "low",
                "c": "close", "v": "volume", "t": "open_time",
            })
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df = df.set_index("open_time")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            print(f"Erreur get_klines {asset}: {e}")
            return pd.DataFrame()

    # ── Ordres via SDK ────────────────────────────────────────────────────

    def buy(self, asset: str, size_usd: float) -> dict:
        """
        Achat market (IOC limit avec slippage 1%).
        size_usd : montant en USDC à investir.
        Ouvre une position LONG.
        """
        try:
            price    = self.get_price(asset)
            if not price:
                return {"ok": False, "message": "Prix indisponible", "fill_price": 0}
            size     = round(size_usd / price, 5)
            limit_px = int(price * 1.01)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, True, size, limit_px, {"limit": {"tif": "Ioc"}}
            )
            ok = result.get("status") == "ok"
            return {"ok": ok, "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def sell(self, asset: str, size: float) -> dict:
        """
        Vente market (IOC limit avec slippage 1%).
        size : quantité d'asset à vendre.
        Ferme une position LONG (reduce_only=True).
        """
        try:
            price    = self.get_price(asset)
            if not price:
                return {"ok": False, "message": "Prix indisponible", "fill_price": 0}
            limit_px = int(price * 0.99)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, False, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=True
            )
            ok = result.get("status") == "ok"
            return {"ok": ok, "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def short(self, asset: str, size_usd: float) -> dict:
        """
        Ouverture d'une position SHORT (vente sans reduce_only).
        size_usd : montant en USDC.
        """
        try:
            price    = self.get_price(asset)
            if not price:
                return {"ok": False, "message": "Prix indisponible", "fill_price": 0}
            size     = round(size_usd / price, 5)
            limit_px = int(price * 0.99)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, False, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=False
            )
            ok = result.get("status") == "ok"
            return {"ok": ok, "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def close_short(self, asset: str, size: float) -> dict:
        """
        Ferme une position SHORT (achat avec reduce_only=True).
        size : quantité d'asset à racheter.
        """
        try:
            price    = self.get_price(asset)
            if not price:
                return {"ok": False, "message": "Prix indisponible", "fill_price": 0}
            limit_px = int(price * 1.01)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, True, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=True
            )
            ok = result.get("status") == "ok"
            return {"ok": ok, "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}
