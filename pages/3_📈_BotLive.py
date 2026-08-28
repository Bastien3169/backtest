"""
pages/3_📈_BotLive.py
Monitoring et configuration du bot de trading.
"""

import sys
import os
import glob

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import extra_streamlit_components as stx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

import src.utils.bot_state as _bs_module
from src.utils.binance_client import BinanceClient
from src.utils.data_loader import get_all_assets
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Bot Live", page_icon="📈", layout="wide")

# ---------------------------------------------------------------------------
# 🔒 Protection par mot de passe
# ---------------------------------------------------------------------------
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "")

if BOT_PASSWORD:
    gestionnaire_cookies = stx.CookieManager(key="bot_auth_manager")
    cookie_auth = gestionnaire_cookies.get("bot_auth")

    if cookie_auth != "ok":
        st.title("🔒 Accès protégé")
        saisie = st.text_input("Mot de passe", type="password", key="saisie_mdp")

        if saisie == BOT_PASSWORD:
            gestionnaire_cookies.set("bot_auth", "ok", max_age=30 * 24 * 3600)
            st.rerun()
        elif saisie:
            st.error("❌ Mot de passe incorrect")

        st.stop()

# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------
st.title("📈 Bot Trading — Monitoring")

# ---------------------------------------------------------------------------
# Sélecteur de bot
# ---------------------------------------------------------------------------
_data_dir   = os.getenv("DATA_DIR", _ROOT)
_json_files = sorted(glob.glob(os.path.join(_data_dir, "bot_state*.json")))

if not _json_files:
    st.error(f"⚠️ Aucun fichier `bot_state*.json` trouvé dans `{_data_dir}`. Lance d'abord `python start.py`.")
    st.stop()

_json_labels = [os.path.basename(f) for f in _json_files]

_selected_json        = st.selectbox("📂 Bot à configurer / monitorer", _json_labels, index=0)
_bs_module.STATE_FILE = os.path.join(_data_dir, _selected_json)

get_state  = _bs_module.get_state
save_state = _bs_module.save_state
reset      = _bs_module.reset

# Détection du side depuis le nom du JSON — utilisé partout dans la page
bot_side = "short" if "short" in _selected_json.lower() else ("free" if "free" in _selected_json.lower() else "long")

def get_hl_client():
    """Retourne un HyperliquidClient pour le bon compte (long ou short)."""
    from src.utils.hyperliquid_client import HyperliquidClient
    return HyperliquidClient(side=bot_side)

# ---------------------------------------------------------------------------
# 1️⃣ Mode de trading
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Mode de trading")

mode = st.radio(
    "Mode",
    ["🖥️ Local (simulation)", "🧪 Testnet Binance (faux argent)", "💰 Mainnet Hyperliquid (vrai argent)"],
    horizontal=True,
)
is_local   = "Local"   in mode
is_testnet = "Testnet" in mode
is_mainnet = "Mainnet" in mode

if is_local:
    st.info("**Mode Local** — Données Binance public, simulation pure dans le JSON. Lance `python bot_local.py`")
elif is_testnet:
    st.info("**Mode Testnet** — Binance testnet, clé gratuite, faux argent. Lance `python bot_testnet.py`")
else:
    st.error("**⚠️ Mode Mainnet Hyperliquid — VRAI ARGENT.** Lance `python bot_mainnet.py` dans un terminal.")

if is_testnet:
    with st.expander("🔑 Connexion Binance Testnet", expanded=False):
        api_key = os.getenv("BINANCE_TESTNET_API_KEY")
        if api_key:
            st.success("✅ Clés chargées depuis `.env`")
        else:
            st.warning("Clés manquantes dans `.env`")
            st.markdown("""
1. Aller sur [testnet.binance.vision](https://testnet.binance.vision)
2. Connexion GitHub → Generate HMAC_SHA256 Key
3. Ajouter dans `.env` :
```
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_SECRET_KEY=...
```
""")
        if st.button("🔌 Tester la connexion Binance"):
            try:
                client = BinanceClient(testnet=True)
                res    = client.test_connection()
                if res["ok"]:
                    st.success(res["message"])
                else:
                    st.error(res["message"])
            except Exception as e:
                st.error(str(e))

if is_mainnet:
    with st.expander("🔑 Connexion Hyperliquid", expanded=False):
        hl_key = os.getenv("HL_PRIVATE_KEY")
        if hl_key:
            st.success("✅ Clés HL chargées depuis `.env`")
        else:
            st.warning("Clés manquantes dans `.env`")
            st.markdown("""
1. Aller sur [app.hyperliquid.xyz](https://app.hyperliquid.xyz)
2. Connecter MetaMask → Settings → API Keys → Generate
3. Ajouter dans Railway Variables :
```
HL_PRIVATE_KEY=0x...
HL_WALLET_ADDRESS=0x...
```
""")
        if st.button("🔌 Tester la connexion Hyperliquid"):
            try:
                client_test = get_hl_client()
                res = client_test.test_connection()
                if res["ok"]:
                    st.success(res["message"])
                else:
                    st.error(res["message"])
            except Exception as e:
                st.error(str(e))

st.divider()

# ---------------------------------------------------------------------------
# 2️⃣ Configuration de la stratégie
# ---------------------------------------------------------------------------
st.subheader("2️⃣ Configuration")

direction = st.radio("Direction", ["🟢 Long", "🔴 Short"], horizontal=True, key="bot_dir")
is_short  = direction == "🔴 Short"

cfg1, cfg2, cfg3 = st.columns(3)

# ── Ligne 1 : Actif | Taille de position | Rythme de check ──────────────────
with cfg1:
    _all_assets   = get_all_assets()
    _asset_labels = [f"{c['symbol']} — {c['name']}" for c in _all_assets]
    _asset_map    = {f"{c['symbol']} — {c['name']}": c["id"] for c in _all_assets}

    asset_label = st.selectbox("Actif", _asset_labels, index=0)
    asset_id    = _asset_map[asset_label]

    if is_local:
        symbol = asset_id
    else:
        if asset_id.startswith("^"):
            st.warning(f"⚠️ {asset_label} est un indice — non disponible sur Binance.")
            symbol = "BTCUSDT"
        else:
            symbol = asset_id.replace("-USD", "USDT").replace("-USDT", "USDT")

with cfg2:
    if is_local:
        capital = st.number_input("Capital fictif ($)", 100.0, 100000.0, 1000.0, 100.0)
    elif is_mainnet:
        size_pct = st.number_input("% du solde par trade", 1, 100, 10, 1, key="size_pct_hl")
        capital  = 0.0
    else:
        size_pct = st.number_input("% du solde par trade", 1, 100, 95, 1)
        capital  = 0.0

with cfg3:
    timing_mode = st.selectbox(
        "Rythme de check", ["Intervalle (min)", "Heure fixe UTC"],
        key="bot_timing_mode_v2",
    )

# ── Ligne 2 : Timeframe | Levier | Intervalle ou heure ──────────────────────
with cfg1:
    timeframe = st.selectbox(
        "Timeframe",
        ["1m", "5m", "15m", "1h", "4h", "1d", "1w"] if not is_local
        else ["1m", "5m", "15m", "heure", "4h", "jour", "semaine"],
        index=3,
    )

with cfg2:
    if is_local:
        size_pct = st.number_input("% du capital par trade", 1, 100, 100, 1)
        leverage = 1
    elif is_mainnet:
        leverage = st.number_input("Levier (x)", 1, 20, 1, 1, key="leverage_hl")
    else:
        leverage = 1
        st.number_input("Levier (x)", 1, 1, 1, 1, disabled=True,
                        help="Levier non géré sur ce mode", key="leverage_dummy")

with cfg3:
    check_time_utc = None
    interval_min   = None
    if timing_mode == "Heure fixe UTC":
        check_time_utc = st.text_input(
            "Heure UTC (HH:MM)", value="00:01",
            help="France = UTC+1 hiver / UTC+2 été",
        )
    else:
        interval_min = st.number_input(
            "Intervalle (minutes)", 1, 1440, 15, 1,
            help="Synchronisé sur les heures rondes UTC",
        )

# ── Ligne 3 : récapitulatifs (sous les champs, n'affecte plus l'alignement) ──
with cfg2:
    if is_local:
        st.caption(f"→ {capital * size_pct / 100:.2f} $ par trade")
    elif is_mainnet:
        try:
            solde_hl = get_hl_client().get_balance()
        except Exception:
            solde_hl = 0.0
        notional = solde_hl * size_pct / 100 * leverage
        st.caption(
            f"Solde HL : **{solde_hl:.2f} USDC** — "
            f"{solde_hl * size_pct / 100:.2f} USDC par trade"
        )
        st.caption(f"→ Notional : {notional:.2f} USDC (x{leverage})")
    else:
        st.caption("Solde réel chargé depuis Binance testnet")

with cfg3:
    if timing_mode == "Heure fixe UTC":
        st.caption("🇫🇷 00:01 UTC = 01h01 hiver / 02h01 été")

st.divider()

with st.container(border=True):
    st.markdown(f"#### {'🟢 Indicateurs d\'achat' if not is_short else '🔴 Indicateurs d\'entrée short'}")
    ind_entry = render_indicator_bloc("buy" if not is_short else "sell", "bot_entry")

st.write("")

with st.container(border=True):
    st.markdown(f"#### {'🔴 Indicateurs de vente' if not is_short else '🟢 Indicateurs de sortie short'}")
    st.caption("Vente déclenchée si **TP/SL atteint OU indicateur de sortie actif** — laisser vide = hold")
    _tp_col, _sl_col = st.columns(2)
    with _tp_col:
        tp_pct = st.number_input("Take Profit (%)", 0.0, 100.0, 5.0, 0.5, key="bot_tp")
        tp_pct = tp_pct if tp_pct > 0 else None
    with _sl_col:
        sl_pct = st.number_input("Stop Loss (%)", 0.0, 50.0, 2.5, 0.5, key="bot_sl")
        sl_pct = sl_pct if sl_pct > 0 else None
    ind_exit = render_indicator_bloc("sell" if not is_short else "buy", "bot_exit")

st.divider()

# ---------------------------------------------------------------------------
# 3️⃣ Contrôles
# ---------------------------------------------------------------------------
st.subheader("3️⃣ Contrôles")

state = get_state()
c1, c2, c3, c4 = st.columns(4)

with c1:
    if st.button("▶️ Démarrer", type="primary", disabled=state.get("status") == "running"):
        new_state = get_state()
        new_state["status"] = "running"
        new_state["mode"]   = "local" if is_local else ("testnet" if is_testnet else "mainnet")
        if is_local:
            new_state["balance"]      = capital
            new_state["balance_init"] = capital
        new_state["strategy"] = {
            "symbol":         symbol,
            "timeframe":      timeframe,
            "size_pct":       size_pct,
            "tp_pct":         tp_pct,
            "sl_pct":         sl_pct,
            "is_short":       is_short,
            "check_time_utc": check_time_utc,
            "interval_min":   interval_min,
            "ind_entry":      ind_entry,
            "ind_exit":       ind_exit,
            "leverage":       leverage if is_mainnet else 1,
        }
        save_state(new_state)
        bot_cmd = {"local": "python bot_local.py", "testnet": "python bot_testnet.py", "mainnet": "python bot_mainnet.py"}[new_state["mode"]]
        st.success(f"✅ Config sauvegardée — Lance maintenant : `{bot_cmd}`")
        st.rerun()

with c2:
    if st.button("⏹️ Arrêter", disabled=state.get("status") != "running"):
        s = get_state()
        s["status"] = "stopped"
        save_state(s)
        if s.get("position") and is_mainnet:
            st.warning("⚠️ Bot arrêté mais position toujours ouverte sur HL — utilise '🔴 Arrêter + Fermer' pour tout couper.")
        st.rerun()

with c3:
    if st.button("🔄 Rafraîchir"):
        st.rerun()

# Bouton Arrêter + Fermer
pos_ouverte = get_state().get("position")
if is_mainnet and pos_ouverte and state.get("status") == "running":
    st.caption(
        "Arrête le bot ET ferme sa position sur HL. "
        "La quantité fermée est relue en direct depuis Hyperliquid "
        "(voir le panneau 📡 pour les chiffres réels)."
    )
    if st.button("🔴 Arrêter + Fermer position", type="primary"):
        try:
            client_stop  = get_hl_client()
            symbol_stop  = pos_ouverte.get("symbol", "BTC")
            # SÉCURITÉ : relire la position REELLE sur HL. Un qty local périmé
            # (renfort ou clôture partielle hors app) laisserait un reliquat
            # ouvert et NON protégé sur Hyperliquid.
            _vrai_stop   = client_stop.get_position(symbol_stop)
            if _vrai_stop is None:
                st.warning("Aucune position " + symbol_stop + " sur HL — le bot est simplement arrêté.")
                _s_stop = get_state()
                _s_stop["status"]   = "stopped"
                _s_stop["position"] = None
                save_state(_s_stop)
                st.rerun()
            qty_stop     = round(_vrai_stop["qty"], 5)
            is_short_pos = _vrai_stop["is_short"]
            res = client_stop.close_short(symbol_stop, qty_stop) if is_short_pos else client_stop.sell(symbol_stop, qty_stop)
            if res and res["ok"]:
                fill    = res.get("fill_price") or pos_ouverte["entry_price"]
                pnl_pct = (fill - pos_ouverte["entry_price"]) / pos_ouverte["entry_price"] * 100 if not is_short_pos else (pos_ouverte["entry_price"] - fill) / pos_ouverte["entry_price"] * 100
                pnl_usd = round(pos_ouverte["qty"] * fill - pos_ouverte.get("size_usdt", 0), 2) if not is_short_pos else round(pos_ouverte.get("size_usdt", 0) - pos_ouverte["qty"] * fill, 2)
                s = get_state()
                s["status"] = "stopped"
                s["trades"].append({
                    "ts": datetime.now().isoformat(), "symbol": pos_ouverte["symbol"],
                    "side": pos_ouverte["side"], "entry_price": pos_ouverte["entry_price"],
                    "exit_price": fill, "qty": pos_ouverte["qty"],
                    "pnl_pct": round(pnl_pct, 2), "pnl_usd": pnl_usd,
                    "raison": "Arrêt + Clôture forcée",
                })
                s["position"] = None
                save_state(s)
                st.success(f"✅ Bot arrêté + Position fermée @ {fill:.2f}$ | PnL: {pnl_usd:+.2f}$")
                st.rerun()
            else:
                st.error(f"❌ Échec clôture HL : {res}")
        except Exception as e:
            st.error(f"❌ Erreur : {e}")

with c4:
    if st.button("🗑️ Reset session"):
        pos = get_state().get("position")
        if pos and not is_local:
            position_existe_sur_hl = False
            if is_mainnet:
                try:
                    client_reset   = get_hl_client()
                    state_hl       = client_reset._post_info({"type": "clearinghouseState", "user": client_reset.address})
                    positions_hl   = state_hl.get("assetPositions", [])
                    symbol_reset   = pos.get("symbol", "BTC")
                    position_existe_sur_hl = any(
                        p.get("position", {}).get("coin") == symbol_reset
                        for p in positions_hl
                    )
                except Exception:
                    position_existe_sur_hl = True

            if position_existe_sur_hl:
                st.error(
                    "⚠️ Position encore ouverte sur HL ! Ferme-la d'abord "
                    "depuis le panneau 📡 Positions ouvertes sur Hyperliquid."
                )
            else:
                reset()
                st.rerun()
        else:
            reset()
            st.rerun()

# Bouton Forcer entrée
if is_mainnet and state.get("status") == "running" and not get_state().get("position"):
    st.divider()
    st.markdown("**⚡ Forcer une entrée maintenant**")
    st.caption("Ignore last_entry_date et entre immédiatement au prix du marché")
    direction_forcee = st.radio("Direction", ["🟢 Long", "🔴 Short"], horizontal=True, key="force_dir")
    is_short_force   = direction_forcee == "🔴 Short"
    if st.button("⚡ Forcer entrée", type="primary"):
        try:
            client_entree   = get_hl_client()
            balance_entree  = client_entree.get_balance()
            config_entree   = get_state().get("strategy", {})
            size_pct_entree = config_entree.get("size_pct", 10)
            leverage_entree = config_entree.get("leverage", 1)
            size_usd_entree = balance_entree * (size_pct_entree / 100)
            notional_entree = size_usd_entree * leverage_entree
            symbol_entree   = config_entree.get("symbol", "BTCUSDT").replace("USDT", "")
            tp_pct_entree   = config_entree.get("tp_pct")
            sl_pct_entree   = config_entree.get("sl_pct")
            if size_usd_entree < 10:
                st.error(f"⚠️ Solde insuffisant ({balance_entree:.2f} USDC)")
            else:
                if leverage_entree > 1:
                    get_hl_client().set_leverage(symbol_entree, leverage_entree)
                res = client_entree.short(symbol_entree, notional_entree) if is_short_force else client_entree.buy(symbol_entree, notional_entree)
                if res and res["ok"]:
                    fill = res.get("fill_price", 0)
                    qty  = round(notional_entree / fill, 6)
                    s    = get_state()
                    s["position"] = {
                        "symbol": symbol_entree, "side": "SHORT" if is_short_force else "LONG",
                        "is_short": is_short_force, "entry_price": fill,
                        "qty": qty, "size_usdt": notional_entree,
                        "margin_usdt": size_usd_entree, "leverage": leverage_entree,
                        "ts": datetime.now().isoformat(),
                    }
                    s["last_entry_date"] = datetime.now().strftime("%Y-%m-%d")
                    save_state(s)
                    if tp_pct_entree or sl_pct_entree:
                        tp_prix = fill * (1 + tp_pct_entree/100) if tp_pct_entree and not is_short_force else (fill * (1 - tp_pct_entree/100) if tp_pct_entree else None)
                        sl_prix = fill * (1 - sl_pct_entree/100) if sl_pct_entree and not is_short_force else (fill * (1 + sl_pct_entree/100) if sl_pct_entree else None)
                        client_entree.set_tp_sl(symbol_entree, qty, is_short_force, tp_prix, sl_prix)
                    st.success(f"✅ {'SHORT' if is_short_force else 'LONG'} ouvert @ {fill:.2f}$ | {size_usd_entree:.2f} USDC")
                    st.rerun()
                else:
                    st.error(f"❌ Ordre échoué : {res}")
        except Exception as e:
            st.error(f"❌ Erreur : {e}")

if state.get("status") == "running":
    mode_key = state.get("mode", "local")
    st.info(f"🖥️ Le bot doit tourner dans un terminal : `python bot_{mode_key}.py`")

st.divider()

# ---------------------------------------------------------------------------
# 4️⃣ Monitoring temps réel
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 📡 Positions ouvertes sur Hyperliquid — SOURCE DE VÉRITÉ
# Lecture directe de HL à chaque affichage, indépendante du JSON local.
# Gère plusieurs positions simultanées : fermeture totale, fermeture partielle
# et renfort, symbole par symbole.
# ---------------------------------------------------------------------------
if is_mainnet:
    st.subheader("📡 Positions ouvertes sur Hyperliquid")
    st.caption("Lu en direct depuis HL — inclut les positions ouvertes à la main, hors bot.")

    def _resync_json_depuis_hl(symbole: str):
        """Aligne state['position'] du bot sur la réalité HL pour ce symbole.
        Ne touche pas au JSON si celui-ci suit un AUTRE symbole."""
        try:
            p_hl = get_hl_client().get_position(symbole)
        except Exception:
            return
        s_json = get_state()
        ancien = s_json.get("position") or {}
        if ancien and ancien.get("symbol") != symbole:
            return
        if p_hl is None:
            s_json["position"] = None
        else:
            s_json["position"] = {
                "symbol":      p_hl["symbol"],
                "side":        p_hl["side"],
                "is_short":    p_hl["is_short"],
                "entry_price": p_hl["entry_price"],
                "qty":         p_hl["qty"],
                "size_usdt":   p_hl["size_usdt"],
                "margin_usdt": p_hl.get("margin_used") or ancien.get("margin_usdt", 0),
                "leverage":    p_hl.get("leverage") or ancien.get("leverage", 1),
                "ts":          ancien.get("ts") or datetime.now().isoformat(),
                "protected":   ancien.get("protected", False),
            }
        save_state(s_json)

    try:
        _positions_live = get_hl_client().get_open_positions()
        _lecture_ok     = True
    except Exception as _e_live:
        _positions_live = []
        _lecture_ok     = False
        st.error("Impossible de lire les positions sur Hyperliquid : " + str(_e_live))

    if _lecture_ok and not _positions_live:
        st.info("Aucune position ouverte sur ce wallet d'après Hyperliquid.")

    _symbole_suivi = (get_state().get("position") or {}).get("symbol")

    for _p in _positions_live:
        _sym   = _p["symbol"]
        _suivi = (_sym == _symbole_suivi)
        _badge = "🔗 suivie par le bot" if _suivi else "⚠️ hors bot"
        _coul  = "#22C55E" if _p["unrealized_pnl"] >= 0 else "#EF4444"

        with st.container(border=True):
            _c1, _c2, _c3, _c4 = st.columns([1.4, 1.4, 1.4, 1.4])
            _c1.markdown("**" + _sym + "** — " + _p["side"])
            _c1.caption(_badge)
            _c2.markdown("Quantité : `" + str(round(_p["qty"], 6)) + "`")
            _c2.caption("Notional ≈ " + str(_p["size_usdt"]) + " $")
            _c3.markdown("Entrée moy. : `" + format(_p["entry_price"], ".4f") + "`")
            if _p["liquidation_px"]:
                _c3.caption("Liquidation : " + format(_p["liquidation_px"], ".4f"))
            _c4.markdown(
                "PnL latent : <span style='color:" + _coul + ";font-weight:bold'>"
                + format(_p["unrealized_pnl"], "+.2f") + " $</span>",
                unsafe_allow_html=True,
            )

            _t_close, _t_partiel, _t_renfort = st.tabs(
                ["🔴 Tout fermer", "✂️ Fermer une partie", "➕ Renforcer"]
            )

            # ── Fermeture totale ────────────────────────────────────────────
            with _t_close:
                if st.button("🔴 Fermer toute la position " + _sym, key="full_close_" + _sym):
                    try:
                        _cli = get_hl_client()
                        _vrai = _cli.get_position(_sym)
                        if _vrai is None:
                            st.warning("Position déjà fermée sur HL.")
                            _resync_json_depuis_hl(_sym)
                            st.rerun()
                        else:
                            _qte = round(_vrai["qty"], 5)
                            _res = (_cli.close_short(_sym, _qte) if _vrai["is_short"]
                                    else _cli.sell(_sym, _qte))
                            if _res and _res.get("ok"):
                                st.success("Position " + _sym + " fermée.")
                                _resync_json_depuis_hl(_sym)
                                st.rerun()
                            else:
                                st.error("Échec fermeture : " + str(_res))
                    except Exception as _e:
                        st.error("Erreur : " + str(_e))

            # ── Fermeture partielle ─────────────────────────────────────────
            with _t_partiel:
                _mode_p = st.radio(
                    "Fermer en", ["% de la position", "Montant USDC"],
                    horizontal=True, key="mode_part_" + _sym,
                )
                if _mode_p == "% de la position":
                    _val_p = st.slider("Part à fermer (%)", 1, 99, 50, key="pct_part_" + _sym)
                else:
                    _val_p = st.number_input(
                        "Montant à fermer (USDC de notional)",
                        min_value=1.0, value=float(max(10.0, _p["size_usdt"] / 2)),
                        step=10.0, key="usd_part_" + _sym,
                    )

                if st.button("✂️ Fermer cette partie de " + _sym, key="btn_part_" + _sym):
                    try:
                        _cli  = get_hl_client()
                        _vrai = _cli.get_position(_sym)
                        if _vrai is None:
                            st.warning("Position déjà fermée sur HL.")
                            _resync_json_depuis_hl(_sym)
                            st.rerun()
                        else:
                            if _mode_p == "% de la position":
                                _qte = _vrai["qty"] * (float(_val_p) / 100.0)
                            else:
                                _prix = _cli.get_price(_sym)
                                if not _prix:
                                    st.error("Prix indisponible, réessaie.")
                                    _qte = 0
                                else:
                                    _qte = float(_val_p) / float(_prix)
                            _qte = round(min(_qte, _vrai["qty"]), 5)

                            if _qte <= 0:
                                st.error("Quantité à fermer nulle après arrondi (position trop petite ?).")
                            elif abs(_qte - round(_vrai["qty"], 5)) < 1e-9:
                                st.warning(
                                    "Cela ferme la position ENTIÈRE — utilise l'onglet "
                                    "'Tout fermer' si c'est bien ce que tu veux."
                                )
                            else:
                                _res = (_cli.close_short(_sym, _qte) if _vrai["is_short"]
                                        else _cli.sell(_sym, _qte))
                                if _res and _res.get("ok"):
                                    st.success(
                                        "Fermé " + str(_qte) + " " + _sym
                                        + " — reste ≈ " + str(round(_vrai["qty"] - _qte, 6))
                                    )
                                    _resync_json_depuis_hl(_sym)
                                    st.rerun()
                                else:
                                    st.error("Échec fermeture partielle : " + str(_res))
                    except Exception as _e:
                        st.error("Erreur : " + str(_e))

            # ── Renfort ─────────────────────────────────────────────────────
            with _t_renfort:
                st.caption(
                    "Le renfort garde le sens de la position ("
                    + _p["side"] + "). Les TP/SL posés ici ne couvrent QUE la "
                    "quantité ajoutée — les ordres déjà en place sur les tranches "
                    "précédentes ne sont pas touchés (comportement natif HL)."
                )
                _notional_add = st.number_input(
                    "Montant à ajouter (USDC de notional)",
                    min_value=10.0, value=100.0, step=10.0, key="add_usd_" + _sym,
                )
                _ca, _cb = st.columns(2)
                _tp_add = _ca.number_input(
                    "TP sur cette tranche (%)", 0.0, 100.0, 5.0, 0.5, key="add_tp_" + _sym
                )
                _sl_add = _cb.number_input(
                    "SL sur cette tranche (%)", 0.0, 50.0, 2.5, 0.5, key="add_sl_" + _sym
                )

                if st.button("➕ Renforcer " + _sym, key="btn_add_" + _sym):
                    try:
                        _cli  = get_hl_client()
                        _vrai = _cli.get_position(_sym)
                        if _vrai is None:
                            st.error(
                                "Plus aucune position " + _sym + " sur HL — "
                                "utilise 'Forcer entrée' pour en ouvrir une nouvelle."
                            )
                        else:
                            _short = _vrai["is_short"]
                            _res = (_cli.short(_sym, float(_notional_add)) if _short
                                    else _cli.buy(_sym, float(_notional_add)))
                            if not (_res and _res.get("ok")):
                                st.error("Échec du renfort : " + str(_res))
                            else:
                                _fill = _res.get("fill_price") or _cli.get_price(_sym)
                                st.success(
                                    "Renfort exécuté sur " + _sym + " @ " + format(float(_fill), ".4f")
                                )
                                _qte_add = round(float(_notional_add) / float(_fill), 5)

                                _tp_prix = None
                                _sl_prix = None
                                if _tp_add > 0:
                                    _tp_prix = (_fill * (1 - _tp_add / 100) if _short
                                                else _fill * (1 + _tp_add / 100))
                                if _sl_add > 0:
                                    _sl_prix = (_fill * (1 + _sl_add / 100) if _short
                                                else _fill * (1 - _sl_add / 100))

                                if _tp_prix or _sl_prix:
                                    _tpsl = _cli.set_tp_sl(
                                        asset=_sym, size=_qte_add, is_short=_short,
                                        tp_price=_tp_prix, sl_price=_sl_prix,
                                    )
                                    _sl_pose = _tpsl.get("sl_ok", False) if _sl_prix else True
                                    _tp_pose = _tpsl.get("tp_ok", False) if _tp_prix else True
                                    if _sl_pose and _tp_pose:
                                        st.success("TP/SL natifs posés sur la tranche ajoutée.")
                                    elif not _sl_pose:
                                        st.error(
                                            "⚠️ SL NON POSÉ sur la tranche ajoutée — "
                                            "cette quantité est SANS protection. "
                                            "Interviens manuellement sur Hyperliquid."
                                        )
                                    else:
                                        st.warning("TP non posé (SL OK) sur la tranche ajoutée.")
                                else:
                                    st.warning("Aucun TP/SL demandé : tranche ajoutée sans protection.")

                                _resync_json_depuis_hl(_sym)
                                st.rerun()
                    except Exception as _e:
                        st.error("Erreur : " + str(_e))

    st.divider()

st.subheader("4️⃣ Monitoring")

state = get_state()

with st.expander("🔍 Debug — bot_state.json", expanded=False):
    st.caption(f"Chemin fichier : `{_bs_module.STATE_FILE}`")
    st.json(state)

stat_col, pnl_col = st.columns(2)

with stat_col:
    mode_labels = {"local": "🖥️ Local", "testnet": "🧪 Testnet", "mainnet": "💰 Mainnet"}
    mode_label  = mode_labels.get(state.get("mode", "local"), "")
    if state.get("status") == "running":
        st.success(f"🟢 Bot ACTIF — {mode_label}")
    else:
        st.info("⚪ Bot INACTIF")
    last = state.get("last_check")
    if last:
        st.caption(f"Dernier check : {str(last)[:19]}")
    price = state.get("last_price")
    if price:
        st.metric("Dernier prix", f"{float(price):.4f}")

with pnl_col:
    if "mainnet" in _selected_json.lower():
        try:
            bal       = get_hl_client().get_balance()
            bal_label = "USDC"
            # PnL session calculé depuis HL (source de vérité)
            fills_pnl = get_hl_client()._post_info({"type": "userFills", "user": get_hl_client().address})
            pnl = sum(float(f.get("closedPnl", 0)) - float(f.get("fee", 0)) for f in fills_pnl)
            # Nombre de trades fermés : compté depuis HL (source de vérité), pas
            # depuis state["trades"] qui ignore tout ce qui est fait hors de l'app.
            nb_trades_aff = len({f.get("oid") for f in fills_pnl if "Close" in f.get("dir", "")})
            src_trades    = "sur HL"
        except Exception:
            bal           = state.get("balance", 0)
            bal_label     = "$"
            pnl           = state.get("pnl_session", 0.0)
            nb_trades_aff = len(state.get("trades", []))
            src_trades    = "local (HL injoignable)"
    else:
        bal           = state.get("balance", 0)
        bal_label     = "$"
        pnl           = state.get("pnl_session", 0.0)
        nb_trades_aff = len(state.get("trades", []))
        src_trades    = "local"
    color = "#22C55E" if pnl >= 0 else "#EF4444"
    st.markdown(
        f"**PnL Session**  \n"
        f"<span style='font-size:28px;color:{color};font-weight:bold'>{float(pnl):+.2f}</span>  \n"
        f"Capital : **{float(bal):.2f} {bal_label}**",
        unsafe_allow_html=True,
    )
    st.caption(str(nb_trades_aff) + " trade(s) fermé(s) — " + src_trades)

# ---------------------------------------------------------------------------
# Historique des trades — depuis HL directement
# ---------------------------------------------------------------------------
st.subheader("📋 Historique des trades")
if "mainnet" in _selected_json.lower():
    try:
        client_historique = get_hl_client()
        fills_hl          = client_historique._post_info({"type": "userFills", "user": client_historique.address})

        trades_reconstruits = []
        entrees_en_attente  = {}   # coin → liste de fills d'ouverture
        closes_par_oid      = {}   # oid → liste de fills de fermeture (HL peut splitter)

        # 1. Regrouper les closes par oid (même ordre peut être splitté en N fills)
        for f in fills_hl:
            if "Close" in f.get("dir", ""):
                oid = f["oid"]
                if oid not in closes_par_oid:
                    closes_par_oid[oid] = []
                closes_par_oid[oid].append(f)

        # 2. Construire les closes fusionnés (un seul fill agrégé par oid)
        closes_fusionnes = []
        for oid, close_fills in closes_par_oid.items():
            f0 = close_fills[0]
            sz_total       = sum(float(f["sz"]) for f in close_fills)
            closed_pnl_tot = sum(float(f.get("closedPnl", 0)) for f in close_fills)
            frais_tot      = sum(float(f.get("fee", 0)) for f in close_fills)
            closes_fusionnes.append({
                "coin":       f0["coin"],
                "dir":        f0["dir"],
                "px":         f0["px"],
                "sz":         str(sz_total),
                "time":       f0["time"],
                "fee":        str(frais_tot),
                "closedPnl":  str(closed_pnl_tot),
                "oid":        oid,
            })

        # 3. Reconstruire les trades en appariant opens et closes fusionnés
        tous_fills = [f for f in fills_hl if "Open" in f.get("dir", "")] + closes_fusionnes
        for f in sorted(tous_fills, key=lambda x: x["time"]):
            coin           = f["coin"]
            direction_fill = f.get("dir", "")
            prix_fill      = float(f["px"])
            date_fill      = pd.to_datetime(f["time"], unit="ms")
            frais_fill     = float(f.get("fee", 0))

            if "Open" in direction_fill:
                if coin not in entrees_en_attente:
                    entrees_en_attente[coin] = []
                entrees_en_attente[coin].append(f)

            elif "Close" in direction_fill and coin in entrees_en_attente:
                opens        = entrees_en_attente.pop(coin)
                est_long     = "Long" in direction_fill
                ntl_total    = sum(float(o.get("ntl", 0)) or (float(o["px"]) * float(o["sz"])) for o in opens)
                frais_opens  = sum(float(o.get("fee", 0)) for o in opens)
                prix_entree  = sum(float(o["px"]) * float(o["sz"]) for o in opens) / sum(float(o["sz"]) for o in opens)
                pnl_usd      = float(f.get("closedPnl", 0)) - frais_fill - frais_opens
                pnl_pct      = (pnl_usd / ntl_total * 100) if ntl_total else 0
                trades_reconstruits.append({
                    "Date":      date_fill.strftime("%Y-%m-%d %H:%M"),
                    "Actif":     coin,
                    "Direction": "LONG" if est_long else "SHORT",
                    "Entrée":    round(prix_entree, 2),
                    "Sortie":    prix_fill,
                    "Taille":    float(f["sz"]),
                    "PnL $":     round(pnl_usd, 2),
                    "PnL %":     round(pnl_pct, 2),
                    "Raison":    direction_fill,
                })

        if trades_reconstruits:
            df_trades = pd.DataFrame(reversed(trades_reconstruits))
            def colorier_pnl(val):
                try:
                    return f"color: {'#22C55E' if float(val) >= 0 else '#EF4444'}; font-weight: bold"
                except:
                    return ""
            st.dataframe(
                df_trades.style.map(colorier_pnl, subset=["PnL $", "PnL %"]),
                width='stretch'
            )
            pnl_total   = sum(t["PnL $"] for t in trades_reconstruits)
            nb_gagnants = sum(1 for t in trades_reconstruits if t["PnL $"] > 0)
            winrate     = nb_gagnants / len(trades_reconstruits) * 100
            col_nb, col_winrate, col_pnl = st.columns(3)
            col_nb.metric("Trades fermés", len(trades_reconstruits))
            col_winrate.metric("Win rate", f"{winrate:.0f}%")
            col_pnl.metric("PnL total net (HL)", f"{pnl_total:+.2f} USDC")
        else:
            st.info("Aucun trade fermé sur ce compte HL")
    except Exception as e:
        st.error(f"❌ Erreur chargement historique HL : {e}")
        trades = state.get("trades", [])
        if trades:
            st.dataframe(pd.DataFrame(trades), width='stretch')
else:
    trades = state.get("trades", [])
    if trades:
        df_t = pd.DataFrame(trades)
        def color_pnl(val):
            try:
                return f"color: {'#22C55E' if float(val) >= 0 else '#EF4444'}"
            except:
                return ""
        cols_color = [c for c in ["pnl_usd", "pnl_pct"] if c in df_t.columns]
        st.dataframe(df_t.style.map(color_pnl, subset=cols_color) if cols_color else df_t, width='stretch')
    else:
        st.info("Aucun trade enregistré")

# Log du bot
log_lines = state.get("log", [])
if log_lines:
    with st.expander("📋 Log du bot", expanded=True):
        for line in reversed(log_lines[-30:]):
            st.caption(line)
