"""
src/utils/indicateurs.py
Indicateurs partagés — UNE version de chacun, utilisée par le Screening, le
radar, le backtest des stratégies et l'Analyse marché.
"""

import numpy as np
import pandas as pd

MAD_VERS_ECART_TYPE = 1.4826          # MAD × 1,4826 ≈ écart-type pour une loi normale


def rsi(close: pd.Series, periode: int = 14) -> pd.Series:
    """RSI de Wilder. 100 quand il n'y a eu aucune baisse sur la période."""
    delta = close.diff()
    hausse = delta.clip(lower=0).ewm(alpha=1 / periode, adjust=False).mean()
    baisse = (-delta.clip(upper=0)).ewm(alpha=1 / periode, adjust=False).mean()
    out = 100 - 100 / (1 + hausse / baisse.replace(0, np.nan))
    return out.mask((baisse == 0) & hausse.notna(), 100.0)


def amplitude(df: pd.DataFrame) -> pd.Series:
    """(haut − bas) / clôture, en fraction. Les divisions impossibles deviennent NaN."""
    return ((df["High"] - df["Low"]) / df["Close"]).replace([np.inf, -np.inf], np.nan)


def compression(df: pd.DataFrame, court: int = 5, long: int = 30,
                min_long: int | None = None) -> pd.Series:
    """Amplitude moyenne des `court` dernières bougies ÷ amplitude médiane des `long`
    dernières, pour CET actif. < 1 : le range se resserre par rapport à ses habitudes."""
    amp = amplitude(df)
    return amp.rolling(court).mean() / amp.rolling(long, min_periods=min_long or long).median()


def zscore_robuste(x, fenetre: int, min_periodes: int):
    """(x − médiane) / (1,4826 × MAD), sur une fenêtre glissante : « combien de fois
    plus que d'habitude », insensible aux valeurs extrêmes."""
    med = x.rolling(fenetre, min_periods=min_periodes).median()
    mad = (x - med).abs().rolling(fenetre, min_periods=min_periodes).median()
    return (x - med) / (MAD_VERS_ECART_TYPE * mad.replace(0, np.nan))
