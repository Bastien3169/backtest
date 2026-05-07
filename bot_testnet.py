"""
bot_testnet.py
Paper trading sur Binance TESTNET — vrais ordres, faux argent.

Prérequis :
1. pip install python-binance
2. Créer un compte sur https://testnet.binance.vision (connexion GitHub)
3. Générer des clés API testnet
4. Ajouter dans .env :
   BINANCE_TESTNET_API_KEY=...
   BINANCE_TESTNET_SECRET_KEY=...

Lancement : python bot_testnet.py
"""

import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from src.utils import bot_state as _bs
import argparse as _ap

# Support --config pour lancer plusieurs bots en parallèle
# Exemple : python bot_testnet.py --config bot_state_testnet_long.json
_parser = _ap.ArgumentParser()
_parser.add_argument("--config", default="bot_state.json")
_args, _ = _parser.parse_known_args()
_bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), _args.config)

# Préfixe pour les logs — identifie quel bot écrit
# ex: "bot_state_testnet_long.json" → "[TESTNET-LONG]"
_config_name = _args.config.replace("bot_state_", "").replace(".json", "").upper()
BOT_PREFIX   = f"[{_config_name}]"

get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log
from src.utils.bot_state import
from src.utils.bot_report import generate as generate_report
from src.utils.binance_client import BinanceClient
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal


def run():
    log(f"{BOT_PREFIX} 🤖 Bot TESTNET démarré")

    # Client initialisé dans la boucle — pas au démarrage
    # Si les clés manquent, le bot attend sans crasher
    client = None

    while True:
        try:
            state = get_state()

            if state.get("status") != "running":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] En attente (status=stopped)...")
                time.sleep(10)
                continue

            # Connexion Binance seulement quand status=running
            if client is None:
                client = BinanceClient(testnet=True)
                res = client.test_connection()
                if not res["ok"]:
                    log(f"{BOT_PREFIX} ⚠️ Connexion impossible : {res['message']} — réessai dans 60s")
                    client = None
                    time.sleep(60)
                    continue
                log(f"{BOT_PREFIX} {res['message']}")

            cfg       = state.get("strategy", {})

            # Log de démarrage avec toutes les infos — affiché une fois par cycle
            log_startup(BOT_PREFIX, state)

            symbol    = cfg.get("symbol",    "BTCUSDT")
            timeframe = cfg.get("timeframe", "1h")
            tp_pct    = cfg.get("tp_pct")
            sl_pct    = cfg.get("sl_pct")
            is_short  = cfg.get("is_short",  False)
            size_pct  = cfg.get("size_pct",  95)    # 95% du solde USDT
            ind_entry = cfg.get("ind_entry", {})
            ind_exit  = cfg.get("ind_exit",  {})

            # ── 1. Bougies depuis Binance ──────────────────────────────────
            df = client.get_klines(symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"{BOT_PREFIX} ⚠️ Données insuffisantes pour {symbol}")
                time.sleep(60)
                continue

            # ── 2. Indicateurs ─────────────────────────────────────────────
            ind_merged = {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period", 14),
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": ind_entry.get("mm_align_periods", []),
            }
            df_ind = apply_all_indicators(df, ind_merged)

            # ── 3. Bougie T fermée = iloc[-2] ──────────────────────────────
            candle_t1  = df_ind.iloc[-1]
            exec_price = float(candle_t1["open"])
            high_t1    = float(candle_t1["high"])
            low_t1     = float(candle_t1["low"])

            state["last_check"] = datetime.now().isoformat()
            state["last_price"] = exec_price

            # ── 4. Signaux ─────────────────────────────────────────────────
            sig_entry = _build_signal(df_ind, ind_entry, side="buy"  if not is_short else "sell")
            sig_exit  = _build_signal(df_ind, ind_exit,  side="sell" if not is_short else "buy")

            entry_signal = bool(sig_entry.iloc[-2])
            exit_signal  = bool(sig_exit.iloc[-2])
            pos          = state.get("position")

            log(
                f"{symbol} @ {exec_price:.4f} | "
                f"Entrée: {'✅' if entry_signal else '❌'} | "
                f"Sortie: {'✅' if exit_signal else '❌'} | "
                f"Position: {'Ouverte' if pos else 'Fermée'}"
            )

            # ── 5. Entrée ──────────────────────────────────────────────────
            if pos is None and entry_signal:
                balance = client.get_balance("USDT")
                if balance < 10:
                    log(f"{BOT_PREFIX} {BOT_PREFIX} ⚠️ Solde USDT insuffisant")
                else:
                    size = balance * (size_pct / 100)
                    qty  = round(size / exec_price, 6)
                    res  = client.buy(symbol, qty)
                    if res and res["ok"]:
                        fill = res.get("fill_price") or exec_price
                        state["position"] = {
                            "symbol":      symbol,
                            "side":        "LONG" if not is_short else "SHORT",
                            "is_short":    is_short,
                            "entry_price": fill,
                            "qty":         qty,
                            "size_usdt":   size,
                            "ts":          datetime.now().isoformat(),
                        }
                        log(f"{BOT_PREFIX} ✅ LONG ouvert @ {fill:.4f} | Qty: {qty}")
                    else:
                        log(f"{BOT_PREFIX} ❌ Ordre achat échoué : {res}")

            # ── 6. Sortie ──────────────────────────────────────────────────
            elif pos is not None:
                entry = pos["entry_price"]

                tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
                sl_price = entry * (1 - sl_pct / 100) if sl_pct else None

                should_exit = False
                exit_reason = ""

                if sl_price and low_t1 <= sl_price:
                    should_exit = True
                    exit_reason = "SL"
                elif tp_price and high_t1 >= tp_price:
                    should_exit = True
                    exit_reason = "TP"
                elif exit_signal:
                    should_exit = True
                    exit_reason = "Signal sortie"

                if should_exit:
                    res = client.sell(symbol, pos["qty"])
                    if res and res["ok"]:
                        fill    = res.get("fill_price") or exec_price
                        pnl_pct = (fill - entry) / entry * 100
                        pnl_usd = round((fill - entry) * pos["qty"], 2)
                        trade   = {
                            "ts":          datetime.now().isoformat(),
                            "symbol":      symbol,
                            "side":        pos["side"],
                            "entry_price": entry,
                            "exit_price":  fill,
                            "qty":         pos["qty"],
                            "pnl_pct":     round(pnl_pct, 2),
                            "pnl_usd":     pnl_usd,
                            "raison":      exit_reason,
                        }
                        state["trades"].append(trade)
                        state["pnl_session"] = sum(t.get("pnl_usd", 0) for t in state["trades"])
                        state["position"]    = None
                        log(f"{BOT_PREFIX} 🔴 Position fermée : {exit_reason} @ {fill:.4f} | PnL: {pnl_usd:+.2f}$")
                    else:
                        log(f"{BOT_PREFIX} ❌ Ordre vente échoué : {res}")

            save_state(state)

            sleep = SLEEP_MAP.get(timeframe, 1800)
            check_time_utc = cfg.get("check_time_utc")
            interval_min   = cfg.get("interval_min")
            wait_until_next_check(timeframe, check_time_utc, interval_min)

        except KeyboardInterrupt:
            log(f"{BOT_PREFIX} {BOT_PREFIX} Bot TESTNET arrêté (Ctrl+C)")
            break
        except Exception as e:
            log(f"{BOT_PREFIX} ⚠️ Erreur : {e}")
            time.sleep(60)


if __name__ == "__main__":
    run()
