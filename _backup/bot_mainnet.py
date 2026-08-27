"""
bot_mainnet.py — VERSION CORRIGÉE (voir commentaires "# FIX n" pour le détail)
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

---------------------------------------------------------------------------
CHANGEMENTS PAR RAPPORT À L'ORIGINAL (bot_mainnet.py) :

FIX 1 — Double exposition non protégée après échec de fermeture d'urgence.
  Avant : si le SL natif échouait ET la fermeture d'urgence échouait aussi,
  le code faisait quand même `state["position"] = None`. Le bot croyait donc
  n'avoir aucune position et pouvait en ouvrir une nouvelle au cycle suivant,
  alors que l'ancienne restait réellement ouverte sur Hyperliquid, sans
  aucune protection SL/TP.
  Maintenant : la position n'est effacée du state QUE si la fermeture
  d'urgence a réellement réussi. Sinon elle reste marquée
  `protected: False` — ce qui bloque toute nouvelle entrée (car l'entrée
  exige `pos is None`) et déclenche une nouvelle tentative de pose du SL/TP
  natif à chaque cycle tant que ce n'est pas résolu.

FIX 2 — Le bouton "stop" / changement de stratégie depuis Streamlit pouvait
  être écrasé par le bot en fin de cycle.
  Avant : le bot lisait le state en début de boucle, travaillait sur cette
  copie en mémoire pendant tout le cycle (jusqu'à plusieurs minutes selon le
  timeframe), puis réécrivait TOUT le state à la fin — y compris les champs
  "status" et "strategy" figés depuis le début du cycle. Si l'utilisateur
  cliquait "stop" ou changeait la config pendant ce temps, sa modification
  était perdue.
  Maintenant : juste avant la sauvegarde finale, on relit le state à jour
  et on ne réécrit que les champs que le bot possède réellement (position,
  trades, pnl_session, last_check, last_price, last_entry_date). Les champs
  pilotés par l'utilisateur (status, strategy) restent ceux les plus
  récents, peu importe quand ils ont été modifiés pendant le cycle.

FIX 3 — Aucun garde-fou de perte maximale.
  Avant : seul un SL par trade existait. Rien n'empêchait une série de
  pertes de continuer indéfiniment.
  Maintenant : un kill switch optionnel bloque les NOUVELLES entrées (les
  sorties/fermetures restent toujours actives) si la perte cumulée de la
  session dépasse `max_loss_pct` % du capital initial (`balance_init`).
  Réglable via la clé "max_loss_pct" dans le JSON de config (défaut : 20%).

FIX 4 — Pas de plafond sur le levier.
  Avant : le levier du JSON était envoyé tel quel à Hyperliquid, sans
  validation — une erreur de saisie (ex: 250 au lieu de 2.5) partait
  directement en production.
  Maintenant : le levier est plafonné à MAX_LEVERAGE (25 par défaut) avec
  un log d'avertissement si la valeur configurée dépasse ce plafond.
---------------------------------------------------------------------------
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

# Détecter le side (long/short) depuis le nom du fichier config
# "bot_state_mainnet_short.json" → side = "short"
# "bot_state_mainnet_long.json"  → side = "long"
_hl_side = "short" if "short" in _basename.lower() else "long"

print(f"{BOT_PREFIX} Fichier JSON : {_bs.STATE_FILE}")

get_state  = _bs.get_state
save_state = _bs.save_state
log        = _bs.log

# ---------------------------------------------------------------------------
# FIX 4 — Plafond de sécurité sur le levier
# ---------------------------------------------------------------------------
MAX_LEVERAGE = 25

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
                client = HyperliquidClient(side=_hl_side)
                res    = client.test_connection()
                if not res["ok"]:
                    log(f"{BOT_PREFIX} ⚠️ Connexion HL impossible : {res['message']} — réessai dans 60s",
                        max_logs=5000)
                    client = None
                    time.sleep(60)
                    continue
                log(f"{BOT_PREFIX} {res['message']}", max_logs=5000)

            # ── Vérification synchronisation position JSON/HL ─────────────
            pos_json = state.get("position")
            if pos_json:
                try:
                    hl_state   = client._post_info({"type": "clearinghouseState", "user": client.address})
                    hl_positions = hl_state.get("assetPositions", [])
                    _sym_check = pos_json.get("symbol", "BTC")
                    pos_on_hl  = any(
                        float(p.get("position", {}).get("szi", 0)) != 0
                        for p in hl_positions
                        if p.get("position", {}).get("coin") == _sym_check
                    )
                    if not pos_on_hl:
                        # Position fermée par HL (SL/TP natif) sans que le bot le sache
                        log(f"{BOT_PREFIX} 🔄 Position fermée par HL (SL/TP natif) — mise à jour JSON", max_logs=5000)
                        # Estimer le PnL depuis le dernier prix connu
                        _last_price = state.get("last_price") or pos_json["entry_price"]
                        _pnl_pct = (_last_price - pos_json["entry_price"]) / pos_json["entry_price"] * 100 if not pos_json.get("is_short") else (pos_json["entry_price"] - _last_price) / pos_json["entry_price"] * 100
                        _pnl_usd = round(pos_json["qty"] * _last_price - pos_json["size_usdt"], 2) if not pos_json.get("is_short") else round(pos_json["size_usdt"] - pos_json["qty"] * _last_price, 2)
                        state["trades"].append({
                            "ts": datetime.now().isoformat(),
                            "symbol": pos_json["symbol"],
                            "side": pos_json["side"],
                            "entry_price": pos_json["entry_price"],
                            "exit_price": _last_price,
                            "qty": pos_json["qty"],
                            "pnl_pct": round(_pnl_pct, 2),
                            "pnl_usd": _pnl_usd,
                            "raison": "SL/TP natif HL",
                        })
                        state["pnl_session"] = sum(t.get("pnl_usd", 0) for t in state["trades"])
                        state["position"] = None
                        save_state(state)
                        state = get_state()
                except Exception as e:
                    log(f"{BOT_PREFIX} ⚠️ Erreur vérif position HL : {e}", max_logs=5000)

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

            leverage       = int(cfg.get("leverage", 1))
            # FIX 4 — plafond de sécurité sur le levier
            if leverage > MAX_LEVERAGE:
                log(f"{BOT_PREFIX} ⚠️ Levier configuré ({leverage}x) > plafond de sécurité "
                    f"({MAX_LEVERAGE}x) — bridé à {MAX_LEVERAGE}x", max_logs=5000)
                leverage = MAX_LEVERAGE
            check_time_utc = cfg.get("check_time_utc")
            interval_min   = cfg.get("interval_min")

            # FIX 3 — kill switch de perte maximale (bloque les nouvelles entrées seulement)
            balance_init   = float(state.get("balance_init", 1000.0)) or 1000.0
            max_loss_pct   = float(cfg.get("max_loss_pct", 20))
            max_loss_usd   = balance_init * (max_loss_pct / 100)
            pnl_session_now = float(state.get("pnl_session", 0))
            kill_switch_active = pnl_session_now <= -max_loss_usd

            # ── 1. Log immédiat au début du cycle ──────────────────────────
            sleep_sec_next = next_sleep(timeframe, check_time_utc, interval_min)
            next_check     = datetime.now(timezone.utc) + timedelta(seconds=sleep_sec_next)
            pos_now        = state.get("position")
            pos_str_now    = f"Ouverte @ {pos_now['entry_price']:.2f}$" if pos_now else "Fermée"
            log(f"{BOT_PREFIX} ✔️ En ligne | {symbol} | {timeframe} | "
                f"Position: {pos_str_now} | "
                f"Prochain check à {next_check.strftime('%H:%M:%S')} UTC", max_logs=5000)

            if kill_switch_active:
                log(f"{BOT_PREFIX} 🛑 Kill switch actif — perte session {pnl_session_now:+.2f}$ "
                    f"≤ seuil -{max_loss_usd:.2f}$ ({max_loss_pct:.0f}% du capital) — "
                    f"nouvelles entrées bloquées, positions existantes toujours gérées", max_logs=5000)

            # FIX 1 — si une position ouverte précédemment n'a pas pu être protégée
            # (SL natif + fermeture d'urgence tous deux échoués au cycle précédent),
            # on retente de poser le SL/TP natif à chaque cycle tant que ce n'est pas résolu.
            pos_unprotected = state.get("position") and not state["position"].get("protected", True)
            if pos_unprotected:
                _p = state["position"]
                log(f"{BOT_PREFIX} 🚨 Position {_p['side']} @ {_p['entry_price']:.2f}$ toujours SANS SL/TP natif "
                    f"— nouvelle tentative de pose", max_logs=5000)
                _tp_native = _p["entry_price"] * (1 + tp_pct / 100) if tp_pct and not _p["is_short"] else (_p["entry_price"] * (1 - tp_pct / 100) if tp_pct else None)
                _sl_native = _p["entry_price"] * (1 - sl_pct / 100) if sl_pct and not _p["is_short"] else (_p["entry_price"] * (1 + sl_pct / 100) if sl_pct else None)
                if _tp_native or _sl_native:
                    _retry = client.set_tp_sl(
                        asset=_p["symbol"], size=_p["qty"], is_short=_p["is_short"],
                        tp_price=_tp_native, sl_price=_sl_native,
                    )
                    if _retry.get("sl_ok", False) or not _sl_native:
                        state["position"]["protected"] = True
                        log(f"{BOT_PREFIX} 🛡️ SL/TP natif reposé avec succès — position de nouveau protégée", max_logs=5000)
                    else:
                        log(f"{BOT_PREFIX} ❌ Nouvelle tentative de pose du SL échouée — "
                            f"INTERVENTION MANUELLE TOUJOURS REQUISE", max_logs=5000)

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
                "bollinger_period": ind_entry.get("bollinger_period", 20),
                "bollinger_std":    ind_entry.get("bollinger_std", 2.0),
                "btc_mm":           None,
                "mm_align_periods": list(set(
                    ind_entry.get("mm_align_periods", []) +
                    ind_exit.get("mm_align_periods", [])
                )),
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
            # Vérifier si on a déjà traité ce signal aujourd'hui (last_entry_date)
            today_utc       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            last_entry_date = state.get("last_entry_date")
            already_checked = last_entry_date == today_utc

            # first_run = True → on ne prend pas de position au premier cycle
            # already_checked = True → signal déjà vu aujourd'hui, on attend demain
            # kill_switch_active = True → perte max de session atteinte, plus de nouvelles entrées (FIX 3)
            if pos is None and entry_signal and not first_run and not already_checked and not kill_switch_active:
                balance  = client.get_balance()
                size_usd = balance * (size_pct / 100)

                # Notional = marge × levier
                notional = size_usd * leverage

                if size_usd < 10:
                    log(f"{BOT_PREFIX} ⚠️ Solde insuffisant ({balance:.2f} USDC)", max_logs=5000)
                else:
                    # Configurer le levier sur HL avant d'ouvrir
                    if leverage > 1:
                        lev_res = client.set_leverage(symbol, leverage)
                        if lev_res["ok"]:
                            log(f"{BOT_PREFIX} ⚙️ Levier {leverage}x configuré sur {symbol}", max_logs=5000)
                        else:
                            log(f"{BOT_PREFIX} ⚠️ Échec config levier : {lev_res} — ouverture en x1", max_logs=5000)

                    # Long → buy / Short → short (ordre sans reduce_only)
                    # On envoie le notional comme taille en USDC
                    res = client.buy(symbol, notional) if not is_short else client.short(symbol, notional)
                    if res and res["ok"]:
                        fill = res.get("fill_price") or exec_price
                        qty  = round(notional / fill, 6)
                        state["position"] = {
                            "symbol":      symbol,
                            "side":        "LONG" if not is_short else "SHORT",
                            "is_short":    is_short,
                            "entry_price": fill,
                            "qty":         qty,
                            "size_usdt":   notional,   # notional pour PnL correct
                            "margin_usdt": size_usd,   # marge réelle engagée
                            "leverage":    leverage,
                            "ts":          datetime.now().isoformat(),
                            "protected":   False,  # FIX 1 — passe à True seulement si le SL/TP natif est confirmé posé
                        }
                        log(f"{BOT_PREFIX} ✅ {'LONG' if not is_short else 'SHORT'} ouvert "
                            f"@ {fill:.2f} | {notional:.2f} USDC notional (marge: {size_usd:.2f} USDC, x{leverage})", max_logs=5000)

                        # ── TP/SL natifs HL — protection temps réel ────────
                        tp_price_native = fill * (1 + tp_pct / 100) if tp_pct and not is_short else (fill * (1 - tp_pct / 100) if tp_pct else None)
                        sl_price_native = fill * (1 - sl_pct / 100) if sl_pct and not is_short else (fill * (1 + sl_pct / 100) if sl_pct else None)
                        if tp_price_native or sl_price_native:
                            tpsl_res = client.set_tp_sl(
                                asset=symbol,
                                size=qty,
                                is_short=is_short,
                                tp_price=tp_price_native,
                                sl_price=sl_price_native,
                            )
                            tp_ok = tpsl_res.get("tp_ok", False) if tp_price_native else True
                            sl_ok = tpsl_res.get("sl_ok", False) if sl_price_native else True

                            if tp_ok and sl_ok:
                                state["position"]["protected"] = True
                                log(f"{BOT_PREFIX} 🛡️ TP/SL natifs posés sur HL — "
                                    f"TP: {tp_price_native:.0f}$ | SL: {sl_price_native:.0f}$", max_logs=5000)
                            elif not sl_ok:
                                # SL échoué = pas de protection → fermeture d'urgence
                                log(f"{BOT_PREFIX} 🚨 SL natif échoué — fermeture d'urgence de la position !", max_logs=5000)
                                urgence_res = client.sell(symbol, qty) if not is_short else client.close_short(symbol, qty)
                                if urgence_res and urgence_res["ok"]:
                                    log(f"{BOT_PREFIX} ✅ Position fermée en urgence (pas de SL posé)", max_logs=5000)
                                    # FIX 1 — la position est réellement fermée, on peut l'effacer du state
                                    state["position"] = None
                                else:
                                    # FIX 1 — fermeture d'urgence ÉCHOUÉE : la position est TOUJOURS
                                    # ouverte sur Hyperliquid. On NE l'efface PAS du state, sinon le bot
                                    # croirait à tort n'avoir aucune position et pourrait en ouvrir une
                                    # seconde par-dessus, sans protection, au cycle suivant.
                                    log(f"{BOT_PREFIX} ❌ Échec fermeture urgence : {urgence_res} — "
                                        f"INTERVENTION MANUELLE REQUISE — position gardée en state comme "
                                        f"'non protégée', nouvelle tentative de pose du SL au prochain cycle",
                                        max_logs=5000)
                                    state["position"]["protected"] = False
                            else:
                                # TP échoué mais SL OK → on garde la position, juste un warning
                                state["position"]["protected"] = True
                                log(f"{BOT_PREFIX} ⚠️ TP natif échoué mais SL OK — position gardée sans TP automatique", max_logs=5000)
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

            # ── Sauvegarder la date du check uniquement si on a vraiment vérifié ─
            # (pas en first_run pour ne pas bloquer le lendemain après un restart)
            if not first_run:
                state["last_entry_date"] = today_utc

            # ── 7. Log état final + save ───────────────────────────────────
            pos         = state.get("position")
            bal         = client.get_balance()
            pos_str     = f"Ouverte @ {pos['entry_price']:.2f}$" if pos else "Fermée"
            pnl_session = float(state.get("pnl_session", 0))
            nb_trades   = len(state.get("trades", []))
            log(f"{BOT_PREFIX} {'SHORT' if is_short else 'LONG'} | {symbol} | {timeframe} | "
                f"Balance: {bal:.2f} USDC | PnL session: {pnl_session:+.2f}$ | {nb_trades} trades | "
                f"Position: {pos_str}", max_logs=5000)

            # FIX 2 — on relit le state à jour et on ne réécrit QUE les champs
            # que le bot possède réellement, pour ne pas écraser un "stop" ou
            # un changement de stratégie fait depuis Streamlit pendant le cycle.
            fresh                     = get_state()
            fresh["log"]              = fresh["log"]          # déjà à jour (via log())
            fresh["position"]         = state["position"]
            fresh["trades"]           = state["trades"]
            fresh["pnl_session"]      = state["pnl_session"]
            fresh["last_check"]       = datetime.now().isoformat()
            fresh["last_price"]       = exec_price
            fresh["last_entry_date"]  = state.get("last_entry_date", fresh.get("last_entry_date"))
            save_state(fresh)

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
