"""
pages/3_📡_PaperTrading.py
Paper trading en live sur Hyperliquid (testnet ou mainnet).

Flux :
1. Connexion via .env (clé privée + adresse)
2. Configuration de la stratégie (mêmes indicateurs que app.py)
3. Boucle de monitoring : évalue le signal sur la dernière bougie
4. Passage d'ordre si signal → affichage position + PnL
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

from src.utils.hyperliquid_client import (
    HL_ASSETS, get_credentials, test_connection,
    get_account_state, get_current_price,
    place_order, close_position, get_recent_trades,
)
from src.utils.data_loader import fetch_ohlcv
from src.controllers.indicators import apply_all_indicators
from src.controllers.backtest import _build_signal
from src.views.indicator_bloc import render_indicator_bloc

st.set_page_config(page_title="Paper Trading", page_icon="📡", layout="wide")
st.title("📡 Paper Trading — Hyperliquid")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
for key, val in {
    "pt_active":    False,     # stratégie active ou non
    "pt_position":  None,      # {"asset", "side", "size", "entry_price", "ts"}
    "pt_trades":    [],        # historique des trades de la session
    "pt_log":       [],        # log des événements
    "pt_last_check": None,     # dernière vérification du signal
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ---------------------------------------------------------------------------
# 1️⃣ CONNEXION
# ---------------------------------------------------------------------------
st.subheader("1️⃣ Connexion Hyperliquid")

pk, addr = get_credentials()

with st.expander("🔑 Credentials (.env)", expanded=(not pk)):
    if pk and addr:
        st.success(f"✅ Credentials chargés depuis `.env`  \nWallet : `{addr[:6]}...{addr[-4:]}`")
    else:
        st.warning("Aucun credential trouvé dans `.env`")
        st.code("""# Créer un fichier .env à la racine du projet :
HL_PRIVATE_KEY=ta_cle_privee_64_chars
HL_WALLET_ADDRESS=0xTonAdresse""")
        st.markdown("""
**Comment obtenir ta clé privée MetaMask :**
1. MetaMask → 3 points → Détails du compte
2. Exporter la clé privée
3. Coller dans `.env` sans le `0x`

⚠️ Ne partage jamais cette clé — elle donne accès total à ton wallet.
""")

use_testnet = st.toggle("Utiliser le testnet", value=True,
                        help="Testnet = fonds fictifs. Mainnet = vrais fonds.")

if st.button("🔌 Tester la connexion"):
    with st.spinner("Connexion..."):
        res = test_connection(use_testnet)
    if res["ok"]:
        st.success(res["message"])
    else:
        st.error(f"Connexion échouée : {res['message']}")

st.divider()

# ---------------------------------------------------------------------------
# 2️⃣ CONFIGURATION
# ---------------------------------------------------------------------------
st.subheader("2️⃣ Configuration de la stratégie")

cfg1, cfg2, cfg3 = st.columns(3)
with cfg1:
    asset     = st.selectbox("Actif", HL_ASSETS, index=0)
    timeframe = st.selectbox("Timeframe", ["heure", "4h", "jour"], index=0)
    # Mapping timeframe → interval yfinance
    tf_map = {"heure": "1h", "4h": "4h", "jour": "1d"}

with cfg2:
    size_usd  = st.number_input("Taille position (USD)", 10.0, 10000.0, 100.0, 10.0)
    leverage  = st.number_input("Levier", 1, 20, 1)
    direction = st.radio("Direction", ["🟢 Long", "🔴 Short"], horizontal=True)
    is_short  = direction == "🔴 Short"

with cfg3:
    refresh_min = st.number_input("Rafraîchissement (minutes)", 1, 60, 5)
    tp_pct = st.number_input("Take Profit (%)", 0.0, 100.0, 5.0, 0.5)
    sl_pct = st.number_input("Stop Loss (%)", 0.0, 50.0, 2.5, 0.5)
    tp_pct = tp_pct if tp_pct > 0 else None
    sl_pct = sl_pct if sl_pct > 0 else None

st.write("")
st.markdown("#### 🟢 Indicateurs d'entrée")
ind_entry = render_indicator_bloc("buy" if not is_short else "sell", "pt_entry")

st.markdown("#### 🔴 Indicateurs de sortie")
ind_exit = render_indicator_bloc("sell" if not is_short else "buy", "pt_exit")

strategy = {
    "ind_achat":  ind_entry,
    "ind_vente":  ind_exit,
    "is_short":   is_short,
    "tp_pct":     tp_pct,
    "sl_pct":     sl_pct,
}

st.divider()

# ---------------------------------------------------------------------------
# 3️⃣ CONTRÔLES
# ---------------------------------------------------------------------------
st.subheader("3️⃣ Contrôles")

col_start, col_stop, col_force = st.columns(3)

with col_start:
    if st.button("▶️ Démarrer la stratégie", type="primary",
                 disabled=st.session_state.pt_active or not pk):
        st.session_state.pt_active    = True
        st.session_state.pt_log.append(
            f"{datetime.now().strftime('%H:%M:%S')} — Stratégie démarrée sur {asset}")
        st.rerun()

with col_stop:
    if st.button("⏹️ Arrêter", disabled=not st.session_state.pt_active):
        st.session_state.pt_active = False
        st.session_state.pt_log.append(
            f"{datetime.now().strftime('%H:%M:%S')} — Stratégie arrêtée")
        st.rerun()

with col_force:
    if st.button("🔴 Forcer la clôture", disabled=not st.session_state.pt_position):
        pos = st.session_state.pt_position
        if pos and pk:
            price = get_current_price(pos["asset"], use_testnet)
            if price:
                res = close_position(
                    asset=pos["asset"], size=pos["size"],
                    is_long=not pos["is_short"], price=price,
                    private_key=pk, wallet_address=addr,
                    use_testnet=use_testnet,
                )
                if res["ok"]:
                    pnl = (price - pos["entry_price"]) * pos["size"] * (1 if not pos["is_short"] else -1)
                    st.session_state.pt_trades.append({
                        "ts":          datetime.now().strftime("%H:%M:%S"),
                        "asset":       pos["asset"],
                        "side":        "LONG" if not pos["is_short"] else "SHORT",
                        "entry":       pos["entry_price"],
                        "exit":        price,
                        "pnl_usd":     round(pnl, 2),
                        "raison":      "Clôture forcée",
                    })
                    st.session_state.pt_position = None
                    st.session_state.pt_log.append(
                        f"{datetime.now().strftime('%H:%M:%S')} — Position fermée manuellement")
                    st.rerun()

if not pk:
    st.warning("⚠️ Configure le fichier `.env` pour activer les ordres réels.")

st.divider()

# ---------------------------------------------------------------------------
# 4️⃣ MONITORING
# ---------------------------------------------------------------------------
st.subheader("4️⃣ Monitoring")

# Statut
status_col, pos_col = st.columns(2)
with status_col:
    if st.session_state.pt_active:
        st.success("🟢 Stratégie **ACTIVE**")
    else:
        st.info("⚪ Stratégie **INACTIVE**")

with pos_col:
    pos = st.session_state.pt_position
    if pos:
        price_now = get_current_price(pos["asset"], use_testnet) or pos["entry_price"]
        if not pos["is_short"]:
            pnl_pct = (price_now - pos["entry_price"]) / pos["entry_price"] * 100
        else:
            pnl_pct = (pos["entry_price"] - price_now) / pos["entry_price"] * 100
        color = "#22C55E" if pnl_pct >= 0 else "#EF4444"
        st.markdown(
            f"**Position ouverte** : {pos['asset']} {'LONG 🟢' if not pos['is_short'] else 'SHORT 🔴'}  \n"
            f"Entrée : **{pos['entry_price']:.2f}$** | Actuel : **{price_now:.2f}$**  \n"
            f"PnL : <span style='color:{color};font-weight:bold'>{pnl_pct:+.2f}%</span>",
            unsafe_allow_html=True,
        )
    else:
        st.info("Aucune position ouverte")

# Compte Hyperliquid
if pk and addr:
    with st.expander("💰 État du compte", expanded=False):
        account = get_account_state(addr, use_testnet)
        if account["ok"] and account["data"]:
            data = account["data"]
            margin = data.get("marginSummary", {})
            st.metric("Equity", f"{float(margin.get('accountValue', 0)):.2f} $")
            st.metric("Marge utilisée", f"{float(margin.get('totalMarginUsed', 0)):.2f} $")
            positions = data.get("assetPositions", [])
            if positions:
                st.write("**Positions ouvertes sur HL :**")
                for p in positions:
                    pos_data = p.get("position", {})
                    if float(pos_data.get("szi", 0)) != 0:
                        st.write(f"- {pos_data.get('coin')} : {pos_data.get('szi')} "
                                 f"@ {pos_data.get('entryPx')} | PnL: {pos_data.get('unrealizedPnl')}")

# Log des événements
with st.expander("📋 Log", expanded=True):
    for log in reversed(st.session_state.pt_log[-20:]):
        st.caption(log)

# Historique des trades de la session
if st.session_state.pt_trades:
    st.subheader("📊 Trades de la session")
    df_trades = pd.DataFrame(st.session_state.pt_trades)
    def color_pnl(val):
        try:
            return f"color: {'#22C55E' if float(val) >= 0 else '#EF4444'}"
        except:
            return ""
    st.dataframe(
        df_trades.style.map(color_pnl, subset=["pnl_usd"]),
        use_container_width=True,
    )
    total_pnl = sum(t["pnl_usd"] for t in st.session_state.pt_trades)
    color = "#22C55E" if total_pnl >= 0 else "#EF4444"
    st.markdown(
        f"**PnL total session : <span style='color:{color}'>{total_pnl:+.2f}$</span>**",
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# 5️⃣ BOUCLE DE STRATÉGIE (évaluée à chaque rerun)
# ---------------------------------------------------------------------------
if st.session_state.pt_active and pk:
    now = datetime.now()
    last = st.session_state.pt_last_check
    interval_sec = refresh_min * 60

    # Vérifier si c'est le moment de checker le signal
    should_check = (last is None or (now - last).total_seconds() >= interval_sec)

    if should_check:
        st.session_state.pt_last_check = now
        ticker = f"{asset}-USD"

        with st.spinner(f"Vérification du signal {asset}..."):
            try:
                # Récupérer les données
                df = fetch_ohlcv(ticker, "heure" if timeframe != "4h" else "heure")

                # Pour le 4h : resample
                if timeframe == "4h":
                    df = df.resample("4h").agg({
                        "open": "first", "high": "max",
                        "low": "min", "close": "last"
                    }).dropna()

                # Calculer les indicateurs
                ind_merged = {
                    "use_rsi":       ind_entry.get("use_rsi") or ind_exit.get("use_rsi"),
                    "rsi_period":    ind_entry.get("rsi_period", 14),
                    "use_macd":      ind_entry.get("use_macd") or ind_exit.get("use_macd"),
                    "use_bollinger": ind_entry.get("use_bollinger") or ind_exit.get("use_bollinger"),
                    "btc_mm":        None,
                    "mm_align_periods": ind_entry.get("mm_align_periods", []),
                }
                df_ind = apply_all_indicators(df, ind_merged)

                # Évaluer le signal sur la DERNIÈRE bougie complète (T-1)
                side_entry = "buy" if not is_short else "sell"
                side_exit  = "sell" if not is_short else "buy"
                sig_entry_s = _build_signal(df_ind, ind_entry, side=side_entry)
                sig_exit_s  = _build_signal(df_ind, ind_exit,  side=side_exit)

                # Prendre l'avant-dernière bougie (dernière complète)
                entry_signal = bool(sig_entry_s.iloc[-2]) if len(sig_entry_s) >= 2 else False
                exit_signal  = bool(sig_exit_s.iloc[-2])  if len(sig_exit_s)  >= 2 else False
                current_price = float(df_ind["close"].iloc[-1])

                log_ts = now.strftime("%H:%M:%S")
                st.session_state.pt_log.append(
                    f"{log_ts} — {asset} @ {current_price:.2f}$ | "
                    f"Signal entrée: {'✅' if entry_signal else '❌'} | "
                    f"Signal sortie: {'✅' if exit_signal else '❌'}"
                )

                pos = st.session_state.pt_position

                # ── Gestion des positions ─────────────────────────────────
                if pos is None and entry_signal:
                    # Passer l'ordre d'entrée
                    res = place_order(
                        asset=asset, is_buy=not is_short,
                        size_usd=size_usd, price=current_price,
                        private_key=pk, wallet_address=addr,
                        use_testnet=use_testnet, leverage=leverage,
                    )
                    if res["ok"]:
                        st.session_state.pt_position = {
                            "asset":       asset,
                            "is_short":    is_short,
                            "size":        size_usd / current_price,
                            "entry_price": current_price,
                            "ts":          log_ts,
                        }
                        st.session_state.pt_log.append(
                            f"{log_ts} — 🟢 {'SHORT' if is_short else 'LONG'} ouvert "
                            f"{asset} @ {current_price:.2f}$"
                        )
                    else:
                        st.session_state.pt_log.append(
                            f"{log_ts} — ❌ Ordre échoué : {res['message']}"
                        )

                elif pos is not None:
                    # Vérifier TP/SL
                    if not is_short:
                        pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                    else:
                        pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100

                    should_close = False
                    close_reason = ""

                    if sl_pct and pnl_pct <= -sl_pct:
                        should_close = True
                        close_reason = f"SL {pnl_pct:.1f}%"
                    elif tp_pct and pnl_pct >= tp_pct:
                        should_close = True
                        close_reason = f"TP +{pnl_pct:.1f}%"
                    elif exit_signal:
                        should_close = True
                        close_reason = f"Signal sortie ({pnl_pct:.1f}%)"

                    if should_close:
                        res = close_position(
                            asset=pos["asset"], size=pos["size"],
                            is_long=not pos["is_short"], price=current_price,
                            private_key=pk, wallet_address=addr,
                            use_testnet=use_testnet,
                        )
                        if res["ok"]:
                            st.session_state.pt_trades.append({
                                "ts":      log_ts,
                                "asset":   pos["asset"],
                                "side":    "LONG" if not pos["is_short"] else "SHORT",
                                "entry":   pos["entry_price"],
                                "exit":    current_price,
                                "pnl_usd": round(pnl_pct / 100 * size_usd, 2),
                                "raison":  close_reason,
                            })
                            st.session_state.pt_position = None
                            st.session_state.pt_log.append(
                                f"{log_ts} — 🔴 Position fermée : {close_reason}"
                            )

            except Exception as e:
                st.session_state.pt_log.append(
                    f"{now.strftime('%H:%M:%S')} — ⚠️ Erreur : {e}"
                )

    # Prochain rafraîchissement automatique
    remaining = interval_sec - (datetime.now() - st.session_state.pt_last_check).total_seconds()
    remaining = max(0, remaining)
    st.caption(f"⏱ Prochain check dans {int(remaining // 60)}m {int(remaining % 60)}s")
    time.sleep(min(remaining, 30))   # recheck max toutes les 30s
    st.rerun()
