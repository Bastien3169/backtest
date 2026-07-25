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
bot_side = "short" if "short" in _selected_json.lower() else "long"

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

    timeframe = st.selectbox(
        "Timeframe",
        ["1m", "5m", "15m", "1h", "4h", "1d", "1w"] if not is_local
        else ["1m", "5m", "15m", "heure", "4h", "jour", "semaine"],
        index=3,
    )

with cfg2:
    if is_local:
        capital  = st.number_input("Capital fictif ($)", 100.0, 100000.0, 1000.0, 100.0)
        size_pct = st.number_input("% du capital par trade", 1, 100, 100, 1)
        st.caption(f"→ {capital * size_pct / 100:.2f} $ par trade")
    elif is_mainnet:
        try:
            solde_hl = get_hl_client().get_balance()
        except Exception:
            solde_hl = 0.0
        st.metric("Solde HL", f"{solde_hl:.2f} USDC")
        size_pct = st.number_input("% du solde par trade", 1, 100, 10, 1, key="size_pct_hl")
        leverage = st.number_input("Levier (x)", 1, 20, 1, 1, key="leverage_hl")
        notional = solde_hl * size_pct / 100 * leverage
        st.metric("USDC par trade", f"{solde_hl * size_pct / 100:.2f} USDC")
        st.caption(f"→ Notional : {notional:.2f} USDC (x{leverage})")
        capital  = 0.0
    else:
        size_pct = st.number_input("% du solde par trade", 1, 100, 95, 1)
        capital  = 0.0
        st.caption("Solde réel chargé depuis Binance testnet")

with cfg3:
    st.markdown("**⏱️ Timing**")
    timing_mode = st.radio(
        "Mode", ["Intervalle (min)", "Heure fixe UTC"],
        horizontal=True, key="bot_timing_mode",
    )
    check_time_utc = None
    interval_min   = None
    if timing_mode == "Heure fixe UTC":
        check_time_utc = st.text_input(
            "Heure UTC (HH:MM)", value="00:01",
            help="France = UTC+1 hiver / UTC+2 été",
        )
        st.caption("🇫🇷 00:01 UTC = 01h01 hiver / 02h01 été")
    else:
        interval_min = st.number_input(
            "Intervalle (minutes)", 1, 1440, 15, 1,
            help="Synchronisé sur les heures rondes UTC",
        )

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
    st.warning(f"⚠️ Position ouverte : {pos_ouverte.get('side')} {pos_ouverte.get('symbol')} @ {pos_ouverte.get('entry_price'):.2f}$")
    st.caption("Arrête le bot ET ferme la position sur HL")
    if st.button("🔴 Arrêter + Fermer position", type="primary"):
        try:
            client_stop  = get_hl_client()
            symbol_stop  = pos_ouverte.get("symbol", "BTC")
            qty_stop     = pos_ouverte.get("qty", 0)
            is_short_pos = pos_ouverte.get("is_short", False)
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
                st.error("⚠️ Position ouverte sur HL ! Ferme-la d'abord avec '🔴 Forcer clôture'")
            else:
                reset()
                st.rerun()
        else:
            reset()
            st.rerun()

# Bouton Forcer clôture
pos = get_state().get("position")
if pos:
    st.warning(f"⚠️ Position ouverte : {pos.get('side')} {pos.get('symbol')} @ {pos.get('entry_price'):.2f}$")
    col_close, _ = st.columns([1, 3])
    with col_close:
        st.caption("Ferme la position sur HL — le bot continue de chercher un nouveau signal")
        if st.button("🔴 Forcer clôture", type="primary"):
            if is_local:
                s          = get_state()
                last_price = s.get("last_price") or pos["entry_price"]
                pnl_pct    = (last_price - pos["entry_price"]) / pos["entry_price"] * 100
                pnl_usd    = round(pos["qty"] * last_price - pos["size_usdt"], 2)
                s["balance"]    += pos["qty"] * last_price
                s["pnl_session"] = round(s["balance"] - s.get("balance_init", 1000.0), 2)
                s["trades"].append({
                    "ts": datetime.now().isoformat(), "symbol": pos["symbol"],
                    "side": pos["side"], "entry_price": pos["entry_price"],
                    "exit_price": last_price, "qty": pos["qty"],
                    "pnl_pct": round(pnl_pct, 2), "pnl_usd": pnl_usd,
                    "raison": "Clôture forcée",
                })
                s["position"] = None
                save_state(s)
                st.success(f"Position fermée @ {last_price:.2f}$ | PnL: {pnl_usd:+.2f}$")
                st.rerun()
            elif is_mainnet:
                try:
                    client_cloture  = get_hl_client()
                    symbol_cloture  = pos.get("symbol", "BTC")
                    qty_cloture     = pos.get("qty", 0)
                    is_short_pos    = pos.get("is_short", False)
                    res = client_cloture.close_short(symbol_cloture, qty_cloture) if is_short_pos else client_cloture.sell(symbol_cloture, qty_cloture)
                    if res and res["ok"]:
                        fill    = res.get("fill_price") or pos["entry_price"]
                        pnl_pct = (fill - pos["entry_price"]) / pos["entry_price"] * 100 if not is_short_pos else (pos["entry_price"] - fill) / pos["entry_price"] * 100
                        pnl_usd = round(pos["qty"] * fill - pos.get("size_usdt", 0), 2) if not is_short_pos else round(pos.get("size_usdt", 0) - pos["qty"] * fill, 2)
                        s = get_state()
                        s["trades"].append({
                            "ts": datetime.now().isoformat(), "symbol": pos["symbol"],
                            "side": pos["side"], "entry_price": pos["entry_price"],
                            "exit_price": fill, "qty": pos["qty"],
                            "pnl_pct": round(pnl_pct, 2), "pnl_usd": pnl_usd,
                            "raison": "Clôture forcée",
                        })
                        s["position"] = None
                        save_state(s)
                        st.success(f"✅ Position fermée sur HL @ {fill:.2f}$ | PnL: {pnl_usd:+.2f}$")
                        st.rerun()
                    else:
                        st.error(f"❌ Échec clôture HL : {res}")
                except Exception as e:
                    st.error(f"❌ Erreur : {e}")
            else:
                st.info("Pour le testnet : ferme manuellement sur Binance puis clique Reset.")

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
st.subheader("4️⃣ Monitoring")

state = get_state()

with st.expander("🔍 Debug — bot_state.json", expanded=False):
    st.caption(f"Chemin fichier : `{_bs_module.STATE_FILE}`")
    st.json(state)

stat_col, pos_col, pnl_col = st.columns(3)

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

with pos_col:
    pos = state.get("position")
    if pos:
        entry     = pos["entry_price"]
        cur_price = state.get("last_price") or entry
        pnl_pct   = (float(cur_price) - entry) / entry * 100 if not pos.get("is_short") else (entry - float(cur_price)) / entry * 100
        color     = "#22C55E" if pnl_pct >= 0 else "#EF4444"
        st.markdown(
            f"**{pos['symbol']}** — {pos['side']}  \n"
            f"Entrée : `{entry:.4f}` | Actuel : `{float(cur_price):.4f}`  \n"
            f"PnL : <span style='color:{color};font-weight:bold'>{pnl_pct:+.2f}%</span>",
            unsafe_allow_html=True,
        )
    else:
        st.info("Aucune position ouverte")

with pnl_col:
    pnl   = state.get("pnl_session", 0.0)
    color = "#22C55E" if pnl >= 0 else "#EF4444"
    if "mainnet" in _selected_json.lower():
        try:
            bal       = get_hl_client().get_balance()
            bal_label = "USDC"
        except Exception:
            bal       = state.get("balance", 0)
            bal_label = "$"
    else:
        bal       = state.get("balance", 0)
        bal_label = "$"
    st.markdown(
        f"**PnL Session**  \n"
        f"<span style='font-size:28px;color:{color};font-weight:bold'>{float(pnl):+.2f}</span>  \n"
        f"Capital : **{float(bal):.2f} {bal_label}**",
        unsafe_allow_html=True,
    )
    st.caption(f"{len(state.get('trades', []))} trade(s) fermé(s)")

# ---------------------------------------------------------------------------
# Historique des trades — depuis HL directement
# ---------------------------------------------------------------------------
st.subheader("📋 Historique des trades")
if "mainnet" in _selected_json.lower():
    try:
        client_historique = get_hl_client()
        fills_hl          = client_historique._post_info({"type": "userFills", "user": client_historique.address})

        trades_reconstruits = []
        entrees_en_attente  = {}  # coin → fill d'ouverture en attente

        for f in sorted(fills_hl, key=lambda x: x["time"]):
            coin          = f["coin"]
            direction_fill = f.get("dir", "")
            prix_fill     = float(f["px"])
            date_fill     = pd.to_datetime(f["time"], unit="ms")
            frais_fill    = float(f.get("fee", 0))

            if "Open" in direction_fill:
                entrees_en_attente[coin] = f
            elif "Close" in direction_fill and coin in entrees_en_attente:
                fill_entree = entrees_en_attente.pop(coin)
                prix_entree = float(fill_entree["px"])
                est_long    = "Long" in direction_fill
                frais_entree = float(fill_entree.get("fee", 0))
                pnl_usd     = float(f.get("closedPnl", 0)) - frais_fill - frais_entree
                notional_entree = float(fill_entree.get("ntl", 0)) or (prix_entree * float(fill_entree.get("sz", 0)))
                pnl_pct     = (pnl_usd / notional_entree * 100) if notional_entree else 0
                trades_reconstruits.append({
                    "Date":      date_fill.strftime("%Y-%m-%d %H:%M"),
                    "Actif":     coin,
                    "Direction": "LONG" if est_long else "SHORT",
                    "Entrée":    prix_entree,
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
            pnl_total  = sum(t["PnL $"] for t in trades_reconstruits)
            nb_gagnants = sum(1 for t in trades_reconstruits if t["PnL $"] > 0)
            winrate     = nb_gagnants / len(trades_reconstruits) * 100
            col_nb, col_winrate, col_pnl = st.columns(3)
            col_nb.metric("Trades fermés", len(trades_reconstruits))
            col_winrate.metric("Win rate", f"{winrate:.0f}%")
            col_pnl.metric("PnL total net", f"{pnl_total:+.2f} USDC")
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
