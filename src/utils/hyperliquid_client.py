"""
hyperliquid_client.py
Client Hyperliquid en class — pour plus tard quand tu passeras à HL.
Même structure que BinanceClient pour cohérence.

Nécessite : pip install hyperliquid-python-sdk eth-account
Clé : clé privée MetaMask dans .env (HL_PRIVATE_KEY + HL_WALLET_ADDRESS)
"""

import os
from dotenv import load_dotenv

load_dotenv()

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_URL = "https://api.hyperliquid.xyz"

HL_ASSETS = [
    "BTC", "ETH", "SOL", "ARB", "OP", "AVAX", "BNB",
    "LINK", "ATOM", "NEAR", "APT", "SUI", "INJ", "DOGE",
    "LTC", "XRP", "DOT", "ADA", "AAVE", "UNI",
]


class HyperliquidClient:
    """
    Client Hyperliquid — perps on-chain.
    Pour l'instant gardé en réserve, le paper trading se fait sur Binance.

    Exemple :
        client = HyperliquidClient(testnet=True)
        price  = client.get_price("BTC")
    """

    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.url     = TESTNET_URL if testnet else MAINNET_URL
        self.pk      = os.getenv("HL_PRIVATE_KEY")
        self.address = os.getenv("HL_WALLET_ADDRESS")

    def _info(self):
        from hyperliquid.info import Info
        return Info(self.url, skip_ws=True)

    def _exchange(self):
        from hyperliquid.exchange import Exchange
        from eth_account import Account
        account = Account.from_key(self.pk)
        return Exchange(account, self.url)

    def test_connection(self) -> dict:
        try:
            info  = self._info()
            mids  = info.all_mids()
            price = float(mids.get("BTC", 0))
            env   = "Testnet" if self.testnet else "Mainnet"
            return {"ok": True, "message": f"✅ Connexion HL {env} OK — BTC : {price:,.0f} $"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def get_price(self, asset: str) -> float | None:
        try:
            mids = self._info().all_mids()
            return float(mids.get(asset, 0)) or None
        except Exception:
            return None

    def get_balance(self) -> float:
        try:
            state  = self._info().user_state(self.address)
            margin = state.get("marginSummary", {})
            return float(margin.get("accountValue", 0))
        except Exception:
            return 0.0

    def buy(self, asset: str, size_usd: float) -> dict:
        price = self.get_price(asset)
        if not price:
            return {"ok": False, "message": "Prix indisponible"}
        size     = round(size_usd / price, 6)
        limit_px = round(price * 1.01, 2)   # slippage 1%
        try:
            result = self._exchange().order(
                asset, True, size, limit_px, {"limit": {"tif": "Ioc"}}
            )
            return {"ok": result.get("status") == "ok", "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def sell(self, asset: str, size: float) -> dict:
        price    = self.get_price(asset)
        limit_px = round(price * 0.99, 2) if price else 0
        try:
            result = self._exchange().order(
                asset, False, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=True
            )
            return {"ok": result.get("status") == "ok", "data": result, "fill_price": price}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}
