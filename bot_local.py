"""
bot_local.py
Paper trading LOCAL — aucune API, simulation pure sur données yfinance.
Pas de clé requise. Idéal pour valider une stratégie avant le testnet.

Lancement : python bot_local.py
Arrêt     : Ctrl+C ou mettre status="stopped" dans bot_state.json

Logique :
- Récupère les bougies via yfinance
- Signal sur bougie T fermée (iloc[-2])
- Exécution simulée à l'open de T+1 (iloc[-1]["open"])
- Trades enregistrés dans bot_state.json
"""

import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime
from src.utils import bot_state as _bs

# Permet de lancer plusieurs bots avec des fichiers JSON différents
# Exemple : python bot_local.py --config bot_state_short.json
parser = argparse.ArgumentParser()
parser.add_argument("--config", default="bot_state.json",
                    help="Fichier JSON d'état (défaut: bot_state.json)")
args, _ = parser.parse_known_args()

# Override du fichier d'état si spécifié
_bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)

get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log
reset      = _bs.reset
from src.utils.binance_client import BinanceClient   # données publiques, pas de clé
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal

# Client Binance lecture seule — mainnet public, pas de clé requise
# On n'utilise PAS testnet=True ici car le testnet est souvent down
# Les données de prix du mainnet sont 100% publiques sans authentification
_binance = BinanceClient.__new__(BinanceClient)
_binance.testnet = False
from binance.client import Client as _Client
_binance.client = _Client("", "")   # clés vides = lecture seule sur mainnet

# ---------------------------------------------------------------------------
# Config par défaut (sera écrasée par Streamlit si disponible)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "symbol":    "BTC-EUR",
    "timeframe": "jour",
    "size_pct":  100,        # % du capital à engager par trade
    "tp_pct":    5.0,
    "sl_pct":    2.5,
    "is_short":  False,
    "ind_entry": {           # indicateurs d'entrée — à modifier selon ta stratégie
        "use_bollinger":  True,
        "bollinger_band": "basse",
        "use_rsi":        False,
        "mm_align_periods": [],
        "mm_configs":     {},
        "mm_cross_a":     None,
        "mm_cross_b":     None,
        "btc_cross_period": None,
        "use_macd":       False,
    },
    "ind_exit": {            # indicateurs de sortie
        "use_bollinger":  True,
        "bollinger_band": "haute",
        "use_rsi":        False,
        "mm_configs":     {},
        "mm_cross_a":     None,
        "mm_cross_b":     None,
        "btc_cross_period": None,
        "use_macd":       False,
        "mm_align_periods": [],
    },
}

# Durée de sleep selon le timeframe (en secondes)
SLEEP_MAP = {
    "1m": 60, "5m": 300, "15m": 900,
    "heure": 1800, "1h": 1800,
    "4h": 7200, "jour": 43200, "1d": 43200,
}


def run():
    log("🤖 Bot LOCAL démarré")

    while True:
        try:
            state = get_state()

            if state.get("status") != "running":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] En attente (status=stopped)...")
                time.sleep(10)
                continue

            cfg       = state.get("strategy") or DEFAULT_CONFIG
            symbol    = cfg.get("symbol",    DEFAULT_CONFIG["symbol"])
            timeframe = cfg.get("timeframe", DEFAULT_CONFIG["timeframe"])
            tp_pct    = cfg.get("tp_pct",    DEFAULT_CONFIG["tp_pct"])
            sl_pct    = cfg.get("sl_pct",    DEFAULT_CONFIG["sl_pct"])
            is_short  = cfg.get("is_short",  DEFAULT_CONFIG["is_short"])
            size_pct  = cfg.get("size_pct",  100)
            ind_entry = cfg.get("ind_entry", DEFAULT_CONFIG["ind_entry"])
            ind_exit  = cfg.get("ind_exit",  DEFAULT_CONFIG["ind_exit"])

            # ── 1. Récupérer les bougies depuis Binance (sans clé) ────────
            # On convertit le symbole yfinance en symbole Binance si nécessaire
            binance_symbol = symbol.replace("-USD", "USDT").replace("-USDT", "USDT")
            df = _binance.get_klines(binance_symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"⚠️ Pas assez de données pour {binance_symbol}")
                time.sleep(60)
                continue

            # ── 2. Calculer les indicateurs ────────────────────────────────
            ind_merged = {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period") or ind_exit.get("rsi_period") or 14,
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": list(set(
                    ind_entry.get("mm_align_periods", []) +
                    ind_exit.get("mm_align_periods", [])
                )),
            }
            df_ind = apply_all_indicators(df, ind_merged)

            # ── 3. Bougie T fermée = iloc[-2] / Open T+1 = iloc[-1]["open"] ──
            candle_t  = df_ind.iloc[-2]   # dernière bougie COMPLÈTE — signal calculé ici
            candle_t1 = df_ind.iloc[-1]   # bougie en cours — exécution à son open

            exec_price = float(candle_t1["open"])   # prix d'exécution réel
            high_t1    = float(candle_t1["high"])
            low_t1     = float(candle_t1["low"])

            # ── 4. Évaluer les signaux sur T ───────────────────────────────
            side_entry = "buy"  if not is_short else "sell"
            side_exit  = "sell" if not is_short else "buy"

            sig_entry = _build_signal(df_ind, ind_entry, side=side_entry)
            sig_exit  = _build_signal(df_ind, ind_exit,  side=side_exit)

            entry_signal = bool(sig_entry.iloc[-2])
            exit_signal  = bool(sig_exit.iloc[-2])

            ts    = datetime.now().strftime("%H:%M:%S")
            pos   = state.get("position")
            bal   = float(state.get("balance", 1000.0))

            state["last_check"] = datetime.now().isoformat()
            state["last_price"] = exec_price

            log(
                f"{symbol} @ {exec_price:.4f} | "
                f"Entrée: {'✅' if entry_signal else '❌'} | "
                f"Sortie: {'✅' if exit_signal else '❌'} | "
                f"Position: {'Ouverte' if pos else 'Fermée'} | "
                f"Capital: {bal:.2f}"
            )

            # ── 5. Gestion entrée ──────────────────────────────────────────
            if pos is None and entry_signal and bal > 0:
                size   = bal * (size_pct / 100)
                qty    = size / exec_price
                state["position"] = {
                    "symbol":      symbol,
                    "side":        "LONG" if not is_short else "SHORT",
                    "is_short":    is_short,
                    "entry_price": exec_price,
                    "qty":         qty,
                    "size_usdt":   size,
                    "ts":          datetime.now().isoformat(),
                }
                state["balance"] -= size   # réserver le capital
                log(f"✅ {'LONG' if not is_short else 'SHORT'} ouvert @ {exec_price:.4f} | Qty: {qty:.6f}")

            # ── 6. Gestion sortie ──────────────────────────────────────────
            elif pos is not None:
                entry = pos["entry_price"]

                # TP/SL vérifiés sur high/low de la bougie T+1 (intra-bougie)
                if not is_short:
                    tp_price = entry * (1 + tp_pct / 100) if tp_pct else None
                    sl_price = entry * (1 - sl_pct / 100) if sl_pct else None
                else:
                    tp_price = entry * (1 - tp_pct / 100) if tp_pct else None
                    sl_price = entry * (1 + sl_pct / 100) if sl_pct else None

                should_exit = False
                exit_price  = exec_price
                exit_reason = ""

                # SL prioritaire
                if not is_short:
                    if sl_price and low_t1 <= sl_price:
                        should_exit = True
                        exit_price  = sl_price
                        exit_reason = f"SL"
                    elif tp_price and high_t1 >= tp_price:
                        should_exit = True
                        exit_price  = tp_price
                        exit_reason = f"TP"
                else:
                    if sl_price and high_t1 >= sl_price:
                        should_exit = True
                        exit_price  = sl_price
                        exit_reason = f"SL"
                    elif tp_price and low_t1 <= tp_price:
                        should_exit = True
                        exit_price  = tp_price
                        exit_reason = f"TP"

                if exit_signal and not should_exit:
                    should_exit = True
                    exit_reason = "Signal sortie"

                if should_exit:
                    if not is_short:
                        pnl_pct = (exit_price - entry) / entry * 100
                    else:
                        pnl_pct = (entry - exit_price) / entry * 100

                    proceeds = pos["qty"] * exit_price
                    pnl_usd  = round(proceeds - pos["size_usdt"], 2)

                    state["balance"] += proceeds
                    state["pnl_session"] = round(
                        state["balance"] - state.get("balance_init", 1000.0), 2
                    )

                    trade = {
                        "ts":          datetime.now().isoformat(),
                        "symbol":      symbol,
                        "side":        pos["side"],
                        "entry_price": entry,
                        "exit_price":  exit_price,
                        "qty":         pos["qty"],
                        "pnl_pct":     round(pnl_pct, 2),
                        "pnl_usd":     pnl_usd,
                        "raison":      exit_reason,
                    }
                    state["trades"].append(trade)
                    state["position"] = None
                    log(f"🔴 Position fermée : {exit_reason} @ {exit_price:.4f} | PnL: {pnl_usd:+.2f}")

            save_state(state)

            # ── 7. Sleep ────────────────────────────────────────────────────
            sleep = SLEEP_MAP.get(timeframe, 3600)
            # On divise par 2 pour vérifier en milieu de période
            actual_sleep = max(60, sleep // 2)
            log(f"💤 Prochain check dans {actual_sleep // 60} min")
            time.sleep(actual_sleep)

        except KeyboardInterrupt:
            log("Bot LOCAL arrêté (Ctrl+C)")
            break
        except Exception as e:
            log(f"⚠️ Erreur : {e}")
            time.sleep(60)


if __name__ == "__main__":
    run()
