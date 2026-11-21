"""
src/utils/backtest_oi.py
Mini-backtest des signaux d'OPEN INTEREST, sur les photos horaires
Hyperliquid enregistrées par l'app (table hl_snapshots).

Yahoo n'a pas d'historique d'OI : le seul historique disponible est celui que
l'app enregistre elle-même depuis début octobre 2026. C'est court (quelques
semaines, un seul régime de marché) : ce module montre une PISTE, il ne prouve
rien. Il se relance quand on veut : plus le temps passe, plus il a de cas.

Pour chaque actif et chaque heure, avec les seules données passées :
  - Δ OI 24 h et Δ OI 4 h, en %
  - leur z-score robuste par rapport aux habitudes de CET actif
    (médiane et MAD sur 60 jours glissants, 7 jours minimum — comme le radar)
  - Δ prix 24 h, jugé « plat » s'il fait moins de la moitié du mouvement
    24 h habituel de l'actif

Un signal = la première heure où la condition est remplie, puis 24 h de
pause pour cet actif (sinon une même situation compterait 24 fois).
On mesure ensuite le prix 1, 3 et 7 jours plus tard, et on compare au
marché (tous les actifs, au même moment).
"""

import numpy as np
import pandas as pd

from src.utils import indicateurs as I

Z_SEUIL         = 2.0      # |z| ≥ 2 = inhabituel (comme le radar)
Z_SEUIL_4H      = 1.0      # l'OI accélère encore sur les 4 dernières heures
FENETRE_H       = 60 * 24  # habitudes de l'actif : 60 jours
MIN_H           = 7 * 24   # 7 jours d'historique avant le premier z-score
PLAT            = 0.5      # |Δ prix 24 h| < 0,5 × mouvement 24 h habituel
PAUSE_H         = 24
HORIZONS_H      = (24, 72, 168)

SETUPS = {
    "sequence":     "🔍 Ta séquence : z OI 24 h ≥ 2, puis OI 4 h qui accélère, prix plat",
    "accumulation": "🟢 z OI 24 h ≥ 2, prix plat",
    "oi_hausse_px_hausse": "🔵 z OI 24 h ≥ 2, prix en hausse",
    "oi_hausse_px_baisse": "🟣 z OI 24 h ≥ 2, prix en baisse",
    "oi_chute_px_hausse":  "🟠 z OI 24 h ≤ −2, prix en hausse (rachat de shorts)",
    "oi_chute_px_baisse":  "⚫ z OI 24 h ≤ −2, prix en baisse (purge des longs)",
    "reference":    "🎲 Référence : tous les actifs, chaque jour à 00 h UTC",
}


def charger_photos() -> pd.DataFrame:
    from src.utils.hl_snapshots import load_history
    return load_history(jours=3650)


def grille(photos: pd.DataFrame, colonne: str) -> pd.DataFrame:
    """Une ligne par heure, une colonne par actif. Trou de plus de 2 h = NaN."""
    p = photos.copy()
    p["h"] = pd.to_datetime(p["ts"]).dt.floor("h")
    g = p.pivot_table(index="h", columns="coin", values=colonne, aggfunc="last")
    g = g.reindex(pd.date_range(g.index.min(), g.index.max(), freq="h"))
    return g.ffill(limit=2)


def zscore(chg: pd.DataFrame) -> pd.DataFrame:
    """z-score robuste par actif sur 60 jours glissants (indicateurs.zscore_robuste)."""
    return I.zscore_robuste(chg, FENETRE_H, MIN_H)


def _evenements(cond: pd.DataFrame) -> list[tuple]:
    """(heure, actif) : première heure vraie, puis pause de 24 h par actif."""
    sortie = []
    for coin in cond.columns:
        pos = np.flatnonzero(cond[coin].to_numpy(bool))
        dernier = -10 ** 9
        for p in pos:
            if p - dernier >= PAUSE_H:
                sortie.append((cond.index[p], coin))
                dernier = p
    return sortie


def analyser(photos: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    photos = charger_photos() if photos is None else photos
    info = {"photos": len(photos)}
    if photos.empty:
        return pd.DataFrame(), info
    oi = grille(photos, "oi")
    px = grille(photos, "mark_px")
    info.update(debut=oi.index.min(), fin=oi.index.max(), actifs=oi.shape[1],
                heures=len(oi))

    z24 = zscore(oi / oi.shift(24) - 1)
    z4 = zscore(oi / oi.shift(4) - 1)
    pc24 = px / px.shift(24) - 1
    habituel = pc24.abs().rolling(FENETRE_H, min_periods=MIN_H).median()
    plat = pc24.abs() < PLAT * habituel
    hausse = pc24 >= PLAT * habituel
    baisse = pc24 <= -PLAT * habituel

    conditions = {
        "sequence":            (z24 >= Z_SEUIL) & (z4 >= Z_SEUIL_4H) & plat,
        "accumulation":        (z24 >= Z_SEUIL) & plat,
        "oi_hausse_px_hausse": (z24 >= Z_SEUIL) & hausse,
        "oi_hausse_px_baisse": (z24 >= Z_SEUIL) & baisse,
        "oi_chute_px_hausse":  (z24 <= -Z_SEUIL) & hausse,
        "oi_chute_px_baisse":  (z24 <= -Z_SEUIL) & baisse,
    }
    minuit = np.asarray(oi.index.hour == 0)[:, None]          # une colonne, diffusée à tous les actifs
    conditions["reference"] = z24.notna() & minuit

    futurs = {h: px.shift(-h) / px - 1 for h in HORIZONS_H}
    marche = {h: f.mean(axis=1) for h, f in futurs.items()}
    marche_abs = {h: f.abs().mean(axis=1) for h, f in futurs.items()}

    lignes = []
    for cle, cond in conditions.items():
        ev = _evenements(cond.fillna(False))
        ligne = {"setup": SETUPS[cle], "cas": len(ev),
                 "actifs": len({c for _, c in ev})}
        for h in HORIZONS_H:
            r = pd.Series([futurs[h].at[t, c] for t, c in ev], dtype=float) * 100
            m = pd.Series([marche[h].at[t] for t, _ in ev], dtype=float) * 100
            ma = pd.Series([marche_abs[h].at[t] for t, _ in ev], dtype=float) * 100
            ok = r.notna()
            j = h // 24
            ligne[f"moy_{j}"] = round(r[ok].mean(), 2) if ok.any() else None
            ligne[f"marche_{j}"] = round(m[ok].mean(), 2) if ok.any() else None
            ligne[f"hausse_{j}"] = round((r[ok] > 0).mean() * 100) if ok.any() else None
            ligne[f"ampleur_{j}"] = round(r[ok].abs().mean(), 2) if ok.any() else None
            ligne[f"marche_amp_{j}"] = round(ma[ok].mean(), 2) if ok.any() else None
            ligne[f"n_{j}"] = int(ok.sum())
        lignes.append(ligne)
    return pd.DataFrame(lignes), info


# ---------------------------------------------------------------------------
# Setup « compression + z OI fort, dans le sens du BTC »
# ---------------------------------------------------------------------------
# Signal sur un alt : son range quotidien s'est resserré PAR RAPPORT À SES
# PROPRES HABITUDES (compression < 1 : amplitude moyenne des 5 derniers jours
# de CET actif inférieure à sa médiane sur 30 jours) ET son
# OI vient de bondir (z OI 24 h ≥ 2). Le sens vient du BTC :
#     short si BTC sous sa MM20 ET sa MM100
#     long  si BTC au-dessus des deux
#     rien sinon
# Comparé au même pari pris au hasard (tous les alts, même sens, même heure) :
# le setup ne vaut quelque chose que s'il fait mieux que « suivre le BTC ».

COMPRESSION_MAX = 1.0        # strictement en dessous
JOURS_COURT, JOURS_LONG, JOURS_LONG_MIN = 5, 30, 20
FRAIS_AR_PCT = 0.19          # aller-retour, comme le backtest principal


def _btc_regime(index: pd.DatetimeIndex) -> pd.Series:
    """+1 (BTC au-dessus de MM20 et MM100), −1 (en dessous des deux), 0 sinon.
    Bougies journalières Yahoo ; le régime d'un jour vaut pour les heures du
    LENDEMAIN (la clôture n'est connue qu'à minuit) : aucune donnée future."""
    import yfinance as yf
    c = yf.Ticker("BTC-USD").history(period="400d", interval="1d")["Close"]
    idx = pd.to_datetime(c.index)
    c.index = (idx.tz_convert(None) if idx.tz is not None else idx).normalize()
    mm20, mm100 = c.rolling(20).mean(), c.rolling(100).mean()
    reg = pd.Series(0, index=c.index)
    reg[(c > mm20) & (c > mm100)] = 1
    reg[(c < mm20) & (c < mm100)] = -1
    reg[mm100.isna()] = np.nan
    reg.index = reg.index + pd.Timedelta(days=1)          # connu le lendemain
    return reg.reindex(index.normalize()).set_axis(index)


def _compression(px: pd.DataFrame) -> pd.DataFrame:
    """Compression par heure, à partir des photos horaires : range quotidien
    (max − min) / dernier prix, sur les jours UTC COMPLETS précédant l'heure."""
    jour = px.index.normalize()
    rng = (px.groupby(jour).max() - px.groupby(jour).min()) / px.groupby(jour).last()
    nb = px.groupby(jour).count()
    rng = rng.where(nb >= 20)                              # journée trop trouée : ignorée
    court = rng.rolling(JOURS_COURT, min_periods=JOURS_COURT).mean()
    long_ = rng.rolling(JOURS_LONG, min_periods=JOURS_LONG_MIN).median()
    comp = (court / long_).shift(1)                        # jours complets uniquement
    return comp.reindex(jour).set_axis(px.index)


def analyser_compression(photos: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    photos = charger_photos() if photos is None else photos
    info = {"photos": len(photos)}
    if photos.empty:
        return pd.DataFrame(), info
    oi = grille(photos, "oi")
    px = grille(photos, "mark_px")
    info.update(debut=oi.index.min(), fin=oi.index.max(), actifs=oi.shape[1])

    z24 = zscore(oi / oi.shift(24) - 1)
    comp = _compression(px)
    regime = _btc_regime(oi.index)
    info["heures_short"] = int((regime == -1).sum())
    info["heures_long"] = int((regime == 1).sum())
    base = (z24 >= Z_SEUIL) & (comp < COMPRESSION_MAX)
    futurs = {h: px.shift(-h) / px - 1 for h in HORIZONS_H}

    lignes = []
    for sens, signe, lib in ((-1, -1, "📉 Short (BTC sous MM20 et MM100)"),
                             (1, 1, "📈 Long (BTC au-dessus de MM20 et MM100)")):
        actif_regime = (regime == sens).to_numpy()[:, None]
        ev = _evenements((base & actif_regime).fillna(False))
        ligne = {"setup": lib, "cas": len(ev), "actifs": len({c for _, c in ev})}
        for h in HORIZONS_H:
            j = h // 24
            r = pd.Series([futurs[h].at[t, c] for t, c in ev], dtype=float) * 100 * signe - FRAIS_AR_PCT
            hasard = pd.Series([futurs[h].loc[t].mean() for t, _ in ev], dtype=float) * 100 * signe - FRAIS_AR_PCT
            ok = r.notna()
            ligne[f"gain_{j}"] = round(r[ok].mean(), 2) if ok.any() else None
            ligne[f"median_{j}"] = round(r[ok].median(), 2) if ok.any() else None
            ligne[f"gagnants_{j}"] = round((r[ok] > 0).mean() * 100) if ok.any() else None
            ligne[f"hasard_{j}"] = round(hasard[ok].mean(), 2) if ok.any() else None
            ligne[f"n_{j}"] = int(ok.sum())
        lignes.append(ligne)
    return pd.DataFrame(lignes), info
