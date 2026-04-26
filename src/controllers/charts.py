"""
charts.py
Génération des graphiques Plotly pour l'affichage Streamlit.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

COLORS = px.colors.qualitative.Plotly


# ---------------------------------------------------------------------------
# Graphique principal : prix + trades + indicateurs
# ---------------------------------------------------------------------------

def chart_price_trades(
    df: pd.DataFrame,
    all_trades: dict[str, list[dict]],
    strategies_config: list[dict] | None = None,
    title: str = "Prix & Trades",
) -> go.Figure:
    """
    Graphique principal avec sous-graphes automatiques selon les indicateurs actifs.
    - Toujours : cours du prix + points achat/vente + MM choisies
    - Si RSI actif   → sous-graphe RSI avec ligne de seuil
    - Si MACD actif  → sous-graphe MACD
    - Si Bollinger   → bandes sur le graphe prix
    """
    # Déterminer quels indicateurs sont actifs dans les stratégies
    show_rsi  = False
    show_macd = False
    rsi_buy_threshold  = 30
    rsi_sell_threshold = 70

    if strategies_config:
        for s in strategies_config:
            if s.get("ind_achat", {}).get("use_rsi") or s.get("ind_vente", {}).get("use_rsi"):
                show_rsi = True
                rsi_buy_threshold  = s.get("ind_achat", {}).get("rsi_threshold", 30)
                rsi_sell_threshold = s.get("ind_vente", {}).get("rsi_threshold", 70)
            if s.get("ind_achat", {}).get("use_macd") or s.get("ind_vente", {}).get("use_macd"):
                show_macd = True

    # Construire les sous-graphes nécessaires
    subplot_rows = 1
    row_heights  = [0.6]
    subplot_titles = [title]

    if show_rsi:
        subplot_rows += 1
        row_heights.append(0.2)
        subplot_titles.append("RSI")
    if show_macd:
        subplot_rows += 1
        row_heights.append(0.2)
        subplot_titles.append("MACD")

    fig = make_subplots(
        rows=subplot_rows, cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
        vertical_spacing=0.05,
    )

    # ── Prix ──────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df.index, y=df["close"],
        mode="lines", name="Prix",
        line=dict(color="#636EFA", width=1.5),
    ), row=1, col=1)

    # ── MM sur le graphe prix ─────────────────────────────────────────────
    mm_colors = ["#FFA15A", "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"]
    mm_plotted = set()
    if strategies_config:
        for s in strategies_config:
            for side_key in ("ind_achat", "ind_vente"):
                cfg = s.get(side_key, {})
                # Toutes les MM cochées via mm_configs
                for period, mcfg in cfg.get("mm_configs", {}).items():
                    if period not in mm_plotted:
                        col = f"mm_{period}"
                        if col in df.columns:
                            c = mm_colors[len(mm_plotted) % len(mm_colors)]
                            fig.add_trace(go.Scatter(
                                x=df.index, y=df[col],
                                mode="lines", name=f"MM{period}",
                                line=dict(color=c, width=1, dash="dot"),
                            ), row=1, col=1)
                            mm_plotted.add(period)
                # Fallback mm_period unique
                mp = cfg.get("mm_period")
                if mp and mp not in mm_plotted:
                    col = f"mm_{mp}"
                    if col in df.columns:
                        c = mm_colors[len(mm_plotted) % len(mm_colors)]
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df[col],
                            mode="lines", name=f"MM{mp}",
                            line=dict(color=c, width=1, dash="dot"),
                        ), row=1, col=1)
                        mm_plotted.add(mp)
                # MM cross A et B
                for mp2 in [cfg.get("mm_cross_a"), cfg.get("mm_cross_b")]:
                    if mp2 and mp2 not in mm_plotted:
                        col = f"mm_{mp2}"
                        if col in df.columns:
                            c = mm_colors[len(mm_plotted) % len(mm_colors)]
                            fig.add_trace(go.Scatter(
                                x=df.index, y=df[col],
                                mode="lines", name=f"MM{mp2}",
                                line=dict(color=c, width=1, dash="dot"),
                            ), row=1, col=1)
                            mm_plotted.add(mp2)
                # MM BTC
                btc_p = cfg.get("btc_cross_period")
                if btc_p:
                    col_btc = f"btc_mm_{btc_p}"
                    if col_btc in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df[col_btc],
                            mode="lines", name=f"MM{btc_p} BTC",
                            line=dict(color="#F7DC6F", width=1, dash="dash"),
                        ), row=1, col=1)

    # ── Bollinger ─────────────────────────────────────────────────────────
    if "bb_upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_upper"],
            mode="lines", name="BB haute",
            line=dict(color="rgba(200,100,100,0.5)", width=1),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_lower"],
            mode="lines", name="BB basse",
            line=dict(color="rgba(100,200,100,0.5)", width=1),
            fill="tonexty", fillcolor="rgba(150,150,150,0.05)",
        ), row=1, col=1)

    # ── Points achat / vente ──────────────────────────────────────────────
    for idx, (name, trades) in enumerate(all_trades.items()):
        color = COLORS[idx % len(COLORS)]
        buys  = [t for t in trades if t["type"] == "buy"]
        sells = [t for t in trades if t["type"] == "sell"]
        if buys:
            fig.add_trace(go.Scatter(
                x=[t["timestamp"] for t in buys],
                y=[t["price"] for t in buys],
                mode="markers", name=f"{name} — Achat",
                marker=dict(symbol="triangle-up", size=12, color="lime",
                            line=dict(color="darkgreen", width=1)),
            ), row=1, col=1)
        if sells:
            reasons = [t.get("reason", "") for t in sells]
            fig.add_trace(go.Scatter(
                x=[t["timestamp"] for t in sells],
                y=[t["price"] for t in sells],
                mode="markers", name=f"{name} — Vente",
                marker=dict(symbol="triangle-down", size=12, color="red",
                            line=dict(color="darkred", width=1)),
                text=reasons,
                hovertemplate="<b>Vente</b><br>Prix: %{y:.2f}<br>Raison: %{text}<extra></extra>",
            ), row=1, col=1)

    current_row = 2

    # ── Sous-graphe RSI ───────────────────────────────────────────────────
    if show_rsi and "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["rsi"],
            mode="lines", name="RSI",
            line=dict(color="#AB63FA", width=1.5),
        ), row=current_row, col=1)
        # Lignes de seuil
        fig.add_hline(y=rsi_buy_threshold,  line_dash="dash", line_color="lime",
                      annotation_text=f"Achat <{rsi_buy_threshold}",
                      annotation_position="bottom right", row=current_row, col=1)
        fig.add_hline(y=rsi_sell_threshold, line_dash="dash", line_color="red",
                      annotation_text=f"Vente >{rsi_sell_threshold}",
                      annotation_position="top right", row=current_row, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="gray", row=current_row, col=1)
        fig.update_yaxes(range=[0, 100], row=current_row, col=1)
        current_row += 1

    # ── Sous-graphe MACD ──────────────────────────────────────────────────
    if show_macd and "macd" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd"],
            mode="lines", name="MACD",
            line=dict(color="#00CC96", width=1.5),
        ), row=current_row, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["macd_signal"],
            mode="lines", name="Signal MACD",
            line=dict(color="#EF553B", width=1),
        ), row=current_row, col=1)
        fig.add_trace(go.Bar(
            x=df.index, y=df["macd_hist"],
            name="Histogramme",
            marker_color=df["macd_hist"].apply(lambda x: "rgba(0,200,100,0.5)" if x >= 0 else "rgba(220,50,50,0.5)"),
        ), row=current_row, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=400 + subplot_rows * 150,
        showlegend=True,
        xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Bar chart : rendement comparatif
# ---------------------------------------------------------------------------

def chart_rendement_comparison(all_results: dict, durees: list[int]) -> go.Figure:
    fig = go.Figure()
    for idx, (name, results) in enumerate(all_results.items()):
        rendements = [results.get(d, {}).get("rendement_pct", 0) for d in durees]
        fig.add_trace(go.Bar(
            name=name, x=[f"{d}j" for d in durees], y=rendements,
            marker_color=COLORS[idx % len(COLORS)],
        ))
    fig.update_layout(
        barmode="group", title="Rendement comparatif (%)",
        xaxis_title="Durée", yaxis_title="Rendement (%)",
        template="plotly_dark", height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# Equity curves
# ---------------------------------------------------------------------------

def chart_equity_curves(all_results: dict, duree: int) -> go.Figure:
    fig = go.Figure()
    for idx, (name, results) in enumerate(all_results.items()):
        ec = results.get(duree, {}).get("equity_curve", pd.Series(dtype=float))
        if not ec.empty:
            fig.add_trace(go.Scatter(
                x=ec.index, y=ec.values,
                mode="lines", name=name,
                line=dict(color=COLORS[idx % len(COLORS)], width=2),
            ))
    fig.update_layout(
        title=f"Évolution du capital — {duree} périodes",
        xaxis_title="Date", yaxis_title="Capital (€)",
        template="plotly_dark", height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# Drawdown comparé
# ---------------------------------------------------------------------------

def chart_drawdown_comparison(all_results: dict, durees: list[int]) -> go.Figure:
    fig = go.Figure()
    for idx, (name, results) in enumerate(all_results.items()):
        drawdowns = [results.get(d, {}).get("drawdown_max", 0) for d in durees]
        fig.add_trace(go.Bar(
            name=name, x=[f"{d}j" for d in durees], y=drawdowns,
            marker_color=COLORS[idx % len(COLORS)],
        ))
    fig.update_layout(
        barmode="group", title="Drawdown maximum comparé (%)",
        xaxis_title="Durée", yaxis_title="Drawdown (%)",
        template="plotly_dark", height=400,
    )
    return fig
