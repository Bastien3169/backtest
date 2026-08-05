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

    mm_cross_mode  = "franchissement"
    btc_cross_mode = "franchissement"
    macd_mode      = "franchissement"

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
            mm_cross_mode = "etat" if st.radio(
                "Mode", ["↗ Franchissement", "📍 État"],
                key=f"{key_prefix}_cross_mode", horizontal=True,
                help="Franchissement : signal au moment du croisement seulement. "
                     "État : signal tant que A reste du bon côté de B.",
            ) == "📍 État" else "franchissement"
            _sens = ">" if side == "buy" else "<"
            st.caption(
                f"MM{mm_cross_a} {_sens} MM{mm_cross_b} en continu"
                if mm_cross_mode == "etat"
                else f"Au croisement MM{mm_cross_a} / MM{mm_cross_b}"
            )

    st.write("")

    # ── Ligne 2 : Croisement BTC · MACD · Bollinger ──────────────────────
    col4, col5, col6 = st.columns(3)

    with col4:
        st.markdown("**₿ Croisement vs BTC**")
        use_btc = st.checkbox("Activer", key=f"{key_prefix}_btc")
        if use_btc:
            btc_cross_period = st.selectbox(
                "Période MM", MM_LABELS, index=3, key=f"{key_prefix}_btc_p")
            btc_cross_mode = "etat" if st.radio(
                "Mode", ["↗ Franchissement", "📍 État"],
                key=f"{key_prefix}_btc_mode", horizontal=True,
                help="Franchissement : signal au croisement seulement. "
                     "État : signal tant que la condition tient.",
            ) == "📍 État" else "franchissement"
            arrow = ">" if side == "buy" else "<"
            _suffixe = "en continu" if btc_cross_mode == "etat" else "(au croisement)"
            st.caption(f"MM{btc_cross_period} actif {arrow} MM{btc_cross_period} BTC {_suffixe}")

    with col5:
        st.markdown("**〰️ MACD**")
        use_macd = st.checkbox(
            "Haussier" if side == "buy" else "Baissier",
            key=f"{key_prefix}_macd")
        if use_macd:
            macd_mode = "etat" if st.radio(
                "Mode", ["↗ Franchissement", "📍 État"],
                key=f"{key_prefix}_macd_mode", horizontal=True,
                help="Franchissement : signal au croisement MACD/Signal seulement. "
                     "État : signal tant que le MACD reste du bon côté.",
            ) == "📍 État" else "franchissement"
            _sens = "au-dessus" if side == "buy" else "en dessous"
            st.caption(
                f"MACD {_sens} de sa ligne Signal en continu"
                if macd_mode == "etat" else "Au croisement MACD / Signal"
            )

    with col6:
        st.markdown("**📊 Bollinger**")
        use_bollinger = st.checkbox("Activer", key=f"{key_prefix}_boll")
        if use_bollinger:
            # Paramètres MM et écart type
            _bcol1, _bcol2 = st.columns(2)
            with _bcol1:
                boll_period = st.number_input(
                    "Période MM", 2, 200, 20, 1,
                    key=f"{key_prefix}_boll_period",
                    help="Période de la moyenne mobile (défaut: 20)")
            with _bcol2:
                boll_std = st.number_input(
                    "Écart type", 0.5, 5.0, 2.0, 0.5,
                    key=f"{key_prefix}_boll_std",
                    help="Nombre d'écarts types (défaut: 2.0)")

            # Condition d'entrée — 4 choix indépendants
            BOLL_CONDITIONS = {
                "gt_haute":  "close > bande haute",
                "lt_haute":  "close < bande haute",
                "gt_basse":  "close > bande basse",
                "lt_basse":  "close < bande basse",
            }
            bollinger_cond = st.selectbox(
                "Condition",
                list(BOLL_CONDITIONS.keys()),
                format_func=lambda x: BOLL_CONDITIONS[x],
                key=f"{key_prefix}_boll_cond",
            )
            # bollinger_band reste pour compatibilité avec le reste du code
            bollinger_band = "haute" if "haute" in bollinger_cond else "basse"

            boll_mode = st.radio(
                "Mode signal",
                ["etat", "franchissement", "suivi"],
                format_func=lambda x: {
                    "etat": "📍 État",
                    "franchissement": "↗ Franchissement (1 bougie)",
                    "suivi": "🔄 Suivi (entrée ET sortie)",
                }[x],
                key=f"{key_prefix}_boll_mode",
                horizontal=True)

            if boll_mode == "etat":
                boll_confirm = st.checkbox(
                    "1ère bougie seulement",
                    key=f"{key_prefix}_boll_confirm",
                    help="Signal uniquement sur la 1ère bougie qui franchit — évite les runs prolongés",
                )
                if boll_confirm:
                    st.caption(f"✅ T-1 dans la bande ET T vérifie : {BOLL_CONDITIONS[bollinger_cond]}")
                else:
                    st.caption(f"Signal : {BOLL_CONDITIONS[bollinger_cond]}")
            elif boll_mode == "suivi":
                boll_confirm = False
                st.caption(f"✅ Entrée : {BOLL_CONDITIONS[bollinger_cond]}")
            else:
                boll_confirm = False
                st.caption(f"Franchissement de la condition : {BOLL_CONDITIONS[bollinger_cond]}")
        else:
            bollinger_band = None
            bollinger_cond = None
            boll_mode      = "etat"
            boll_confirm   = False
            boll_period    = 20
            boll_std       = 2.0

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
        "mm_cross_mode":    mm_cross_mode,
        "btc_cross_period": btc_cross_period,
        "btc_cross_mode":   btc_cross_mode,
        "use_macd":         use_macd,
        "macd_mode":        macd_mode,
        "use_bollinger":    use_bollinger,
        "bollinger_band":    bollinger_band,
        "bollinger_cond":    bollinger_cond if use_bollinger else None,
        "bollinger_mode":    boll_mode if use_bollinger else "etat",
        "bollinger_confirm": boll_confirm if use_bollinger else False,
        "bollinger_period":  boll_period if use_bollinger else 20,
        "bollinger_std":     boll_std if use_bollinger else 2.0,
    }
