"""
indicators.py
Calcul des indicateurs techniques sur un DataFrame OHLCV.
Chaque fonction ajoute une ou plusieurs colonnes au DataFrame passé en entrée.
"""

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Ajoute la colonne 'rsi' au DataFrame."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df = df.copy()
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ---------------------------------------------------------------------------
# Moyennes Mobiles
# ---------------------------------------------------------------------------

MM_PERIODS = [1, 10, 20, 50, 100, 200]


def add_moving_averages(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
    """
    Ajoute les colonnes 'mm_{period}' pour chaque période demandée.
    Par défaut, calcule toutes les MM définies dans MM_PERIODS.
    """
    df = df.copy()
    if periods is None:
        periods = MM_PERIODS
    for p in periods:
        df[f"mm_{p}"] = df["close"].rolling(window=p).mean()
    return df


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Ajoute les colonnes 'macd', 'macd_signal', 'macd_hist'."""
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Ajoute les colonnes 'bb_upper', 'bb_middle', 'bb_lower'."""
    df = df.copy()
    df["bb_middle"] = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std()
    df["bb_upper"] = df["bb_middle"] + std_dev * rolling_std
    df["bb_lower"] = df["bb_middle"] - std_dev * rolling_std
    return df


# ---------------------------------------------------------------------------
# Application groupée
# ---------------------------------------------------------------------------

def add_btc_mm(df: pd.DataFrame, btc_mm: pd.Series) -> pd.DataFrame:
    """
    Aligne et ajoute la MM BTC au DataFrame de l'actif.
    La colonne ajoutée s'appelle 'btc_mm_{period}'.
    """
    df = df.copy()
    df = df.join(btc_mm, how="left")
    df[btc_mm.name] = df[btc_mm.name].ffill()
    return df


def apply_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Applique les indicateurs en fonction de la configuration d'une stratégie.

    config keys attendues :
        use_rsi        : bool
        rsi_period     : int
        mm_periods     : list[int]
        use_macd       : bool
        use_bollinger  : bool
        bollinger_band : "haute" | "basse"
        btc_mm         : pd.Series | None  (MM BTC pré-calculée)
    """
    df = df.copy()
    df = add_moving_averages(df, MM_PERIODS)

    if config.get("use_rsi"):
        df = add_rsi(df, period=config.get("rsi_period", 14))

    if config.get("use_macd"):
        df = add_macd(df)

    if config.get("use_bollinger"):
        df = add_bollinger(df)

    if config.get("btc_mm") is not None:
        df = add_btc_mm(df, config["btc_mm"])

    return df
