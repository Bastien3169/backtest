"""
bot_local.py
Paper trading LOCAL — simulation pure, aucune clé API requise.
Données de prix : Binance public (lecture seule, sans authentification).
Trades simulés dans bot_state.json.

Lancement : python bot_local.py [--config bot_state_local_long.json]
Arrêt     : Ctrl+C  ou  mettre status="stopped" dans le JSON via Streamlit

Timing :
  - Signal calculé sur la bougie T fermée (iloc[-2])
  - Exécution simulée à l'open de la bougie T+1 (iloc[-1]["open"])
  - TP/SL vérifiés sur high/low de T+1 (intra-bougie)
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta
import pandas as pd

from src.utils import bot_state as _bs
from src.utils.binance_client import BinanceClient
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal
from binance.client import Client as _BinanceRawClient

# ---------------------------------------------------------------------------
# Config --config
# Permet de lancer plusieurs bots en parallèle avec des JSONs différents.
# Ex: python bot_local.py --config bot_state_local_short.json
# Sur Railway, start.py passe le chemin absolu : /data/bot_state_local_long.json
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--config", default="bot_state.json")
args, _ = parser.parse_known_args()

# Chemin absolu → utilisé tel quel / chemin relatif → relatif au script
if os.path.isabs(args.config):
    _bs.STATE_FILE = args.config
else:
    _bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)

# Préfixe de log : "/data/bot_state_local_long.json" → "[LOCAL-LONG]"
_basename  = os.path.basename(args.config)   # garde juste le nom du fichier
BOT_PREFIX = "[" + _basename.replace("bot_state_", "").replace(".json", "").upper() + "]"

# Raccourcis
get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log

# ---------------------------------------------------------------------------
# Client Binance lecture seule (mainnet public — pas de clé, pas d'ordre)
# Le testnet est souvent down, le mainnet public est toujours disponible
# ---------------------------------------------------------------------------
_binance        = BinanceClient.__new__(BinanceClient)
_binance.testnet = False
_binance.client  = _BinanceRawClient("", "")

# ---------------------------------------------------------------------------
# Timing : durée de sleep selon le timeframe
# Pour intraday : on vérifie à mi-période (ex: 1h → check toutes les 30 min)
# Pour daily/weekly : on vérifie une fois par période
# ---------------------------------------------------------------------------
SLEEP_MAP = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 1800, "heure": 1800,
    "4h": 7200,
    "1d": 86400, "jour": 86400,
    "1w": 604800, "semaine": 604800,
}


# Délai ajouté après la fermeture de la bougie
# Pour laisser le temps à Binance/yfinance de mettre à jour les données
BUFFER = {
    "1m": 5, "5m": 10, "15m": 15,
    "1h": 30, "heure": 30,
    "4h": 60,
    "1d": 120, "jour": 120,
    "1w": 300, "semaine": 300,
}


def next_sleep(timeframe: str, check_time_utc: str | None, interval_min: int | None) -> int:
    """
    Retourne les secondes à attendre avant le prochain check.

    Logique de synchronisation :
    - interval_min=60 → check à la prochaine heure ronde UTC + buffer
      Ex: lancé à 9h35 → check à 10h00:30, puis 11h00:30, 12h00:30...
    - check_time_utc="00:01" → check chaque jour à cette heure UTC fixe
    - Sans config → durée de la bougie + buffer (fallback)

    Le buffer laisse le temps à Binance de finaliser la bougie.
    """
    now    = datetime.now(timezone.utc)
    buffer = BUFFER.get(timeframe, 30)

    if interval_min:
        # Buffer selon la durée de l'intervalle
        # Plus l'intervalle est long, plus on attend avant de lire les données
        if interval_min <= 1:    buf = 5
        elif interval_min <= 5:  buf = 10
        elif interval_min <= 15: buf = 15
        elif interval_min <= 60: buf = 30
        elif interval_min <= 240: buf = 60
        else:                    buf = 120   # daily et +

        interval_sec  = interval_min * 60
        seconds_today = now.hour * 3600 + now.minute * 60 + now.second
        next_multiple = ((seconds_today // interval_sec) + 1) * interval_sec
        sleep_sec     = next_multiple - seconds_today + buf
        return max(10, sleep_sec)

    if check_time_utc:
        # Heure UTC fixe quotidienne ex: "00:01"
        h, m   = map(int, check_time_utc.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())

    # Fallback SLEEP_MAP
    raw = SLEEP_MAP.get(timeframe, 3600)
    if timeframe in ("1d", "jour", "1w", "semaine"):
        return raw + buffer
    return max(60, raw // 2) + buffer


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------
def run():
    log(f"{BOT_PREFIX} 🤖 Bot LOCAL démarré", max_logs=5000)

    while True:
        try:
            state = get_state()

            # En attente tant que status != "running"
            if state.get("status") != "running":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {BOT_PREFIX} En attente...")
                time.sleep(10)
                continue

            # ── Lire la config depuis le JSON (écrite par Streamlit) ───────
            cfg       = state.get("strategy", {})
            symbol    = cfg.get("symbol",    "BTCUSDT")
            timeframe = cfg.get("timeframe", "1d")
            tp_pct    = cfg.get("tp_pct")
            sl_pct    = cfg.get("sl_pct")
            is_short  = cfg.get("is_short",  False)
            size_pct  = cfg.get("size_pct",  100)
            ind_entry = cfg.get("ind_entry", {})
            ind_exit  = cfg.get("ind_exit",  {})

            # ── 1. Bougies Binance ─────────────────────────────────────────
            binance_symbol = symbol.replace("-USD", "USDT")
            df = _binance.get_klines(binance_symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"{BOT_PREFIX} ⚠️ Données indisponibles pour {binance_symbol}", max_logs=5000)
                time.sleep(60)
                continue

            # ── 2. Indicateurs ─────────────────────────────────────────────
            df_ind = apply_all_indicators(df, {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period", 14),
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": ind_entry.get("mm_align_periods", []),
            })

            # ── 3. Signal sur bougie T fermée (iloc[-2]) ───────────────────
            exec_price = float(df_ind.iloc[-1]["open"])   # open T+1 = prix d'exécution
            high_t1    = float(df_ind.iloc[-1]["high"])
            low_t1     = float(df_ind.iloc[-1]["low"])

            side_entry   = "buy"  if not is_short else "sell"
            side_exit    = "sell" if not is_short else "buy"
            entry_signal = bool(_build_signal(df_ind, ind_entry, side=side_entry).iloc[-2])
            exit_signal  = bool(_build_signal(df_ind, ind_exit,  side=side_exit).iloc[-2])

            bal = float(state.get("balance", 1000.0))
            pos = state.get("position")

            # Log état du bot à chaque cycle — dans JSON ET terminal
            pnl_session = float(state.get("pnl_session", 0))
            nb_trades   = len(state.get("trades", []))
            pos_str     = f"Ouverte @ {pos['entry_price']:.2f}$" if pos else "Fermée"
            log(f"{BOT_PREFIX} {'SHORT' if is_short else 'LONG'} | {binance_symbol} | {timeframe} | "
                f"Capital: {bal:.2f}$ | PnL session: {pnl_session:+.2f}$ | {nb_trades} trades | "
                f"Position: {pos_str}", max_logs=5000)

            # Signal — terminal uniquement (trop verbeux pour le JSON)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {BOT_PREFIX} "
                  f"{binance_symbol} @ {exec_price:.2f} | "
                  f"Entrée: {'✅' if entry_signal else '❌'} | "
                  f"Sortie: {'✅' if exit_signal else '❌'}")

            # ── 4. Entrée ──────────────────────────────────────────────────
            if pos is None and entry_signal and bal > 0:
                size = bal * (size_pct / 100)
                qty  = size / exec_price
                state["position"] = {
                    "symbol":      symbol,
                    "side":        "LONG" if not is_short else "SHORT",
                    "is_short":    is_short,
                    "entry_price": exec_price,
                    "qty":         qty,
                    "size_usdt":   size,
                    "ts":          datetime.now().isoformat(),
                }
                state["balance"] -= size
                log(f"{BOT_PREFIX} ✅ {'LONG' if not is_short else 'SHORT'} ouvert "
                    f"@ {exec_price:.2f} | Qty: {qty:.6f} | Capital restant: {state['balance']:.2f}$",
                    max_logs=5000)

            # ── 5. Sortie ──────────────────────────────────────────────────
            elif pos is not None:
                entry    = pos["entry_price"]
                tp_price = entry * (1 + tp_pct / 100) if tp_pct and not is_short else (entry * (1 - tp_pct / 100) if tp_pct else None)
                sl_price = entry * (1 - sl_pct / 100) if sl_pct and not is_short else (entry * (1 + sl_pct / 100) if sl_pct else None)

                should_exit = False
                exit_price  = exec_price
                exit_reason = ""

                if not is_short:
                    if sl_price and low_t1  <= sl_price: should_exit, exit_price, exit_reason = True, sl_price, "SL"
                    elif tp_price and high_t1 >= tp_price: should_exit, exit_price, exit_reason = True, tp_price, "TP"
                else:
                    if sl_price and high_t1 >= sl_price: should_exit, exit_price, exit_reason = True, sl_price, "SL"
                    elif tp_price and low_t1  <= tp_price: should_exit, exit_price, exit_reason = True, tp_price, "TP"

                if exit_signal and not should_exit:
                    should_exit, exit_reason = True, "Signal"

                if should_exit:
                    pnl_pct     = (exit_price - entry) / entry * 100 if not is_short else (entry - exit_price) / entry * 100
                    pnl_usd     = round(pos["qty"] * exit_price - pos["size_usdt"], 2)
                    state["balance"]      += pos["qty"] * exit_price
                    state["pnl_session"]   = round(state["balance"] - state.get("balance_init", 1000.0), 2)
                    pnl_session_pct        = round(state["pnl_session"] / state.get("balance_init", 1000.0) * 100, 2)
                    state["trades"].append({
                        "ts": datetime.now().isoformat(), "symbol": symbol,
                        "side": pos["side"], "entry_price": entry, "exit_price": exit_price,
                        "qty": pos["qty"], "pnl_pct": round(pnl_pct, 2),
                        "pnl_usd": pnl_usd, "raison": exit_reason,
                    })
                    state["position"] = None
                    log(f"{BOT_PREFIX} 🔴 Fermé ({exit_reason}) @ {exit_price:.2f} | "
                        f"PnL: {pnl_usd:+.2f}$ ({pnl_pct:+.2f}%) | "
                        f"Capital: {state['balance']:.2f}$ | "
                        f"Session: {state['pnl_session']:+.2f}$ ({pnl_session_pct:+.2f}%)",
                        max_logs=5000)

            # ── 6. Sauvegarder ─────────────────────────────────────────────
            # Fusionner les logs écrits par log() pendant ce cycle
            # (sans ça save_state() les écraserait)
            fresh                = get_state()
            state["log"]         = fresh["log"]
            state["last_check"]  = datetime.now().isoformat()
            state["last_price"]  = exec_price
            save_state(state)

            # ── 7. Sleep jusqu'au prochain check ───────────────────────────
            check_time_utc = cfg.get("check_time_utc")
            interval_min   = cfg.get("interval_min")
            sleep_sec      = next_sleep(timeframe, check_time_utc, interval_min)

            next_check = datetime.now(timezone.utc) + timedelta(seconds=sleep_sec)
            log(f"{BOT_PREFIX} 💤 Prochain check à {next_check.strftime('%H:%M:%S')} UTC "
                f"(dans {sleep_sec//3600}h {(sleep_sec%3600)//60}min {sleep_sec%60}s)",
                max_logs=5000)

            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            log(f"{BOT_PREFIX} ⏹️ Arrêté (Ctrl+C)", max_logs=5000)
            break
        except Exception as e:
            log(f"{BOT_PREFIX} ⚠️ Erreur : {e}", max_logs=5000)
            time.sleep(60)


if __name__ == "__main__":
    run()
