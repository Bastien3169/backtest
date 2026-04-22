"""
backtest.py
Moteur de backtest : génération des signaux + simulation des trades.
"""

import pandas as pd
import numpy as np
from src.controllers.indicators import apply_all_indicators


# ---------------------------------------------------------------------------
# Génération des signaux d'entrée
# ---------------------------------------------------------------------------

def generate_signals(df: pd.DataFrame, strategy: dict) -> pd.Series:
    """
    Retourne une Series booléenne indiquant les barres où le signal d'achat est actif.

    strategy keys :
        indicateurs    : dict (voir apply_all_indicators)
        mm_condition   : "above" | "below" | None
        mm_period      : int (MM sur laquelle comparer le prix)
        mm_cross_a     : int | None   (croisement MM A x MM B)
        mm_cross_b     : int | None
        rsi_threshold  : float | None (achat si RSI < seuil)
        macd_signal    : bool (achat si MACD croise à la hausse sa ligne signal)
        bollinger_band : "haute" | "basse" | None
    """
    df = apply_all_indicators(df, strategy.get("indicateurs", {}))
    n = len(df)
    signal = pd.Series(True, index=df.index)  # commence tout actif, on filtre

    # --- RSI ---
    if strategy.get("indicateurs", {}).get("use_rsi"):
        threshold = strategy.get("rsi_threshold", 30)
        if "rsi" in df.columns:
            signal &= df["rsi"] < threshold

    # --- MM : prix au-dessus / en dessous ---
    mm_period = strategy.get("mm_period")
    mm_condition = strategy.get("mm_condition")
    if mm_period and mm_condition:
        col = f"mm_{mm_period}"
        if col in df.columns:
            if mm_condition == "above":
                signal &= df["close"] > df[col]
            elif mm_condition == "below":
                signal &= df["close"] < df[col]

    # --- Croisement MM A / MM B ---
    cross_a = strategy.get("mm_cross_a")
    cross_b = strategy.get("mm_cross_b")
    if cross_a and cross_b:
        col_a = f"mm_{cross_a}"
        col_b = f"mm_{cross_b}"
        if col_a in df.columns and col_b in df.columns:
            # Signal : MM courte passe au-dessus de MM longue (golden cross)
            prev_a = df[col_a].shift(1)
            prev_b = df[col_b].shift(1)
            cross_signal = (prev_a <= prev_b) & (df[col_a] > df[col_b])
            signal &= cross_signal

    # --- MACD ---
    if strategy.get("indicateurs", {}).get("use_macd"):
        if "macd" in df.columns and "macd_signal" in df.columns:
            prev_macd = df["macd"].shift(1)
            prev_sig = df["macd_signal"].shift(1)
            macd_cross = (prev_macd <= prev_sig) & (df["macd"] > df["macd_signal"])
            signal &= macd_cross

    # --- Bollinger ---
    bollinger_band = strategy.get("bollinger_band")
    if strategy.get("indicateurs", {}).get("use_bollinger") and bollinger_band:
        if "bb_upper" in df.columns:
            if bollinger_band == "haute":
                signal &= df["close"] >= df["bb_upper"]
            elif bollinger_band == "basse":
                signal &= df["close"] <= df["bb_lower"]

    # --- Croisement actif vs MM BTC ---
    btc_cross_period = strategy.get("btc_cross_period")
    if btc_cross_period:
        col_btc = f"btc_mm_{btc_cross_period}"
        if col_btc in df.columns:
            # Signal : MM de l'actif (période btc_cross_period) croise au-dessus de la MM BTC
            col_asset = f"mm_{btc_cross_period}"
            if col_asset in df.columns:
                prev_asset = df[col_asset].shift(1)
                prev_btc   = df[col_btc].shift(1)
                btc_cross  = (prev_asset <= prev_btc) & (df[col_asset] > df[col_btc])
                signal &= btc_cross

    return signal.fillna(False)


# ---------------------------------------------------------------------------
# Simulation d'une stratégie sur une durée donnée
# ---------------------------------------------------------------------------

def run_backtest_single(
    df: pd.DataFrame,
    strategy: dict,
    capital: float,
    frais_pct: float,
    duree: int,
    tp_pct: float | None = None,
    sl_pct: float | None = None,
    activer_vente: bool = False,
) -> dict:
    """
    Simule la stratégie sur 'duree' périodes.

    Returns dict :
        plus_value_eur : float
        rendement_pct  : float
        drawdown_max   : float
        trades         : list[dict]  (date, type, price, capital)
        equity_curve   : pd.Series
    """
    if len(df) < duree + 1:
        return _empty_result()

    df_slice = df.iloc[-duree:].copy()
    signals = generate_signals(df_slice, strategy)

    cash = capital
    position = 0.0        # quantité de crypto détenue
    entry_price = None
    trades = []
    equity = []

    for i, (ts, row) in enumerate(df_slice.iterrows()):
        price = row["close"]
        current_equity = cash + position * price
        equity.append({"timestamp": ts, "equity": current_equity})

        # Signal d'achat
        if signals.iloc[i] and position == 0 and cash > 0:
            qty = (cash * (1 - frais_pct / 100)) / price
            cost = qty * price * (1 + frais_pct / 100)
            if cost <= cash:
                cash -= cost
                position = qty
                entry_price = price
                trades.append({"timestamp": ts, "type": "buy", "price": price, "capital": cash + position * price})

        # Gestion de la vente (TP / SL)
        elif position > 0 and activer_vente and entry_price is not None:
            gain_pct = (price - entry_price) / entry_price * 100
            should_sell = False
            if tp_pct and gain_pct >= tp_pct:
                should_sell = True
            if sl_pct and gain_pct <= -sl_pct:
                should_sell = True

            if should_sell:
                proceeds = position * price * (1 - frais_pct / 100)
                cash += proceeds
                trades.append({"timestamp": ts, "type": "sell", "price": price, "capital": cash})
                position = 0
                entry_price = None

    # Clôture finale (mode hold ou fin de backtest)
    final_price = df_slice.iloc[-1]["close"]
    final_capital = cash + position * final_price

    equity_series = pd.Series(
        [e["equity"] for e in equity],
        index=[e["timestamp"] for e in equity],
    )

    drawdown_max = _compute_max_drawdown(equity_series)
    plus_value = final_capital - capital
    rendement = (plus_value / capital) * 100 if capital > 0 else 0

    return {
        "plus_value_eur": round(plus_value, 2),
        "rendement_pct": round(rendement, 4),
        "drawdown_max": round(drawdown_max, 4),
        "final_capital": round(final_capital, 2),
        "trades": trades,
        "equity_curve": equity_series,
    }


def _compute_max_drawdown(equity: pd.Series) -> float:
    """Calcule le drawdown maximum en % sur une equity curve."""
    if equity.empty:
        return 0.0
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100
    return abs(drawdown.min())


def _empty_result() -> dict:
    return {
        "plus_value_eur": 0.0,
        "rendement_pct": 0.0,
        "drawdown_max": 0.0,
        "final_capital": 0.0,
        "trades": [],
        "equity_curve": pd.Series(dtype=float),
    }


# ---------------------------------------------------------------------------
# Exécution multi-durées pour une stratégie
# ---------------------------------------------------------------------------

def run_strategy(
    df: pd.DataFrame,
    strategy: dict,
    capital: float,
    frais_pct: float,
    durees: list[int],
    tp_pct: float | None,
    sl_pct: float | None,
    activer_vente: bool,
) -> dict:
    """
    Lance le backtest pour toutes les durées et retourne un dict
    {duree: result_dict}.
    """
    results = {}
    for d in durees:
        results[d] = run_backtest_single(
            df=df,
            strategy=strategy,
            capital=capital,
            frais_pct=frais_pct,
            duree=d,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            activer_vente=activer_vente,
        )
    return results
