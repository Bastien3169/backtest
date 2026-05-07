"""
pages/4_📈_BotLive.py
Monitoring unifié des 3 modes de trading.
Configure la stratégie + démarre/arrête le bot depuis Streamlit.
Le bot tourne dans un terminal séparé (python bot_local.py / testnet / mainnet).
"""

import sys, os, time
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

import streamlit as st
import pandas as pd
from datetime import datetime

from src.utils.bot_state import get_state, save_state, reset
from src.utils.binance_client import BinanceClient, BINANCE_SYMBOLS
from src.utils.data_loader import get_all_assets
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Bot Live", page_icon="📈", layout="wide")
st.title("📈 Bot Trading — Monitoring")

# ---------------------------------------------------------------------------
# SÉLECTEUR DE BOT — en tout premier pour que get_state/save_state
# utilisent le bon fichier JSON dès le début
# ---------------------------------------------------------------------------
import glob as _glob
import src.utils.bot_state as _bs_module

_data_dir   = os.getenv("DATA_DIR", os.path.abspath("."))
_json_files = sorted(_glob.glob(os.path.join(_data_dir, "bot_state*.json")))
_json_labels = [os.path.basename(f) for f in _json_files] or ["bot_state_local_long.json"]

_selected_json = st.selectbox("📂 Bot à configurer / monitorer", _json_labels, index=0)
_bs_module.STATE_FILE = os.path.join(_data_dir, _selected_json)

# ---------------------------------------------------------------------------
# 1️⃣ Mode de trading
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Mode de trading")

mode = st.radio(
    "Mode",
    ["🖥️ Local (simulation)", "🧪 Testnet Binance (faux argent)", "💰 Mainnet Binance (vrai argent)"],
    horizontal=True,
)
is_local   = "Local"   in mode
is_testnet = "Testnet" in mode
is_mainnet = "Mainnet" in mode

if is_local:
    st.info("**Mode Local** — Données yfinance, aucune API, simulation pure dans le JSON. Lance `python bot_local.py`")
elif is_testnet:
    st.info("**Mode Testnet** — Binance testnet, clé gratuite, faux argent. Lance `python bot_testnet.py`")
else:
    st.error("**⚠️ Mode Mainnet — VRAI ARGENT.** Lance `python bot_mainnet.py` dans un terminal.")

# Connexion Binance si nécessaire
if not is_local:
    with st.expander("🔑 Connexion Binance", expanded=False):
        api_key = os.getenv("BINANCE_TESTNET_API_KEY" if is_testnet else "BINANCE_API_KEY")
        secret  = os.getenv("BINANCE_TESTNET_SECRET_KEY" if is_testnet else "BINANCE_API_SECRET")
        if api_key:
            st.success("✅ Clés chargées depuis `.env`")
        else:
            st.warning("Clés manquantes dans `.env`")
            if is_testnet:
                st.markdown("""
1. Aller sur [testnet.binance.vision](https://testnet.binance.vision)
2. Connexion GitHub → Generate HMAC_SHA256 Key
3. Ajouter dans `.env` :
```
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_SECRET_KEY=...
```
Tu reçois automatiquement du BTC et ETH fictifs.
""")
        if st.button("🔌 Tester la connexion"):
            try:
                client = BinanceClient(testnet=is_testnet)
                res    = client.test_connection()
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

cfg1, cfg2, cfg3 = st.columns(3)
with cfg1:
    # Même liste que app.py — cryptos + indices depuis coins.py
    _all_assets    = get_all_assets()
    _asset_labels  = [f"{c['symbol']} — {c['name']}" for c in _all_assets]
    _asset_map     = {f"{c['symbol']} — {c['name']}": c["id"] for c in _all_assets}

    asset_label = st.selectbox("Actif", _asset_labels, index=0)
    asset_id    = _asset_map[asset_label]   # ticker yfinance (ex: BTC-USD) ou Binance (BTCUSDT)

    # En mode local : on utilise le ticker yfinance directement
    # En mode testnet/mainnet : on convertit en symbole Binance
    if is_local:
        symbol = asset_id   # BTC-USD, ETH-USD, ^GSPC, etc.
    else:
        # Convertir BTC-USD → BTCUSDT pour Binance (les indices ne sont pas dispo sur Binance)
        if asset_id.startswith("^"):
            st.warning(f"⚠️ {asset_label} est un indice — non disponible sur Binance. Choisir une crypto.")
            symbol = "BTCUSDT"
        else:
            symbol = asset_id.replace("-USD", "USDT").replace("-USDT", "USDT")

    timeframe = st.selectbox("Timeframe",
                             ["1m", "5m", "15m", "1h", "4h", "1d", "1w"] if not is_local
                             else ["1m", "5m", "15m", "heure", "4h", "jour", "semaine"],
                             index=3)

with cfg2:
    if is_local:
        capital  = st.number_input("Capital fictif ($)", 100.0, 100000.0, 1000.0, 100.0)
        size_pct = st.slider("% du capital par trade", 1, 100, 100)
    else:
        size_pct = st.slider("% du solde USDT par trade", 1, 20 if is_mainnet else 100, 10 if is_mainnet else 95)
        capital  = 0.0
    direction = st.radio("Direction", ["🟢 Long", "🔴 Short"], horizontal=True, key="bot_dir")
    is_short  = direction == "🔴 Short"

with cfg3:
    tp_pct = st.number_input("Take Profit (%)", 0.0, 100.0, 5.0, 0.5)
    sl_pct = st.number_input("Stop Loss (%)", 0.0, 50.0, 2.5, 0.5)
    tp_pct = tp_pct if tp_pct > 0 else None
    sl_pct = sl_pct if sl_pct > 0 else None

    st.markdown("**⏱️ Timing du check**")
    timing_mode = st.radio(
        "Mode",
        ["Intervalle (minutes)", "Heure fixe UTC"],
        horizontal=True,
        key="bot_timing_mode",
    )
    check_time_utc = None
    interval_min   = None
    if timing_mode == "Heure fixe UTC":
        check_time_utc = st.text_input(
            "Heure UTC (HH:MM)",
            value="00:01",
            help="Le bot se déclenche chaque jour à cette heure UTC. "
                 "France = UTC+1 en hiver, UTC+2 en été. "
                 "00:01 UTC = 01:01 en hiver / 02:01 en été en France.",
        )
        st.caption("🇫🇷 00:01 UTC = 01h01 hiver / 02h01 été (heure française)")
    else:
        interval_min = st.number_input(
            "Intervalle (minutes)", 1, 1440, 15, 1,
            help="Le bot vérifie toutes les X minutes",
        )

st.divider()

# ── Bloc indicateurs — même présentation que app.py ──────────────────────
with st.container(border=True):
    label_entry = "🟢 Indicateurs d'achat" if not is_short else "🔴 Indicateurs d'entrée short"
    st.markdown(f"#### {label_entry}")
    ind_entry = render_indicator_bloc("buy" if not is_short else "sell", "bot_entry")

st.write("")

with st.container(border=True):
    label_exit = "🔴 Indicateurs de vente" if not is_short else "🟢 Indicateurs de sortie short"
    st.markdown(f"#### {label_exit}")
    st.caption("Vente déclenchée si **TP/SL atteint OU indicateur de sortie actif** — laisser vide = hold")
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
            "check_time_utc": check_time_utc,   # heure UTC fixe ex: "00:01"
            "interval_min":   interval_min,      # intervalle en minutes
            "ind_entry":      ind_entry,
            "ind_exit":       ind_exit,
        }
        save_state(new_state)

        bot_cmd = {
            "local":   "python bot_local.py",
            "testnet": "python bot_testnet.py",
            "mainnet": "python bot_mainnet.py",
        }[new_state["mode"]]

        st.success(f"✅ Config sauvegardée — Lance maintenant : `{bot_cmd}`")
        st.rerun()

with c2:
    if st.button("⏹️ Arrêter", disabled=state.get("status") != "running"):
        s = get_state()
        s["status"] = "stopped"
        save_state(s)
        st.rerun()

with c3:
    if st.button("🔄 Rafraîchir"):
        st.rerun()

with c4:
    if st.button("🗑️ Reset session"):
        reset()
        st.rerun()

# Commande à lancer
if state.get("status") == "running":
    mode_key = state.get("mode", "local")
    bot_cmd  = f"python bot_{mode_key}.py"
    st.info(f"🖥️ Le bot doit tourner dans un terminal : `{bot_cmd}`")

st.divider()

# ---------------------------------------------------------------------------
# 4️⃣ Monitoring temps réel
# ---------------------------------------------------------------------------
st.subheader("4️⃣ Monitoring")

state = get_state()

# Debug — voir le chemin du fichier et son contenu brut
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
        if not pos.get("is_short"):
            pnl_pct = (float(cur_price) - entry) / entry * 100
        else:
            pnl_pct = (entry - float(cur_price)) / entry * 100
        color = "#22C55E" if pnl_pct >= 0 else "#EF4444"
        st.markdown(
            f"**{pos['symbol']}** — {pos['side']}  \n"
            f"Entrée : `{entry:.4f}` | Actuel : `{float(cur_price):.4f}`  \n"
            f"PnL : <span style='color:{color};font-weight:bold'>{pnl_pct:+.2f}%</span>",
            unsafe_allow_html=True,
        )
    else:
        st.info("Aucune position ouverte")

with pnl_col:
    pnl    = state.get("pnl_session", 0.0)
    color  = "#22C55E" if pnl >= 0 else "#EF4444"
    bal    = state.get("balance", 0)
    st.markdown(
        f"**PnL Session**  \n"
        f"<span style='font-size:28px;color:{color};font-weight:bold'>{float(pnl):+.2f}</span>  \n"
        f"Capital : **{float(bal):.2f} $**",
        unsafe_allow_html=True,
    )
    nb = len(state.get("trades", []))
    st.caption(f"{nb} trade(s) fermé(s)")

# Historique trades
trades = state.get("trades", [])
if trades:
    st.subheader("📋 Historique des trades")
    df_t = pd.DataFrame(trades)
    def color_pnl(val):
        try:
            return f"color: {'#22C55E' if float(val) >= 0 else '#EF4444'}"
        except:
            return ""
    cols_color = [c for c in ["pnl_usd", "pnl_pct"] if c in df_t.columns]
    if cols_color:
        st.dataframe(df_t.style.map(color_pnl, subset=cols_color), use_container_width=True)
    else:
        st.dataframe(df_t, use_container_width=True)

# Log
log_lines = state.get("log", [])
if log_lines:
    with st.expander("📋 Log du bot", expanded=True):
        for line in reversed(log_lines[-30:]):
            st.caption(line)

# Auto-refresh si actif
if state.get("status") == "running":
    st.caption("🔄 Rafraîchissement dans 30s")
    time.sleep(30)
    st.rerun()
