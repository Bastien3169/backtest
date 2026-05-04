"""
indicator_bloc.py
Composant Streamlit réutilisable pour le bloc indicateurs achat/vente.
Importé par app.py et 2_🤖_Scanner.py.
"""

import streamlit as st

MM_LABELS = [1, 10, 20, 50, 100, 200]


def render_indicator_bloc(side: str, key_prefix: str) -> dict:
    """
    Affiche le bloc indicateurs pour un côté (achat ou vente).

    side       : "buy" ou "sell"
    key_prefix : préfixe unique pour les clés Streamlit (ex: "buy_0", "sell_0")

    Retourne un dict de configuration de l'indicateur.
    """
    use_rsi        = False
    rsi_period     = 14
    rsi_threshold  = 30.0 if side == "buy" else 70.0
    mm_selected    = []
    mm_cross_a     = None
    mm_cross_b     = None
    btc_cross_period = None
    use_macd       = False
    use_bollinger  = False
    bollinger_band = None

    col_a, col_b = st.columns(2)

    # ── Colonne gauche : RSI + MM ─────────────────────────────────────────
    with col_a:
        st.markdown("**📉 RSI**")
        use_rsi = st.checkbox("Activer", key=f"{key_prefix}_rsi")
        if use_rsi:
            c1, c2 = st.columns(2)
            with c1:
                rsi_period = st.number_input("Période", 2, 50, 14, key=f"{key_prefix}_rsi_p")
            with c2:
                label = "Achat si <" if side == "buy" else "Vente si >"
                rsi_threshold = st.number_input(
                    label, 1.0, 99.0,
                    30.0 if side == "buy" else 70.0,
                    key=f"{key_prefix}_rsi_th",
                )
        st.write("")

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
                unsafe_allow_html=True,
            )
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                use_filter = st.checkbox(
                    "Filtre signal", value=True,
                    key=f"{key_prefix}_mm_{p}_filter",
                    help="Décoché = affiché sur le graphe uniquement",
                )
            with mc2:
                cond = st.radio(
                    "Position",
                    ["above", "below"],
                    format_func=lambda x: "Au-dessus ↑" if x == "above" else "En-dessous ↓",
                    key=f"{key_prefix}_mm_{p}_cond",
                    horizontal=True,
                )
            with mc3:
                slope = st.multiselect(
                    "Pente",
                    ["up", "down", "flat"],
                    default=["up", "down", "flat"],
                    format_func=lambda x: {"up": "↗", "down": "↘", "flat": "→"}[x],
                    key=f"{key_prefix}_mm_{p}_slope",
                )
            mm_configs[p] = {
                "condition":     cond,
                "slope":         slope if slope else ["up", "down", "flat"],
                "use_as_filter": use_filter,
            }

    # ── Colonne droite : Alignement + Cross MM + BTC + MACD + Bollinger ──
    with col_b:
        # Alignement MM
        mm_align_periods = []
        st.markdown("**📐 Alignement MM**")
        use_align = st.checkbox(
            "MM alignées haussières" if side == "buy" else "MM alignées baissières",
            key=f"{key_prefix}_align",
        )
        if use_align:
            align_opts = st.multiselect(
                "MM à aligner",
                MM_LABELS,
                default=[10, 20, 50],
                key=f"{key_prefix}_align_periods",
            )
            mm_align_periods = sorted(align_opts)
            if side == "buy":
                if len(mm_align_periods) >= 2:
                    order = " > ".join([f"MM{p}" for p in mm_align_periods])
                    st.caption(f"✅ Prix > {order} ET toutes montent ↗")
            else:
                if len(mm_align_periods) >= 2:
                    order = " < ".join([f"MM{p}" for p in mm_align_periods])
                    st.caption(f"✅ Prix < {order} ET toutes descendent ↘")
        st.write("")

        st.markdown("**🔀 Croisement MM**")
        label_cross = "Golden cross" if side == "buy" else "Death cross"
        use_cross = st.checkbox(label_cross, key=f"{key_prefix}_cross")
        if use_cross:
            c1, c2 = st.columns(2)
            with c1:
                mm_cross_a = st.selectbox("Courte (A)", MM_LABELS, index=2, key=f"{key_prefix}_cross_a")
            with c2:
                mm_cross_b = st.selectbox("Longue (B)", MM_LABELS, index=4, key=f"{key_prefix}_cross_b")
            if side == "buy":
                st.caption("MM courte passe **au-dessus** de MM longue")
            else:
                st.caption("MM courte passe **en-dessous** de MM longue")
        st.write("")

        st.markdown("**₿ Croisement vs BTC**")
        use_btc = st.checkbox("Activer", key=f"{key_prefix}_btc")
        if use_btc:
            btc_cross_period = st.selectbox("Période MM", MM_LABELS, index=3, key=f"{key_prefix}_btc_p")
            lbl = (
                f"MM{btc_cross_period} actif > MM{btc_cross_period} BTC"
                if side == "buy"
                else f"MM{btc_cross_period} actif < MM{btc_cross_period} BTC"
            )
            st.caption(lbl)
        st.write("")

        st.markdown("**〰️ MACD**")
        use_macd = st.checkbox(
            "Haussier" if side == "buy" else "Baissier",
            key=f"{key_prefix}_macd",
        )
        st.write("")

        st.markdown("**📊 Bollinger**")
        use_bollinger = st.checkbox("Activer", key=f"{key_prefix}_boll")
        if use_bollinger:
            bollinger_band = st.radio(
                "Bande",
                ["haute", "basse"],
                format_func=lambda x: "Haute 🔴" if x == "haute" else "Basse 🟢",
                key=f"{key_prefix}_boll_band",
                horizontal=True,
            )

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
    }
