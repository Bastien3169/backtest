"""
bot_mainnet.py
Trading RÉEL sur Binance MAINNET — VRAI ARGENT.

⚠️  ATTENTION : Ce bot utilise de vrais fonds.
    Ne le lancer qu'après avoir validé la stratégie en local ET testnet.

Prérequis :
1. Compte Binance vérifié (KYC)
2. Clés API mainnet avec permission "Spot Trading" uniquement
   (NE PAS activer "Withdrawal" sur les clés API)
3. Ajouter dans .env :
   BINANCE_API_KEY=...
   BINANCE_API_SECRET=...

Lancement : python bot_mainnet.py
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
# Chemin absolu ou relatif selon comment --config est passé
if os.path.isabs(_args.config):
    _bs.STATE_FILE = _args.config
else:
    _bs.STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), _args.config)

# Préfixe pour les logs — identifie quel bot écrit
# ex: "bot_state_testnet_long.json" → "[TESTNET-LONG]"
_config_name = _args.config.replace("bot_state_", "").replace(".json", "").upper()
BOT_PREFIX   = f"[{_config_name}]"

get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log
# ---------------------------------------------------------------------------
# Fonctions de timing et de log — dupliquées dans chaque bot volontairement
# (plus simple à lire qu'un fichier commun)
# ---------------------------------------------------------------------------

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
    - check_time_utc : heure UTC fixe (ex: "00:01") → le bot se réveille
                       chaque jour à cette heure précise
                       UTC toujours utilisé peu importe le fuseau horaire local
                       France = UTC+1 hiver / UTC+2 été
    - interval_min   : intervalle en minutes (ex: 15) → le bot vérifie
                       toutes les X minutes
    - si les deux sont None → fallback sur SLEEP_MAP selon le timeframe
                               daily/weekly = une fois par période
                               intraday     = moitié de la période
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    if check_time_utc:
        # Heure UTC fixe — ex: "00:01" pour juste après minuit UTC
        h, m   = map(int, check_time_utc.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            # L'heure est déjà passée aujourd'hui → on attend demain
            target += timedelta(days=1)
        sleep_sec = (target - now).total_seconds()
        log(
            f"{BOT_PREFIX} 💤 Prochain check à {check_time_utc} UTC "
            f"(dans {int(sleep_sec // 3600)}h {int((sleep_sec % 3600) // 60)}min)",
            max_logs=1000
        )

    elif interval_min:
        # Intervalle fixe en minutes
        sleep_sec = interval_min * 60
        log(f"{BOT_PREFIX} 💤 Prochain check dans {interval_min} min", max_logs=1000)

    else:
        # Fallback SLEEP_MAP
        sleep_raw = SLEEP_MAP.get(timeframe, 3600)
        if timeframe in ("jour", "1d", "semaine", "1w"):
            # Daily/weekly : une seule vérification par période
            sleep_sec = sleep_raw
        else:
            # Intraday : vérifie à mi-période pour ne pas rater la fermeture
            sleep_sec = max(60, sleep_raw // 2)
        log(f"{BOT_PREFIX} 💤 Prochain check dans {int(sleep_sec // 60)} min", max_logs=1000)

    time.sleep(sleep_sec)


def log_startup(prefix: str, state: dict):
    """
    Log affiché à chaque cycle avec le contenu complet du JSON.
    Permet de savoir d'un coup d'œil l'état complet du bot.
    """
    cfg     = state.get("strategy", {})
    balance = float(state.get("balance", 0))
    pnl     = float(state.get("pnl_session", 0))
    pos     = state.get("position")
    trades  = len(state.get("trades", []))

    symbol    = cfg.get("symbol", "?")
    timeframe = cfg.get("timeframe", "?")
    is_short  = cfg.get("is_short", False)
    tp        = cfg.get("tp_pct", "—")
    sl        = cfg.get("sl_pct", "—")
    size      = cfg.get("size_pct", 100)
    check     = cfg.get("check_time_utc") or f"{cfg.get('interval_min', '?' )} min"

    ind = cfg.get("ind_entry", {})
    indicators = []
    if ind.get("use_rsi"):          indicators.append(f"RSI<{ind.get('rsi_threshold',30)}")
    if ind.get("use_bollinger"):    indicators.append(f"Bollinger {ind.get('bollinger_band','')} ({ind.get('bollinger_mode','')})")
    if ind.get("use_macd"):         indicators.append("MACD")
    if ind.get("mm_align_periods"): indicators.append(f"AlignMM{ind.get('mm_align_periods')}")
    if ind.get("mm_cross_a"):       indicators.append(f"CrossMM{ind.get('mm_cross_a')}/{ind.get('mm_cross_b')}")
    ind_str = " + ".join(indicators) if indicators else "Aucun"

    pos_str = f"Ouverte @ {pos['entry_price']:.2f}$" if pos else "Fermée"

    log(
        f"{prefix} {'SHORT' if is_short else 'LONG'} | {symbol} | {timeframe} | "
        f"Capital: {balance:.2f}$ | PnL: {pnl:+.2f}$ | {trades} trades | "
        f"Position: {pos_str} | Taille: {size}% | TP: {tp}% SL: {sl}% | "
        f"Check: {check} | Indicateurs: {ind_str}",
        max_logs=1000
    )


from src.utils.bot_state import
from src.utils.binance_client import BinanceClient
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal


def run():
    log(f"{BOT_PREFIX} 🤖 Bot MAINNET démarré — ⚠️ ARGENT RÉEL")

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
            # La confirmation "OUI" se fait via Streamlit (bouton Démarrer)
            if client is None:
                client = BinanceClient(testnet=False)
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
            size_pct  = min(cfg.get("size_pct", 10), 20)  # max 20% en mainnet
            ind_entry = cfg.get("ind_entry", {})
            ind_exit  = cfg.get("ind_exit",  {})

            # ── Bougies ────────────────────────────────────────────────────
            df = client.get_klines(symbol, timeframe, limit=300)
            if df.empty or len(df) < 3:
                log(f"{BOT_PREFIX} ⚠️ Données insuffisantes pour {symbol}")
                time.sleep(60)
                continue

            # ── Indicateurs ────────────────────────────────────────────────
            ind_merged = {
                "use_rsi":          ind_entry.get("use_rsi", False) or ind_exit.get("use_rsi", False),
                "rsi_period":       ind_entry.get("rsi_period", 14),
                "use_macd":         ind_entry.get("use_macd", False) or ind_exit.get("use_macd", False),
                "use_bollinger":    ind_entry.get("use_bollinger", False) or ind_exit.get("use_bollinger", False),
                "btc_mm":           None,
                "mm_align_periods": ind_entry.get("mm_align_periods", []),
            }
            df_ind = apply_all_indicators(df, ind_merged)

            candle_t1  = df_ind.iloc[-1]
            exec_price = float(candle_t1["open"])
            high_t1    = float(candle_t1["high"])
            low_t1     = float(candle_t1["low"])

            state["last_check"] = datetime.now().isoformat()
            state["last_price"] = exec_price

            # ── Signaux ────────────────────────────────────────────────────
            sig_entry = _build_signal(df_ind, ind_entry, side="buy"  if not is_short else "sell")
            sig_exit  = _build_signal(df_ind, ind_exit,  side="sell" if not is_short else "buy")

            entry_signal = bool(sig_entry.iloc[-2])
            exit_signal  = bool(sig_exit.iloc[-2])
            pos          = state.get("position")

            log(
                f"[MAINNET] {symbol} @ {exec_price:.4f} | "
                f"Entrée: {'✅' if entry_signal else '❌'} | "
                f"Sortie: {'✅' if exit_signal else '❌'}"
            )

            # ── Entrée ─────────────────────────────────────────────────────
            if pos is None and entry_signal:
                balance = client.get_balance("USDT")
                size    = min(balance * (size_pct / 100), MAX_TRADE_SIZE_USDT)
                if size < 10:
                    log(f"{BOT_PREFIX} {BOT_PREFIX} ⚠️ Solde insuffisant")
                else:
                    qty = round(size / exec_price, 6)
                    res = client.buy(symbol, qty)
                    if res and res["ok"]:
                        fill = res.get("fill_price") or exec_price
                        state["position"] = {
                            "symbol":      symbol,
                            "side":        "LONG",
                            "is_short":    False,
                            "entry_price": fill,
                            "qty":         qty,
                            "size_usdt":   size,
                            "ts":          datetime.now().isoformat(),
                        }
                        log(f"{BOT_PREFIX} ✅ [MAINNET] LONG ouvert @ {fill:.4f} | {size:.2f} USDT")
                    else:
                        log(f"{BOT_PREFIX} ❌ [MAINNET] Ordre échoué : {res}")

            # ── Sortie ─────────────────────────────────────────────────────
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
                            "side":        "LONG",
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
                        log(f"{BOT_PREFIX} 🔴 [MAINNET] Fermé : {exit_reason} @ {fill:.4f} | PnL: {pnl_usd:+.2f}$")
                    else:
                        log(f"{BOT_PREFIX} ❌ [MAINNET] Vente échouée : {res}")

            save_state(state)
            check_time_utc = cfg.get("check_time_utc")
            interval_min   = cfg.get("interval_min")
            wait_until_next_check(timeframe, check_time_utc, interval_min)

        except KeyboardInterrupt:
            log(f"{BOT_PREFIX} {BOT_PREFIX} Bot MAINNET arrêté (Ctrl+C)")
            break
        except Exception as e:
            log(f"{BOT_PREFIX} ⚠️ Erreur mainnet : {e}")
            time.sleep(60)


if __name__ == "__main__":
    run()
