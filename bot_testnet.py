"""
bot_testnet.py
Paper trading sur Binance TESTNET — faux argent, vrais ordres

Identique à bot_mainnet.py mais :
- Connexion sur testnet.binance.vision (faux argent)
- Clés API testnet (gratuites, sans KYC)
- Pas de plafond sur la taille des trades

Prérequis :
1. Aller sur https://testnet.binance.vision
2. Connexion GitHub → Generate HMAC_SHA256 Key
3. Ajouter dans .env :
   BINANCE_TESTNET_API_KEY=...
   BINANCE_TESTNET_SECRET_KEY=...
   (Tu reçois automatiquement du BTC et ETH fictifs)

Lancement : python bot_testnet.py
Lancement multi-bot : python bot_testnet.py --config bot_state_testnet_long.json
"""

# ── Imports ────────────────────────────────────────────────────────────────────
import sys
import os
import time
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import bot_state as _bs
from src.utils.bot_state import get_state, save_state, log
from src.utils.binance_client import BinanceClient
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal

# ── Config --config ────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--config", default="bot_state.json")
args, _ = parser.parse_known_args()

if os.path.isabs(args.config):
    _bs.STATE_FILE = args.config
else:
    _bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)

# Préfixe de log — ex: "bot_state_testnet_long.json" → "[TESTNET-LONG]"
config_name = args.config.replace("bot_state_", "").replace(".json", "").upper()
BOT_PREFIX  = f"[{config_name}]"


# ── Timing ─────────────────────────────────────────────────────────────────────
SLEEP_MAP = {
    "1m":      60,
    "5m":      300,
    "15m":     900,
    "heure":   1800,
    "1h":      1800,
    "4h":      7200,
    "jour":    86400,
    "1d":      86400,
    "semaine": 604800,
    "1w":      604800,
}


def wait_until_next_check(timeframe: str, check_time_utc: str | None, interval_min: int | None):
    """
    Attend jusqu'au prochain check selon la config :
    - check_time_utc : heure UTC fixe (ex: "00:01") → se réveille chaque jour à cette heure
    - interval_min   : intervalle en minutes (ex: 15) → vérifie toutes les X minutes
    - si les deux sont None → fallback sur SLEEP_MAP selon le timeframe
    """
    now = datetime.now(timezone.utc)

    if check_time_utc:
        h, m   = map(int, check_time_utc.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        sleep_sec = (target - now).total_seconds()
        log(
            f"{BOT_PREFIX} 💤 Prochain check à {check_time_utc} UTC "
            f"(dans {int(sleep_sec // 3600)}h {int((sleep_sec % 3600) // 60)}min)",
            max_logs=1000
        )

    elif interval_min:
        sleep_sec = interval_min * 60
        log(f"{BOT_PREFIX} 💤 Prochain check dans {interval_min} min", max_logs=1000)

    else:
        sleep_raw = SLEEP_MAP.get(timeframe, 3600)
        if timeframe in ("jour", "1d", "semaine", "1w"):
            sleep_sec = sleep_raw
        else:
            sleep_sec = max(60, sleep_raw // 2)
        log(f"{BOT_PREFIX} 💤 Prochain check dans {int(sleep_sec // 60)} min", max_logs=1000)

    time.sleep(sleep_sec)


# ── Log de démarrage ────────────────────────────────────────────────────────────
def log_startup(state: dict):
    """Affiche l'état complet du bot en une ligne à chaque cycle."""
    cfg = state.get("strategy", {})
    ind = cfg.get("ind_entry", {})
    pos = state.get("position")

    indicators = []
    if ind.get("use_rsi"):          indicators.append(f"RSI<{ind.get('rsi_threshold', 30)}")
    if ind.get("use_bollinger"):    indicators.append(f"Bollinger {ind.get('bollinger_band', '')} ({ind.get('bollinger_mode', '')})")
    if ind.get("use_macd"):         indicators.append("MACD")
    if ind.get("mm_align_periods"): indicators.append(f"AlignMM{ind.get('mm_align_periods')}")
    if ind.get("mm_cross_a"):       indicators.append(f"CrossMM{ind.get('mm_cross_a')}/{ind.get('mm_cross_b')}")

    log(
        f"{BOT_PREFIX} {'SHORT' if cfg.get('is_short') else 'LONG'} | "
        f"{cfg.get('symbol', '?')} | {cfg.get('timeframe', '?')} | "
        f"Capital: {float(state.get('balance', 0)):.2f}$ | "
        f"PnL: {float(state.get('pnl_session', 0)):+.2f}$ | "
        f"{len(state.get('trades', []))} trades | "
        f"Position: {'Ouverte @ ' + str(round(pos['entry_price'], 2)) + '$' if pos else 'Fermée'} | "
        f"Taille: {cfg.get('size_pct', 100)}% | "
        f"TP: {cfg.get('tp_pct', '—')}% SL: {cfg.get('sl_pct', '—')}% | "
        f"Check: {cfg.get('check_time_utc') or str(cfg.get('interval_min', '?')) + ' min'} | "
        f"Indicateurs: {' + '.join(indicators) if indicators else 'Aucun'}",
        max_logs=1000
    )


# ── Boucle principale ───────────────────────────────────────────────────────────
def run():
    log(f"{BOT_PREFIX} 🧪 Bot TESTNET démarré — faux argent Binance testnet")

    client = None  # Connexion différée — seulement quand status=running

    while True:
        try:
            state = get_state()

            # ── Bot en pause ───────────────────────────────────────────────
            if state.get("status") != "running":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] En attente (status=stopped)...")
                time.sleep(10)
                continue

            # ── Connexion Binance testnet ──────────────────────────────────
            if client is None:
                client = BinanceClient(testnet=True)
                res    = client.test_connection()
                if not res["ok"]:
                    log(f"{BOT_PREFIX} ⚠️ Connexion testnet impossible : {res['message']} — réessai dans 60s")
                    client = None
                    time.sleep(60)
                    continue
                log(f"{BOT_PREFIX} {res['message']}")

            cfg       = state.get("strategy", {})
            symbol    = cfg.get("symbol",    "BTCUSDT")
            timeframe = cfg.get("timeframe", "1h")
            tp_pct    = cfg.get("tp_pct")
            sl_pct    = cfg.get("sl_pct")
            is_short  = cfg.get("is_short",  False)
            size_pct  = cfg.get("size_pct",  95)  # pas de plafond sur le testnet
            ind_entry = cfg.get("ind_entry", {})
            ind_exit  = cfg.get("ind_exit",  {})

            log_startup(state)

            # ── Récupération des bougies ───────────────────────────────────
            df = client.get_klines(symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"{BOT_PREFIX} ⚠️ Données insuffisantes pour {symbol}")
                time.sleep(60)
                continue

            # ── Calcul des indicateurs ─────────────────────────────────────
            ind_merged = {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period", 14),
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": ind_entry.get("mm_align_periods", []),
            }
            df_ind = apply_all_indicators(df, ind_merged)

            # Bougie T-1 (dernière bougie fermée)
            candle  = df_ind.iloc[-1]
            open_t1 = float(candle["open"])
            high_t1 = float(candle["high"])
            low_t1  = float(candle["low"])

            state["last_check"] = datetime.now().isoformat()
            state["last_price"] = open_t1

            # ── Signaux ────────────────────────────────────────────────────
            side_entry   = "sell" if is_short else "buy"
            side_exit    = "buy"  if is_short else "sell"
            entry_signal = bool(_build_signal(df_ind, ind_entry, side=side_entry).iloc[-2])
            exit_signal  = bool(_build_signal(df_ind, ind_exit,  side=side_exit).iloc[-2])

            pos = state.get("position")

            log(
                f"{BOT_PREFIX} {symbol} @ {open_t1:.4f} | "
                f"Entrée: {'✅' if entry_signal else '❌'} | "
                f"Sortie: {'✅' if exit_signal else '❌'}"
            )

            # ── Ouverture de position ──────────────────────────────────────
            if pos is None and entry_signal:
                balance = client.get_balance("USDT")
                size    = balance * (size_pct / 100)

                if size < 10:
                    log(f"{BOT_PREFIX} ⚠️ Solde insuffisant ({balance:.2f} USDT)")
                else:
                    qty = round(size / open_t1, 6)
                    res = client.buy(symbol, qty)
                    if res and res["ok"]:
                        fill = res.get("fill_price") or open_t1
                        state["position"] = {
                            "symbol":      symbol,
                            "side":        "SHORT" if is_short else "LONG",
                            "is_short":    is_short,
                            "entry_price": fill,
                            "qty":         qty,
                            "size_usdt":   size,
                            "ts":          datetime.now().isoformat(),
                        }
                        log(f"{BOT_PREFIX} ✅ {'SHORT' if is_short else 'LONG'} ouvert @ {fill:.4f} | {size:.2f} USDT")
                    else:
                        log(f"{BOT_PREFIX} ❌ Ordre échoué : {res}")

            # ── Fermeture de position ──────────────────────────────────────
            elif pos is not None:
                entry    = pos["entry_price"]
                tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
                sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

                if sl_price and low_t1 <= sl_price:
                    exit_reason = "SL"
                elif tp_price and high_t1 >= tp_price:
                    exit_reason = "TP"
                elif exit_signal:
                    exit_reason = "Signal sortie"
                else:
                    exit_reason = None

                if exit_reason:
                    res = client.sell(symbol, pos["qty"])
                    if res and res["ok"]:
                        fill    = res.get("fill_price") or open_t1
                        pnl_pct = (fill - entry) / entry * 100
                        pnl_usd = round((fill - entry) * pos["qty"], 2)

                        state["trades"].append({
                            "ts":          datetime.now().isoformat(),
                            "symbol":      symbol,
                            "side":        pos["side"],
                            "entry_price": entry,
                            "exit_price":  fill,
                            "qty":         pos["qty"],
                            "pnl_pct":     round(pnl_pct, 2),
                            "pnl_usd":     pnl_usd,
                            "raison":      exit_reason,
                        })
                        state["pnl_session"] = sum(t.get("pnl_usd", 0) for t in state["trades"])
                        state["position"]    = None
                        log(f"{BOT_PREFIX} 🔴 Fermé ({exit_reason}) @ {fill:.4f} | PnL: {pnl_usd:+.2f}$")
                    else:
                        log(f"{BOT_PREFIX} ❌ Vente échouée : {res}")

            save_state(state)
            wait_until_next_check(timeframe, cfg.get("check_time_utc"), cfg.get("interval_min"))

        except KeyboardInterrupt:
            log(f"{BOT_PREFIX} Bot TESTNET arrêté (Ctrl+C)")
            break
        except Exception as e:
            log(f"{BOT_PREFIX} ⚠️ Erreur : {e}")
            time.sleep(60)


if __name__ == "__main__":
    run()
