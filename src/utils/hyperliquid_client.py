"""
hyperliquid_client.py
Client Hyperliquid mainnet — perps on-chain.
Même structure que BinanceClient pour cohérence.

Utilise le SDK officiel hyperliquid-python-sdk (compatible Python 3.12 ✅)

Prérequis :
    pip install hyperliquid-python-sdk

Clés dans Railway Variables (ou .env local) :

    Pour le bot LONG :
        LONG_METAMASK_ADDRESS  = adresse MetaMask bot_long (0xF06b...)
        LONG_HL_PRIVATE_KEY    = clé privée wallet API HL bot_long

    Pour le bot SHORT :
        SHORT_METAMASK_ADDRESS = adresse MetaMask bot_short (0x4Aad...)
        SHORT_HL_PRIVATE_KEY   = clé privée wallet API HL bot_short

    Ancien format encore supporté (compatibilité) :
        HL_PRIVATE_KEY    = clé privée wallet API
        HL_WALLET_ADDRESS = adresse MetaMask
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

    def __init__(self, side: str = "long"):
        """
        side : "long" ou "short" — détermine quelles clés utiliser.
        Fallback sur HL_PRIVATE_KEY / HL_WALLET_ADDRESS si les nouvelles clés sont absentes.
        """
        self.url  = constants.MAINNET_API_URL
        self.side = side.lower()

        if self.side == "short":
            self.pk      = os.getenv("SHORT_HL_PRIVATE_KEY") or os.getenv("HL_PRIVATE_KEY", "")
            self.address = os.getenv("SHORT_METAMASK_ADDRESS") or os.getenv("HL_WALLET_ADDRESS", "")
        elif self.side == "free":
            self.pk      = os.getenv("FREE_HL_PRIVATE_KEY") or os.getenv("HL_PRIVATE_KEY", "")
            self.address = os.getenv("FREE_METAMASK_ADDRESS") or os.getenv("HL_WALLET_ADDRESS", "")
        else:
            self.pk      = os.getenv("LONG_HL_PRIVATE_KEY") or os.getenv("HL_PRIVATE_KEY", "")
            self.address = os.getenv("LONG_METAMASK_ADDRESS") or os.getenv("HL_WALLET_ADDRESS", "")

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
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            has_error = any("error" in s for s in statuses)
            ok = result.get("status") == "ok" and not has_error
            return {"ok": ok, "data": result, "fill_price": price,
                    "error": statuses[0].get("error") if has_error else None}
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
            size     = round(size, 5)      # HL exige max 5 décimales
            limit_px = int(price * 0.99)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, False, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=True
            )
            # Vérifier qu'il n'y a pas d'erreur dans les statuses
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            has_error = any("error" in s for s in statuses)
            ok = result.get("status") == "ok" and not has_error
            return {"ok": ok, "data": result, "fill_price": price,
                    "error": statuses[0].get("error") if has_error else None}
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
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            has_error = any("error" in s for s in statuses)
            ok = result.get("status") == "ok" and not has_error
            return {"ok": ok, "data": result, "fill_price": price,
                    "error": statuses[0].get("error") if has_error else None}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def set_leverage(self, asset: str, leverage: int) -> dict:
        """
        Configure le levier pour un actif sur HL (Isolated margin).
        À appeler avant d'ouvrir une position.
        leverage : entier entre 1 et 50
        """
        try:
            result = self._exchange.update_leverage(leverage, asset, is_cross=False)
            ok = result.get("status") == "ok"
            print(f"Levier {leverage}x sur {asset} : {'✅' if ok else '❌'} {result}")
            return {"ok": ok, "data": result}
        except Exception as e:
            print(f"Erreur set_leverage : {e}")
            return {"ok": False, "message": str(e)}

    def set_tp_sl(self, asset: str, size: float, is_short: bool,
                  tp_price: float = None, sl_price: float = None) -> dict:
        """
        Place des ordres TP et SL natifs sur HL — exécutés en temps réel par la plateforme.
        Ces ordres sont indépendants du bot — ils restent actifs même si le bot s'arrête.

        asset    : "BTC", "ETH"...
        size     : quantité de l'asset (qty de la position)
        is_short : True si position short, False si long
        tp_price : prix de take profit (None = pas de TP)
        sl_price : prix de stop loss (None = pas de SL)

        Format HL :
        - triggerPx doit être une STRING
        - limit_px doit être agressif : pour SL long → limit < trigger, pour SL short → limit > trigger
        - grouping "positionTpsl" lie les ordres à la position
        """
        results = {}
        try:
            size = round(size, 5)  # HL exige max 5 décimales pour les ordres trigger
            # Pour un LONG : fermer = vendre (is_buy=False)
            # Pour un SHORT : fermer = acheter (is_buy=True)
            is_buy_to_close = is_short

            if tp_price:
                tp_px = int(tp_price)
                # limit_px agressif : pour TP long on vend → limit bas / pour TP short on achète → limit haut
                tp_limit = int(tp_px * 0.995) if not is_short else int(tp_px * 1.005)
                tp_result = self._exchange.order(
                    asset,
                    is_buy_to_close,
                    size,
                    tp_limit,
                    {
                        "trigger": {
                            "triggerPx": float(tp_px),
                            "isMarket": True,
                            "tpsl": "tp",
                        }
                    },
                    reduce_only=True,
                )
                results["tp"] = tp_result
                tp_ok = tp_result.get("status") == "ok"
                print(f"TP natif @ {tp_px} : {'✅' if tp_ok else '❌'} {tp_result}")

            if sl_price:
                sl_px = int(sl_price)
                # limit_px agressif : pour SL long on vend → limit très bas / pour SL short on achète → limit très haut
                sl_limit = int(sl_px * 0.995) if not is_short else int(sl_px * 1.005)
                sl_result = self._exchange.order(
                    asset,
                    is_buy_to_close,
                    size,
                    sl_limit,
                    {
                        "trigger": {
                            "triggerPx": float(sl_px),
                            "isMarket": True,
                            "tpsl": "sl",
                        }
                    },
                    reduce_only=True,
                )
                results["sl"] = sl_result
                sl_ok = sl_result.get("status") == "ok"
                print(f"SL natif @ {sl_px} : {'✅' if sl_ok else '❌'} {sl_result}")

            # Vérifier les statuses individuels TP et SL
            tp_ok = False
            sl_ok = False
            if "tp" in results:
                tp_statuses = results["tp"].get("response", {}).get("data", {}).get("statuses", [])
                tp_ok = results["tp"].get("status") == "ok" and not any("error" in s for s in tp_statuses)
            if "sl" in results:
                sl_statuses = results["sl"].get("response", {}).get("data", {}).get("statuses", [])
                sl_ok = results["sl"].get("status") == "ok" and not any("error" in s for s in sl_statuses)

            return {"ok": True, "tp_ok": tp_ok, "sl_ok": sl_ok, "results": results}

        except Exception as e:
            print(f"Erreur set_tp_sl : {e}")
            return {"ok": False, "tp_ok": False, "sl_ok": False, "message": str(e)}

    def close_short(self, asset: str, size: float) -> dict:
        """
        Ferme une position SHORT (achat avec reduce_only=True).
        size : quantité d'asset à racheter.
        """
        try:
            price    = self.get_price(asset)
            if not price:
                return {"ok": False, "message": "Prix indisponible", "fill_price": 0}
            size     = round(size, 5)      # HL exige max 5 décimales
            limit_px = int(price * 1.01)   # HL exige un entier pour BTC
            result   = self._exchange.order(
                asset, True, size, limit_px,
                {"limit": {"tif": "Ioc"}}, reduce_only=True
            )
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            has_error = any("error" in s for s in statuses)
            ok = result.get("status") == "ok" and not has_error
            return {"ok": ok, "data": result, "fill_price": price,
                    "error": statuses[0].get("error") if has_error else None}
        except Exception as e:
            return {"ok": False, "message": str(e), "fill_price": 0}

    def get_open_positions(self) -> list:
        """
        Source de verite : positions REELLEMENT ouvertes sur ce wallet, lues en
        direct depuis Hyperliquid (clearinghouseState). Independant de tout JSON.

        Retourne une liste de dicts, ou [] si aucune position.
        Leve une exception si l'API est injoignable -- l'appelant doit decider
        quoi faire (surtout ne PAS conclure "aucune position").
        """
        state = self._post_info({"type": "clearinghouseState", "user": self.address})
        raw = state.get("assetPositions", []) if isinstance(state, dict) else []

        positions = []
        for item in raw:
            pos = item.get("position", {}) or {}
            try:
                szi = float(pos.get("szi", 0) or 0)
            except (TypeError, ValueError):
                szi = 0.0
            if szi == 0:
                continue

            is_short = szi < 0
            qty      = abs(szi)

            def _f(key, default=0.0):
                try:
                    v = pos.get(key)
                    return float(v) if v not in (None, "") else default
                except (TypeError, ValueError):
                    return default

            entry_price = _f("entryPx")
            lev_raw     = pos.get("leverage")
            lev_val     = lev_raw.get("value") if isinstance(lev_raw, dict) else lev_raw
            liq_raw     = pos.get("liquidationPx")

            positions.append({
                "symbol":         pos.get("coin", "?"),
                "side":           "SHORT" if is_short else "LONG",
                "is_short":       is_short,
                "qty":            qty,
                "entry_price":    entry_price,
                # notional coherent avec qty -- utilise par les calculs de PnL
                "size_usdt":      round(qty * entry_price, 2),
                "unrealized_pnl": _f("unrealizedPnl"),
                "margin_used":    _f("marginUsed"),
                "leverage":       lev_val,
                "liquidation_px": float(liq_raw) if liq_raw not in (None, "") else None,
            })
        return positions

    def get_position(self, asset: str) -> dict | None:
        """
        Position reelle sur un symbole precis, ou None si aucune.
        Leve une exception si l'API est injoignable (voir get_open_positions).
        """
        asset = (asset or "").replace("-USD", "").replace("USDT", "")
        for p in self.get_open_positions():
            if p["symbol"] == asset:
                return p
        return None
