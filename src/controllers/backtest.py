"""
backtest.py
Moteur de backtest : signaux achat + vente + simulation des trades.
"""

import pandas as pd
import numpy as np
from src.controllers.indicators import apply_all_indicators, MM_PERIODS


# ---------------------------------------------------------------------------
# Génération des signaux — logique ET entre indicateurs cochés
# ---------------------------------------------------------------------------

def _build_signal(df: pd.DataFrame, cfg: dict, side: str) -> pd.Series:
    """
    Retourne une Series booléenne.

    Logique : ET entre tous les indicateurs cochés.
    Si aucun indicateur coché → False partout (pas de signal).
    """
    conditions = []   # liste de Series bool, combinées en ET

    # ── RSI ──────────────────────────────────────────────────────────────
    if cfg.get("use_rsi") and "rsi" in df.columns:
        threshold = cfg.get("rsi_threshold", 30 if side == "buy" else 70)
        if side == "buy":
            conditions.append(df["rsi"] < threshold)
        else:
            conditions.append(df["rsi"] > threshold)

    # ── MM : prix au-dessus / en dessous ─────────────────────────────────
    mm_period    = cfg.get("mm_period")
    mm_condition = cfg.get("mm_condition")
    if mm_period and mm_condition:
        col = f"mm_{mm_period}"
        if col in df.columns:
            if mm_condition == "above":
                conditions.append(df["close"] > df[col])
            else:
                conditions.append(df["close"] < df[col])

    # ── Croisement MM A / MM B ────────────────────────────────────────────
    cross_a = cfg.get("mm_cross_a")
    cross_b = cfg.get("mm_cross_b")
    if cross_a and cross_b:
        col_a, col_b = f"mm_{cross_a}", f"mm_{cross_b}"
        if col_a in df.columns and col_b in df.columns:
            prev_a = df[col_a].shift(1)
            prev_b = df[col_b].shift(1)
            if side == "buy":
                conditions.append((prev_a <= prev_b) & (df[col_a] > df[col_b]))
            else:
                conditions.append((prev_a >= prev_b) & (df[col_a] < df[col_b]))

    # ── MACD ─────────────────────────────────────────────────────────────
    if cfg.get("use_macd") and "macd" in df.columns and "macd_signal" in df.columns:
        prev_macd = df["macd"].shift(1)
        prev_sig  = df["macd_signal"].shift(1)
        if side == "buy":
            conditions.append((prev_macd <= prev_sig) & (df["macd"] > df["macd_signal"]))
        else:
            conditions.append((prev_macd >= prev_sig) & (df["macd"] < df["macd_signal"]))

    # ── Bollinger ─────────────────────────────────────────────────────────
    bollinger_band = cfg.get("bollinger_band")
    if cfg.get("use_bollinger") and bollinger_band and "bb_upper" in df.columns:
        if bollinger_band == "haute":
            conditions.append(df["close"] >= df["bb_upper"])
        else:
            conditions.append(df["close"] <= df["bb_lower"])

    # ── Croisement actif vs MM BTC ────────────────────────────────────────
    btc_period = cfg.get("btc_cross_period")
    if btc_period:
        col_btc   = f"btc_mm_{btc_period}"
        col_asset = f"mm_{btc_period}"
        if col_btc in df.columns and col_asset in df.columns:
            prev_asset = df[col_asset].shift(1)
            prev_btc   = df[col_btc].shift(1)
            if side == "buy":
                conditions.append((prev_asset <= prev_btc) & (df[col_asset] > df[col_btc]))
            else:
                conditions.append((prev_asset >= prev_btc) & (df[col_asset] < df[col_btc]))

    # ── Combinaison ET entre toutes les conditions ────────────────────────
    if not conditions:
        return pd.Series(False, index=df.index)

    combined = conditions[0]
    for c in conditions[1:]:
        combined = combined & c

    return combined.fillna(False)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_backtest_single(
    df: pd.DataFrame,
    strategy: dict,
    capital: float,
    frais_pct: float,
    duree: int,
    date_range: tuple | None = None,
) -> dict:
    if len(df) < 2:
        return _empty_result()

    ind_achat = strategy.get("ind_achat", {})
    ind_vente = strategy.get("ind_vente", {})

    # btc_mm : on évite le `or` sur une Series pandas (provoque ValueError)
    # On prend explicitement la première non-None
    btc_mm_achat = ind_achat.get("btc_mm")
    btc_mm_vente = ind_vente.get("btc_mm")
    btc_mm = btc_mm_achat if btc_mm_achat is not None else btc_mm_vente

    ind_merged = {
        "use_rsi":       bool(ind_achat.get("use_rsi")) or bool(ind_vente.get("use_rsi")),
        "rsi_period":    ind_achat.get("rsi_period") or ind_vente.get("rsi_period") or 14,
        "use_macd":      bool(ind_achat.get("use_macd")) or bool(ind_vente.get("use_macd")),
        "use_bollinger": bool(ind_achat.get("use_bollinger")) or bool(ind_vente.get("use_bollinger")),
        "btc_mm":        btc_mm,
    }

    # Calcul indicateurs sur le DF COMPLET
    df_full  = apply_all_indicators(df, ind_merged)

    # Slice : par plage de dates OU par nombre de bougies
    if date_range is not None:
        date_debut, date_fin = date_range
        mask = (df_full.index.date >= date_debut) & (df_full.index.date <= date_fin)
        df_slice = df_full.loc[mask].copy()
        if df_slice.empty:
            return _empty_result()
    else:
        df_slice = df_full.iloc[-duree:].copy() if len(df_full) >= duree else df_full.copy()

    sig_buy  = _build_signal(df_slice, ind_achat, side="buy")
    sig_sell = _build_signal(df_slice, ind_vente, side="sell")

    tp_pct = strategy.get("tp_pct")
    sl_pct = strategy.get("sl_pct")

    cash        = capital
    position    = 0.0
    entry_price = None
    trades      = []
    equity      = []

    for i, (ts, row) in enumerate(df_slice.iterrows()):
        price = row["close"]
        equity.append({"timestamp": ts, "equity": cash + position * price})

        # ── ACHAT : seulement si pas déjà en position ──────────────────
        if position == 0 and cash > 0 and sig_buy.iloc[i]:
            qty  = (cash * (1 - frais_pct / 100)) / price
            cost = qty * price * (1 + frais_pct / 100)
            if cost <= cash:
                cash       -= cost
                position    = qty
                entry_price = price
                trades.append({"timestamp": ts, "type": "buy", "price": price,
                               "capital": cash + position * price})

        # ── VENTE : seulement si on détient une position ────────────────
        elif position > 0 and entry_price is not None:
            gain_pct    = (price - entry_price) / entry_price * 100
            should_sell = False
            sell_reason = ""

            if tp_pct and gain_pct >= tp_pct:
                should_sell = True
                sell_reason = f"TP +{gain_pct:.1f}%"
            if sl_pct and gain_pct <= -sl_pct:
                should_sell = True
                sell_reason = f"SL {gain_pct:.1f}%"
            if sig_sell.iloc[i]:
                should_sell = True
                sell_reason = sell_reason or f"signal ({gain_pct:.1f}%)"

            if should_sell:
                proceeds = position * price * (1 - frais_pct / 100)
                cash    += proceeds
                trades.append({"timestamp": ts, "type": "sell", "price": price,
                               "capital": cash, "reason": sell_reason,
                               "gain_pct": round(gain_pct, 2)})
                position    = 0
                entry_price = None

    # Clôture finale (hold)
    final_price   = df_slice.iloc[-1]["close"]
    final_capital = cash + position * final_price
    equity_series = pd.Series(
        [e["equity"] for e in equity],
        index=[e["timestamp"] for e in equity],
    )

    plus_value = final_capital - capital
    rendement  = (plus_value / capital) * 100 if capital > 0 else 0

    sells     = [t for t in trades if t["type"] == "sell"]
    nb_trades = len(sells)
    wins      = [t for t in sells if t.get("gain_pct", 0) > 0]
    win_rate  = (len(wins) / nb_trades * 100) if nb_trades > 0 else 0.0

    buys_ts  = [t["timestamp"] for t in trades if t["type"] == "buy"]
    sells_ts = [t["timestamp"] for t in trades if t["type"] == "sell"]
    durations = [(s - b).total_seconds() / 3600 for b, s in zip(buys_ts, sells_ts)]
    avg_hold  = round(sum(durations) / len(durations), 1) if durations else 0.0

    # Buy & Hold de référence
    first_price   = df_slice.iloc[0]["close"]
    bnh_rendement = (final_price - first_price) / first_price * 100 if first_price else 0

    return {
        "plus_value_eur": round(plus_value, 2),
        "rendement_pct":  round(rendement, 4),
        "bnh_rendement":  round(bnh_rendement, 4),
        "drawdown_max":   round(_compute_max_drawdown(equity_series), 4),
        "final_capital":  round(final_capital, 2),
        "nb_trades":      nb_trades,
        "win_rate":       round(win_rate, 1),
        "avg_hold_h":     avg_hold,
        "trades":         trades,
        "equity_curve":   equity_series,
        "df_slice":       df_slice,
    }


def _compute_max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    rolling_max = equity.cummax()
    drawdown    = (equity - rolling_max) / rolling_max * 100
    return abs(drawdown.min())


def _empty_result() -> dict:
    return {
        "plus_value_eur": 0.0,
        "rendement_pct":  0.0,
        "bnh_rendement":  0.0,
        "drawdown_max":   0.0,
        "final_capital":  0.0,
        "nb_trades":      0,
        "win_rate":       0.0,
        "avg_hold_h":     0.0,
        "trades":         [],
        "equity_curve":   pd.Series(dtype=float),
        "df_slice":       pd.DataFrame(),
    }


def run_strategy(
    df: pd.DataFrame,
    strategy: dict,
    capital: float,
    frais_pct: float,
    durees: list[int],
    date_range: tuple | None = None,
) -> dict:
    results = {}
    for d in durees:
        results[d] = run_backtest_single(
            df=df, strategy=strategy,
            capital=capital, frais_pct=frais_pct,
            duree=d, date_range=date_range,
        )
    return results
