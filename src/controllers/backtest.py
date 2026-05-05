"""
backtest.py
Moteur de backtest : signaux achat + vente + simulation des trades.

Conventions de timing :
- Signal calculé sur close[T]
- Exécution à open[T+1] (via shift(1) global sur les signaux)
- TP/SL vérifiés sur high/low[T+1] intra-bougie
- Tous les shifts internes aux indicateurs ont été retirés de _build_signal
  car le shift(1) global suffit. Seuls les croisements (MACD, MM cross, Bollinger,
  BTC cross) gardent leur shift interne pour détecter l'événement de croisement —
  mais ils ne sont PAS re-shiftés globalement (voir note ci-dessous).

Note sur les croisements :
  Un croisement (prev <= cur) utilise shift(1) interne pour comparer T-1 vs T.
  Le signal est déjà "ponctuel" sur la bougie T.
  Le shift(1) global l'exécute à open[T+1]. Correct.

Note sur les états (RSI, MM au-dessus, alignement) :
  Ce sont des filtres de tendance. Le shift(1) global les décale d'une bougie.
  C'est acceptable et cohérent.
"""

import pandas as pd
import numpy as np
from src.controllers.indicators import apply_all_indicators, MM_PERIODS


# ---------------------------------------------------------------------------
# Génération des signaux
# ---------------------------------------------------------------------------

def _build_signal(df: pd.DataFrame, cfg: dict, side: str) -> pd.Series:
    """
    Construit le signal brut sur close[T].
    Le shift(1) global dans run_backtest_single décale l'exécution à open[T+1].

    Tous les indicateurs produisent leur signal sur T sans shift interne
    SAUF les croisements qui ont besoin de comparer T-1 vs T pour détecter
    l'événement de franchissement.
    """
    conditions = []

    # ── RSI — filtre d'état ───────────────────────────────────────────────
    if cfg.get("use_rsi") and "rsi" in df.columns:
        threshold = cfg.get("rsi_threshold", 30 if side == "buy" else 70)
        if side == "buy":
            conditions.append(df["rsi"] < threshold)
        else:
            conditions.append(df["rsi"] > threshold)

    # ── MM : prix au-dessus / en dessous — filtre d'état ─────────────────
    mm_configs  = cfg.get("mm_configs", {})
    all_slopes  = {"up", "down", "flat"}

    if mm_configs:
        for period, mcfg in mm_configs.items():
            if not mcfg.get("use_as_filter", True):
                continue
            col = f"mm_{period}"
            if col not in df.columns:
                continue
            cond  = mcfg.get("condition", "above")
            slope = set(mcfg.get("slope", ["up", "down", "flat"]))
            if cond == "above":
                conditions.append(df["close"] > df[col])
            else:
                conditions.append(df["close"] < df[col])
            if slope and slope != all_slopes:
                slope_col = f"mm_{period}_slope"
                if slope_col in df.columns:
                    conditions.append(df[slope_col].isin(slope))
    else:
        mm_period    = cfg.get("mm_period")
        mm_condition = cfg.get("mm_condition")
        mm_slope     = cfg.get("mm_slope", [])
        if mm_period and mm_condition:
            col = f"mm_{mm_period}"
            if col in df.columns:
                if mm_condition == "above":
                    conditions.append(df["close"] > df[col])
                else:
                    conditions.append(df["close"] < df[col])
                selected_slopes = set(mm_slope) if mm_slope else all_slopes
                if selected_slopes and selected_slopes != all_slopes:
                    slope_col = f"mm_{mm_period}_slope"
                    if slope_col in df.columns:
                        conditions.append(df[slope_col].isin(selected_slopes))

    # ── Alignement MM — filtre d'état ─────────────────────────────────────
    mm_align_periods = cfg.get("mm_align_periods", [])
    if mm_align_periods:
        col = "mm_aligned_bull" if side == "buy" else "mm_aligned_bear"
        if col in df.columns:
            conditions.append(df[col])

    # ── Croisement MM A / MM B — événement (shift interne conservé) ───────
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

    # ── MACD — événement (shift interne conservé) ─────────────────────────
    if cfg.get("use_macd") and "macd" in df.columns and "macd_signal" in df.columns:
        prev_macd = df["macd"].shift(1)
        prev_sig  = df["macd_signal"].shift(1)
        if side == "buy":
            conditions.append((prev_macd <= prev_sig) & (df["macd"] > df["macd_signal"]))
        else:
            conditions.append((prev_macd >= prev_sig) & (df["macd"] < df["macd_signal"]))

    # ── Bollinger — événement franchissement (shift interne conservé) ─────
    bollinger_band = cfg.get("bollinger_band")
    if cfg.get("use_bollinger") and bollinger_band and "bb_upper" in df.columns:
        prev_close = df["close"].shift(1)
        if bollinger_band == "haute":
            prev_upper = df["bb_upper"].shift(1)
            conditions.append((prev_close <= prev_upper) & (df["close"] > df["bb_upper"]))
        else:
            prev_lower = df["bb_lower"].shift(1)
            conditions.append((prev_close >= prev_lower) & (df["close"] < df["bb_lower"]))

    # ── Croisement actif vs MM BTC — événement (shift interne conservé) ───
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

    # ── Combinaison ET ────────────────────────────────────────────────────
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
    date_range=None,
) -> dict:
    if len(df) < 2:
        return _empty_result()

    ind_achat = strategy.get("ind_achat", {})
    ind_vente = strategy.get("ind_vente", {})

    btc_mm_achat = ind_achat.get("btc_mm")
    btc_mm_vente = ind_vente.get("btc_mm")
    btc_mm = btc_mm_achat if btc_mm_achat is not None else btc_mm_vente

    ind_merged = {
        "use_rsi":          bool(ind_achat.get("use_rsi")) or bool(ind_vente.get("use_rsi")),
        "rsi_period":       ind_achat.get("rsi_period") or ind_vente.get("rsi_period") or 14,
        "use_macd":         bool(ind_achat.get("use_macd")) or bool(ind_vente.get("use_macd")),
        "use_bollinger":    bool(ind_achat.get("use_bollinger")) or bool(ind_vente.get("use_bollinger")),
        "btc_mm":           btc_mm,
        "mm_align_periods": list(set(
            ind_achat.get("mm_align_periods", []) +
            ind_vente.get("mm_align_periods", [])
        )),
    }

    df_full = apply_all_indicators(df, ind_merged)

    if date_range is not None:
        date_debut, date_fin = date_range
        mask     = (df_full.index.date >= date_debut) & (df_full.index.date <= date_fin)
        df_slice = df_full.loc[mask].copy()
        if df_slice.empty:
            return _empty_result()
    else:
        df_slice = df_full.iloc[-duree:].copy() if len(df_full) >= duree else df_full.copy()

    # ── TIMING : signal sur close[T] → exécution à open[T+1] ─────────────
    # shift(1) décale le signal d'une bougie.
    # L'exécution se fait sur row["open"] de la bougie courante,
    # qui correspond à open[T+1] par rapport au signal.
    sig_entry = _build_signal(df_slice, ind_achat, side="buy").shift(1).fillna(False)
    sig_exit  = _build_signal(df_slice, ind_vente, side="sell").shift(1).fillna(False)

    tp_pct   = strategy.get("tp_pct")
    sl_pct   = strategy.get("sl_pct")
    is_short = strategy.get("is_short", False)

    cash        = capital
    position    = 0.0
    entry_price = None
    trades      = []
    equity      = []

    for i, (ts, row) in enumerate(df_slice.iterrows()):
        close = row["close"]
        high  = row.get("high", close)
        low   = row.get("low",  close)
        # Exécution à l'open de la bougie courante (= open[T+1] par rapport au signal)
        exec_price = row.get("open", close)

        if not is_short:
            # ── MODE LONG ──────────────────────────────────────────────────
            equity.append({"timestamp": ts, "equity": cash + position * close})

            # Entrée à l'open
            if position == 0 and cash > 0 and sig_entry.iloc[i]:
                qty  = cash / (exec_price * (1 + frais_pct / 100))
                cost = qty * exec_price * (1 + frais_pct / 100)
                if cost <= cash:
                    cash       -= cost
                    position    = qty
                    entry_price = exec_price
                    trades.append({"timestamp": ts, "type": "buy", "price": exec_price,
                                   "capital": cash + position * close})

            # TP/SL/signal de sortie
            elif position > 0 and entry_price is not None:
                tp_price = entry_price * (1 + tp_pct / 100) if tp_pct else None
                sl_price = entry_price * (1 - sl_pct / 100) if sl_pct else None

                should_exit = False
                exit_price  = close
                exit_reason = ""

                # SL prioritaire (intra-bougie via low)
                if sl_price and low <= sl_price:
                    should_exit = True
                    exit_price  = sl_price
                    exit_reason = f"SL {((sl_price - entry_price)/entry_price*100):.1f}%"
                elif tp_price and high >= tp_price:
                    should_exit = True
                    exit_price  = tp_price
                    exit_reason = f"TP +{((tp_price - entry_price)/entry_price*100):.1f}%"
                elif sig_exit.iloc[i]:
                    should_exit = True
                    exit_price  = exec_price   # sortie à l'open aussi
                    exit_reason = f"signal ({((exec_price - entry_price)/entry_price*100):.1f}%)"

                if should_exit:
                    gain_pct = (exit_price - entry_price) / entry_price * 100
                    proceeds = position * exit_price * (1 - frais_pct / 100)
                    cash    += proceeds
                    trades.append({"timestamp": ts, "type": "sell", "price": exit_price,
                                   "capital": cash, "reason": exit_reason,
                                   "gain_pct": round(gain_pct, 2)})
                    position    = 0
                    entry_price = None

        else:
            # ── MODE SHORT ─────────────────────────────────────────────────
            latent_pnl = (entry_price - close) * position if (position > 0 and entry_price) else 0
            equity.append({"timestamp": ts, "equity": cash + latent_pnl})

            if position == 0 and cash > 0 and sig_entry.iloc[i]:
                # Frais à l'entrée ET à la sortie — symétriques
                qty         = cash / (exec_price * (1 + frais_pct / 100))
                entry_cost  = qty * exec_price * frais_pct / 100
                cash       -= entry_cost
                position    = qty
                entry_price = exec_price
                trades.append({"timestamp": ts, "type": "short_entry", "price": exec_price,
                               "capital": cash})

            elif position > 0 and entry_price is not None:
                # TP/SL inversés pour short : TP sur low, SL sur high
                tp_price = entry_price * (1 - tp_pct / 100) if tp_pct else None
                sl_price = entry_price * (1 + sl_pct / 100) if sl_pct else None

                should_exit = False
                exit_price  = close
                exit_reason = ""

                if sl_price and high >= sl_price:
                    should_exit = True
                    exit_price  = sl_price
                    exit_reason = f"SL {((entry_price - sl_price)/entry_price*100):.1f}%"
                elif tp_price and low <= tp_price:
                    should_exit = True
                    exit_price  = tp_price
                    exit_reason = f"TP +{((entry_price - tp_price)/entry_price*100):.1f}%"
                elif sig_exit.iloc[i]:
                    should_exit = True
                    exit_price  = exec_price
                    exit_reason = f"signal ({((entry_price - exec_price)/entry_price*100):.1f}%)"

                if should_exit:
                    gain_pct = (entry_price - exit_price) / entry_price * 100
                    pnl      = (entry_price - exit_price) * position * (1 - frais_pct / 100)
                    cash    += pnl
                    trades.append({"timestamp": ts, "type": "short_exit", "price": exit_price,
                                   "capital": cash, "reason": exit_reason,
                                   "gain_pct": round(gain_pct, 2)})
                    position    = 0
                    entry_price = None

    # ── Clôture finale ────────────────────────────────────────────────────
    final_close = df_slice.iloc[-1]["close"]
    if not is_short:
        final_capital = cash + position * final_close
    else:
        latent_pnl    = (entry_price - final_close) * position if (position > 0 and entry_price) else 0
        final_capital = cash + latent_pnl

    equity_series = pd.Series(
        [e["equity"] for e in equity],
        index=[e["timestamp"] for e in equity],
    )

    plus_value = final_capital - capital
    rendement  = (plus_value / capital) * 100 if capital > 0 else 0

    exit_type  = "sell"        if not is_short else "short_exit"
    entry_type = "buy"         if not is_short else "short_entry"
    exits      = [t for t in trades if t["type"] == exit_type]
    nb_trades  = len(exits)
    wins       = [t for t in exits if t.get("gain_pct", 0) > 0]
    win_rate   = (len(wins) / nb_trades * 100) if nb_trades > 0 else 0.0

    entries_ts = [t["timestamp"] for t in trades if t["type"] == entry_type]
    exits_ts   = [t["timestamp"] for t in trades if t["type"] == exit_type]
    durations  = [(s - b).total_seconds() / 3600 for b, s in zip(entries_ts, exits_ts)]
    avg_hold   = round(sum(durations) / len(durations), 1) if durations else 0.0

    first_close = df_slice.iloc[0]["close"]
    if not is_short:
        bnh_rendement = (final_close - first_close) / first_close * 100 if first_close else 0
    else:
        bnh_rendement = (first_close - final_close) / first_close * 100 if first_close else 0

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
    date_range=None,
) -> dict:
    results = {}
    if date_range is None:
        ranges = [None] * len(durees)
    elif isinstance(date_range, list):
        ranges = date_range + [None] * max(0, len(durees) - len(date_range))
    else:
        ranges = [date_range] * len(durees)

    for d, dr in zip(durees, ranges):
        results[d] = run_backtest_single(
            df=df, strategy=strategy,
            capital=capital, frais_pct=frais_pct,
            duree=d, date_range=dr,
        )
    return results
