"""
bot_mainnet.py
Trading RÉEL sur Hyperliquid MAINNET — VRAI ARGENT.

⚠️  ATTENTION : Ce bot utilise de vrais fonds USDC sur Hyperliquid.
    Ne le lancer qu'après avoir validé la stratégie en local ET testnet Binance.

Prérequis :
1. Wallet MetaMask avec USDC sur Arbitrum
2. Dépôt sur app.hyperliquid.xyz
3. Configurer leverage et margin mode sur l'interface HL avant de lancer
4. Ajouter dans Railway Variables (ou .env local) :
   HL_PRIVATE_KEY=0x...
   HL_WALLET_ADDRESS=0x...

Lancement : python bot_mainnet.py [--config bot_state_mainnet_long.json]
"""

# ---------------------------------------------------------------------------
# Imports système
# ---------------------------------------------------------------------------
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Imports internes
# ---------------------------------------------------------------------------
from src.utils import bot_state as _bs
from src.utils.hyperliquid_client import HyperliquidClient
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal

# ---------------------------------------------------------------------------
# Config --config
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--config", default="bot_state.json")
args, _ = parser.parse_known_args()

if os.path.isabs(args.config):
    _bs.STATE_FILE = args.config
else:
    _bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)

# Préfixe de log : "bot_state_mainnet_long.json" → "[MAINNET-LONG]"
_basename  = os.path.basename(args.config)
BOT_PREFIX = "[" + _basename.replace("bot_state_", "").replace(".json", "").upper() + "]"

print(f"{BOT_PREFIX} Fichier JSON : {_bs.STATE_FILE}")

get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log

# ---------------------------------------------------------------------------
# Timing — synchronisation sur les heures rondes UTC
# (identique à bot_testnet.py)
# ---------------------------------------------------------------------------
SLEEP_MAP = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "heure": 3600,
    "4h": 14400,
    "1d": 86400, "jour": 86400,
    "1w": 604800, "semaine": 604800,
}

BUFFER = {
    "1m": 5, "5m": 10, "15m": 15,
    "1h": 30, "heure": 30,
    "4h": 60,
    "1d": 120, "jour": 120,
    "1w": 300, "semaine": 300,
}


def next_sleep(timeframe: str, check_time_utc, interval_min) -> int:
    now    = datetime.now(timezone.utc)
    buffer = BUFFER.get(timeframe, 30)

    if interval_min:
        if interval_min <= 1:     buf = 5
        elif interval_min <= 5:   buf = 10
        elif interval_min <= 15:  buf = 15
        elif interval_min <= 60:  buf = 30
        elif interval_min <= 240: buf = 60
        else:                     buf = 120
        interval_sec  = interval_min * 60
        seconds_today = now.hour * 3600 + now.minute * 60 + now.second
        next_multiple = ((seconds_today // interval_sec) + 1) * interval_sec
        return max(10, next_multiple - seconds_today + buf)

    if check_time_utc:
        h, m   = map(int, check_time_utc.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())

    raw = SLEEP_MAP.get(timeframe, 3600)
    if timeframe in ("1d", "jour", "1w", "semaine"):
        return raw + buffer
    return max(60, raw // 2) + buffer


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------
def run():
    log(f"{BOT_PREFIX} 💰 Bot MAINNET Hyperliquid démarré — ⚠️ ARGENT RÉEL", max_logs=5000)
    first_run = True
    client    = None   # connexion différée

    while True:
        try:
            state = get_state()

            # En attente tant que status != "running"
            if state.get("status") != "running":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {BOT_PREFIX} En attente (status=stopped)...")
                first_run = True
                client    = None
                time.sleep(3600)
                continue

            # ── Connexion HL — seulement quand running ─────────────────────
            if client is None:
                client = HyperliquidClient()
                res    = client.test_connection()
                if not res["ok"]:
                    log(f"{BOT_PREFIX} ⚠️ Connexion HL impossible : {res['message']} — réessai dans 60s",
                        max_logs=5000)
                    client = None
                    time.sleep(60)
                    continue
                log(f"{BOT_PREFIX} {res['message']}", max_logs=5000)

            # ── Config depuis le JSON ──────────────────────────────────────
            cfg       = state.get("strategy", {})
            symbol    = cfg.get("symbol", "BTC-USD").replace("-USD", "").replace("USDT", "")  # BTC-USD → BTC
            timeframe = cfg.get("timeframe", "1h")
            tp_pct    = cfg.get("tp_pct")
            sl_pct    = cfg.get("sl_pct")
            is_short  = cfg.get("is_short", False)
            size_pct  = cfg.get("size_pct", 10)
            ind_entry = cfg.get("ind_entry", {})
            ind_exit  = cfg.get("ind_exit",  {})

            check_time_utc = cfg.get("check_time_utc")
            interval_min   = cfg.get("interval_min")

            # ── 1. Log immédiat au début du cycle ──────────────────────────
            sleep_sec_next = next_sleep(timeframe, check_time_utc, interval_min)
            next_check     = datetime.now(timezone.utc) + timedelta(seconds=sleep_sec_next)
            pos_now        = state.get("position")
            pos_str_now    = f"Ouverte @ {pos_now['entry_price']:.2f}$" if pos_now else "Fermée"
            log(f"{BOT_PREFIX} ✔️ En ligne | {symbol} | {timeframe} | "
                f"Position: {pos_str_now} | "
                f"Prochain check à {next_check.strftime('%H:%M:%S')} UTC", max_logs=5000)

            # ── 2. Bougies HL ──────────────────────────────────────────────
            df = client.get_klines(symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"{BOT_PREFIX} ⚠️ Données insuffisantes pour {symbol}", max_logs=5000)
                time.sleep(60)
                continue

            # ── 3. Indicateurs ─────────────────────────────────────────────
            df_ind = apply_all_indicators(df, {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period", 14),
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": ind_entry.get("mm_align_periods", []),
            })

            # ── 4. Signal sur bougie T fermée (iloc[-2]) ───────────────────
            exec_price = float(df_ind.iloc[-1]["open"])
            high_t1    = float(df_ind.iloc[-1]["high"])
            low_t1     = float(df_ind.iloc[-1]["low"])

            side_entry   = "buy"  if not is_short else "sell"
            side_exit    = "sell" if not is_short else "buy"
            entry_signal = bool(_build_signal(df_ind, ind_entry, side=side_entry).iloc[-2])
            exit_signal  = bool(_build_signal(df_ind, ind_exit,  side=side_exit).iloc[-2])

            pos = state.get("position")

            print(f"[{datetime.now().strftime('%H:%M:%S')}] {BOT_PREFIX} "
                  f"{symbol} @ {exec_price:.2f} | "
                  f"Entrée: {'✅' if entry_signal else '❌'} | "
                  f"Sortie: {'✅' if exit_signal else '❌'}")

            # ── 5. Entrée ──────────────────────────────────────────────────
            if pos is None and entry_signal:
                balance  = client.get_balance()
                size_usd = balance * (size_pct / 100)

                if size_usd < 10:
                    log(f"{BOT_PREFIX} ⚠️ Solde insuffisant ({balance:.2f} USDC)", max_logs=5000)
                else:
                    # Long → buy / Short → short (ordre sans reduce_only)
                    res = client.buy(symbol, size_usd) if not is_short else client.short(symbol, size_usd)
                    if res and res["ok"]:
                        fill = res.get("fill_price") or exec_price
                        qty  = round(size_usd / fill, 6)
                        state["position"] = {
                            "symbol":      symbol,
                            "side":        "LONG" if not is_short else "SHORT",
                            "is_short":    is_short,
                            "entry_price": fill,
                            "qty":         qty,
                            "size_usdt":   size_usd,
                            "ts":          datetime.now().isoformat(),
                        }
                        log(f"{BOT_PREFIX} ✅ {'LONG' if not is_short else 'SHORT'} ouvert "
                            f"@ {fill:.2f} | {size_usd:.2f} USDC", max_logs=5000)
                    else:
                        log(f"{BOT_PREFIX} ❌ Ordre échoué : {res}", max_logs=5000)

            # ── 6. Sortie ──────────────────────────────────────────────────
            elif pos is not None:
                entry    = pos["entry_price"]
                tp_price = entry * (1 + tp_pct / 100) if tp_pct and not is_short else (entry * (1 - tp_pct / 100) if tp_pct else None)
                sl_price = entry * (1 - sl_pct / 100) if sl_pct and not is_short else (entry * (1 + sl_pct / 100) if sl_pct else None)

                should_exit = False
                exit_reason = ""

                if not is_short:
                    if sl_price and low_t1  <= sl_price: should_exit, exit_reason = True, "SL"
                    elif tp_price and high_t1 >= tp_price: should_exit, exit_reason = True, "TP"
                else:
                    if sl_price and high_t1 >= sl_price: should_exit, exit_reason = True, "SL"
                    elif tp_price and low_t1  <= tp_price: should_exit, exit_reason = True, "TP"

                if exit_signal and not should_exit:
                    should_exit, exit_reason = True, "Signal"

                if should_exit:
                    # Long → sell (reduce_only) / Short → close_short (reduce_only)
                    res = client.sell(symbol, pos["qty"]) if not is_short else client.close_short(symbol, pos["qty"])
                    if res and res["ok"]:
                        fill    = res.get("fill_price") or exec_price
                        pnl_pct = (fill - entry) / entry * 100 if not is_short else (entry - fill) / entry * 100
                        pnl_usd = round(pos["qty"] * fill - pos["size_usdt"], 2) if not is_short else round(pos["size_usdt"] - pos["qty"] * fill, 2)

                        state["trades"].append({
                            "ts": datetime.now().isoformat(), "symbol": symbol,
                            "side": pos["side"], "entry_price": entry, "exit_price": fill,
                            "qty": pos["qty"], "pnl_pct": round(pnl_pct, 2),
                            "pnl_usd": pnl_usd, "raison": exit_reason,
                        })
                        state["pnl_session"] = sum(t.get("pnl_usd", 0) for t in state["trades"])
                        state["position"]    = None
                        log(f"{BOT_PREFIX} 🔴 Fermé ({exit_reason}) @ {fill:.2f} | "
                            f"PnL: {pnl_usd:+.2f}$ ({pnl_pct:+.2f}%)", max_logs=5000)
                    else:
                        log(f"{BOT_PREFIX} ❌ Clôture échouée : {res}", max_logs=5000)

            # ── 7. Log état final + save ───────────────────────────────────
            pos         = state.get("position")
            bal         = client.get_balance()
            pos_str     = f"Ouverte @ {pos['entry_price']:.2f}$" if pos else "Fermée"
            pnl_session = float(state.get("pnl_session", 0))
            nb_trades   = len(state.get("trades", []))
            log(f"{BOT_PREFIX} {'SHORT' if is_short else 'LONG'} | {symbol} | {timeframe} | "
                f"Balance: {bal:.2f} USDC | PnL session: {pnl_session:+.2f}$ | {nb_trades} trades | "
                f"Position: {pos_str}", max_logs=5000)

            fresh                = get_state()
            state["log"]         = fresh["log"]
            state["last_check"]  = datetime.now().isoformat()
            state["last_price"]  = exec_price
            save_state(state)

            # ── 8. Sleep ───────────────────────────────────────────────────
            sleep_sec  = next_sleep(timeframe, check_time_utc, interval_min)
            next_check = datetime.now(timezone.utc) + timedelta(seconds=sleep_sec)
            log(f"{BOT_PREFIX} 💤 Prochain check à {next_check.strftime('%H:%M:%S')} UTC "
                f"(dans {sleep_sec//3600}h {(sleep_sec%3600)//60}min {sleep_sec%60}s)",
                max_logs=5000)

            if first_run:
                first_run = False

            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            log(f"{BOT_PREFIX} ⏹️ Arrêté (Ctrl+C)", max_logs=5000)
            break
        except Exception as e:
            log(f"{BOT_PREFIX} ⚠️ Erreur : {e}", max_logs=5000)
            time.sleep(60)


if __name__ == "__main__":
    run()
