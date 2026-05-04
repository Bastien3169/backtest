"""
indicators.py
Calcul des indicateurs techniques sur un DataFrame OHLCV.
"""

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta    = df["close"].diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df       = df.copy()
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ---------------------------------------------------------------------------
# Moyennes Mobiles
# ---------------------------------------------------------------------------

MM_PERIODS = [1, 10, 20, 50, 100, 200]


def add_moving_averages(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
    df = df.copy()
    if periods is None:
        periods = MM_PERIODS
    for p in periods:
        df[f"mm_{p}"] = df["close"].rolling(window=p).mean()
    return df


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    df = df.copy()
    ema_fast        = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow        = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"]      = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    df["bb_middle"] = df["close"].rolling(window=period).mean()
    rolling_std     = df["close"].rolling(window=period).std()
    df["bb_upper"]  = df["bb_middle"] + std_dev * rolling_std
    df["bb_lower"]  = df["bb_middle"] - std_dev * rolling_std
    return df


# ---------------------------------------------------------------------------
# MM BTC
# ---------------------------------------------------------------------------

def add_btc_mm(df: pd.DataFrame, btc_mm: pd.Series) -> pd.DataFrame:
    df = df.copy()
    df = df.join(btc_mm, how="left")
    df[btc_mm.name] = df[btc_mm.name].ffill()
    return df


# ---------------------------------------------------------------------------
# Pente des MM
# ---------------------------------------------------------------------------

def add_mm_slope(df: pd.DataFrame, period: int, flat_threshold: float = 0.0005) -> pd.DataFrame:
    """
    Ajoute 'mm_{period}_slope' : "up" | "down" | "flat"
    """
    df        = df.copy()
    col       = f"mm_{period}"
    if col not in df.columns:
        df = add_moving_averages(df, [period])
    pct_change = df[col].pct_change()
    slope_col  = f"mm_{period}_slope"
    df[slope_col] = "flat"
    df.loc[pct_change >  flat_threshold, slope_col] = "up"
    df.loc[pct_change < -flat_threshold, slope_col] = "down"
    return df


# ---------------------------------------------------------------------------
# Alignement des MM
# ---------------------------------------------------------------------------

def add_mm_alignment(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """
    Ajoute 'mm_aligned_bull' et 'mm_aligned_bear'.

    Bull : prix > MM courte > ... > MM longue ET toutes montent
    Bear : prix < MM courte < ... < MM longue ET toutes descendent

    periods : ex [10, 20, 50]
    """
    df = df.copy()
    if len(periods) < 2:
        df["mm_aligned_bull"] = False
        df["mm_aligned_bear"] = False
        return df

    periods_sorted = sorted(periods)
    cols           = [f"mm_{p}" for p in periods_sorted]

    for col in cols:
        if col not in df.columns:
            df = add_moving_averages(df, [int(col.split("_")[1])])

    # Haussier
    bull = df["close"] > df[cols[0]]
    for i in range(len(cols) - 1):
        bull = bull & (df[cols[i]] > df[cols[i + 1]])
    for col in cols:
        bull = bull & (df[col] > df[col].shift(1))

    # Baissier
    bear = df["close"] < df[cols[0]]
    for i in range(len(cols) - 1):
        bear = bear & (df[cols[i]] < df[cols[i + 1]])
    for col in cols:
        bear = bear & (df[col] < df[col].shift(1))

    df["mm_aligned_bull"] = bull.fillna(False)
    df["mm_aligned_bear"] = bear.fillna(False)
    return df


# ---------------------------------------------------------------------------
# Application groupée
# ---------------------------------------------------------------------------

def apply_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Applique tous les indicateurs nécessaires selon la config.

    config keys :
        use_rsi         : bool
        rsi_period      : int
        use_macd        : bool
        use_bollinger   : bool
        btc_mm          : pd.Series | None
        mm_align_periods: list[int]
    """
    df = df.copy()
    df = add_moving_averages(df, MM_PERIODS)

    for p in MM_PERIODS:
        df = add_mm_slope(df, p)

    mm_align_periods = config.get("mm_align_periods", [])
    if mm_align_periods:
        df = add_mm_alignment(df, mm_align_periods)

    if config.get("use_rsi"):
        df = add_rsi(df, period=config.get("rsi_period", 14))

    if config.get("use_macd"):
        df = add_macd(df)

    if config.get("use_bollinger"):
        df = add_bollinger(df)

    if config.get("btc_mm") is not None:
        df = add_btc_mm(df, config["btc_mm"])

    return df
