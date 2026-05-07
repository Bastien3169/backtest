"""
indicator_bloc.py
Composant Streamlit réutilisable pour le bloc indicateurs achat/vente.
Layout compact : indicateurs simples en grille, MM en bas.
"""

import streamlit as st

MM_LABELS = [1, 10, 20, 50, 100, 200]


def render_indicator_bloc(side: str, key_prefix: str) -> dict:
    use_rsi          = False
    rsi_period       = 14
    rsi_threshold    = 30.0 if side == "buy" else 70.0
    mm_selected      = []
    mm_cross_a       = None
    mm_cross_b       = None
    btc_cross_period = None
    mm_align_periods = []
    use_macd         = False
    use_bollinger    = False
    bollinger_band   = None

    # ── Ligne 1 : RSI · Alignement MM · Croisement MM ────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**📉 RSI**")
        use_rsi = st.checkbox("Activer", key=f"{key_prefix}_rsi")
        if use_rsi:
            rsi_period = st.number_input(
                "Période", 2, 50, 14, key=f"{key_prefix}_rsi_p")
            label = "Achat si <" if side == "buy" else "Vente si >"
            rsi_threshold = st.number_input(
                label, 1.0, 99.0,
                30.0 if side == "buy" else 70.0,
                key=f"{key_prefix}_rsi_th")

    with col2:
        st.markdown("**📐 Alignement MM**")
        use_align = st.checkbox(
            "Haussier ↗" if side == "buy" else "Baissier ↘",
            key=f"{key_prefix}_align")
        if use_align:
            align_opts = st.multiselect(
                "MM à aligner", MM_LABELS, default=[10, 20, 50],
                key=f"{key_prefix}_align_periods")
            mm_align_periods = sorted(align_opts)
            if len(mm_align_periods) >= 2:
                order = " > ".join([f"MM{p}" for p in mm_align_periods]) if side == "buy" \
                    else " < ".join([f"MM{p}" for p in mm_align_periods])
                st.caption(f"Prix {order}")

    with col3:
        st.markdown("**🔀 Croisement MM**")
        use_cross = st.checkbox(
            "Golden cross" if side == "buy" else "Death cross",
            key=f"{key_prefix}_cross")
        if use_cross:
            mm_cross_a = st.selectbox(
                "Courte (A)", MM_LABELS, index=2, key=f"{key_prefix}_cross_a")
            mm_cross_b = st.selectbox(
                "Longue (B)", MM_LABELS, index=4, key=f"{key_prefix}_cross_b")

    st.write("")

    # ── Ligne 2 : Croisement BTC · MACD · Bollinger ──────────────────────
    col4, col5, col6 = st.columns(3)

    with col4:
        st.markdown("**₿ Croisement vs BTC**")
        use_btc = st.checkbox("Activer", key=f"{key_prefix}_btc")
        if use_btc:
            btc_cross_period = st.selectbox(
                "Période MM", MM_LABELS, index=3, key=f"{key_prefix}_btc_p")
            arrow = ">" if side == "buy" else "<"
            st.caption(f"MM{btc_cross_period} actif {arrow} MM{btc_cross_period} BTC")

    with col5:
        st.markdown("**〰️ MACD**")
        use_macd = st.checkbox(
            "Haussier" if side == "buy" else "Baissier",
            key=f"{key_prefix}_macd")
        if use_macd:
            st.caption("Croisement MACD / Signal")

    with col6:
        st.markdown("**📊 Bollinger**")
        use_bollinger = st.checkbox("Activer", key=f"{key_prefix}_boll")
        if use_bollinger:
            bollinger_band = st.radio(
                "Bande",
                ["haute", "basse"],
                format_func=lambda x: "Haute 🔴" if x == "haute" else "Basse 🟢",
                key=f"{key_prefix}_boll_band",
                horizontal=True)
            boll_mode = st.radio(
                "Mode signal",
                ["etat", "franchissement"],
                format_func=lambda x: "📍 État (close sous/dessus la bande)" if x == "etat" else "↗ Franchissement (1 bougie uniquement)",
                key=f"{key_prefix}_boll_mode",
                horizontal=True)
            if boll_mode == "etat":
                boll_confirm = st.checkbox(
                    "1ère bougie seulement",
                    key=f"{key_prefix}_boll_confirm",
                    help="Achat uniquement si T-1 était dans la bande — évite les runs prolongés",
                )
                if boll_confirm:
                    st.caption("✅ T-1 dans la bande ET T en sort → achat open[T+1]")
                else:
                    st.caption("Close[T] < bande → achat open[T+1]")
            else:
                boll_confirm = False
                st.caption("Signal uniquement sur la bougie qui franchit la bande")
        else:
            bollinger_band = None
            boll_mode      = "etat"
            boll_confirm   = False

    st.write("")

    # ── Ligne 3 : Moyennes Mobiles (prend plus de place) ─────────────────
    st.markdown("**📈 Moyennes Mobiles**")
    mm_cols_ui = st.columns(6)
    for j, p in enumerate(MM_LABELS):
        with mm_cols_ui[j]:
            if st.checkbox(f"{p}", key=f"{key_prefix}_mm_{p}"):
                mm_selected.append(p)

    mm_configs = {}
    for p in mm_selected:
        st.markdown(
            f"<span style='color:#aaa;font-size:12px'>── MM{p}</span>",
            unsafe_allow_html=True)
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            use_filter = st.checkbox(
                "Filtre signal", value=True,
                key=f"{key_prefix}_mm_{p}_filter",
                help="Décoché = affiché sur le graphe uniquement")
        with mc2:
            cond = st.radio(
                "Position", ["above", "below"],
                format_func=lambda x: "Au-dessus ↑" if x == "above" else "En-dessous ↓",
                key=f"{key_prefix}_mm_{p}_cond", horizontal=True)
        with mc3:
            slope = st.multiselect(
                "Pente",
                ["up", "down", "flat"],
                default=["up", "down", "flat"],
                format_func=lambda x: {"up": "↗", "down": "↘", "flat": "→"}[x],
                key=f"{key_prefix}_mm_{p}_slope")
        mm_configs[p] = {
            "condition":     cond,
            "slope":         slope if slope else ["up", "down", "flat"],
            "use_as_filter": use_filter,
        }

    return {
        "use_rsi":          use_rsi,
        "rsi_period":       rsi_period,
        "rsi_threshold":    rsi_threshold,
        "mm_periods":       mm_selected,
        "mm_configs":       mm_configs if mm_selected else {},
        "mm_period":        mm_selected[0] if mm_selected else None,
        "mm_condition":     mm_configs[mm_selected[0]]["condition"] if mm_selected else None,
        "mm_slope":         mm_configs[mm_selected[0]]["slope"] if mm_selected else ["up", "down", "flat"],
        "mm_align_periods": mm_align_periods,
        "mm_cross_a":       mm_cross_a,
        "mm_cross_b":       mm_cross_b,
        "btc_cross_period": btc_cross_period,
        "use_macd":         use_macd,
        "use_bollinger":    use_bollinger,
        "bollinger_band":   bollinger_band,
        "bollinger_mode":   boll_mode if use_bollinger else "etat",
        "bollinger_confirm": boll_confirm if use_bollinger else False,
    }
