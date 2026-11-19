"""
src/utils/strategies.py
Règles des stratégies de tendance — SOURCE UNIQUE.

Le Screening (aujourd'hui), le backtest (chaque jour du passé) et le journal
(chaque jour en réel) appellent ces mêmes fonctions. Changer un seuil ici le
change partout : impossible qu'un backtest teste une règle et que le screener
en affiche une autre.

Quatre stratégies, deux par sens :
    📉 Tendance short   : shorter tant que l'actif est en baisse longue propre
    🔻 Rebond à shorter : attendre un rebond dans cette baisse, entrer quand il se retourne
    📈 Tendance long    : l'inverse en hausse
    🔺 Repli à acheter  : attendre un repli dans cette hausse, entrer quand il se retourne

Tout se calcule sur des clôtures JOURNALIÈRES COMPLÈTES (pas la bougie en cours).
"""

import numpy as np
import pandas as pd

JOURS_TENDANCE  = 365   # fenêtre des métriques (1 an, ou depuis le listing)
MM_TENDANCE     = 100   # la « ligne rouge »
MM_COURTE       = 10    # sert à repérer le rebond / repli et son retournement
JOURS_PENTE_MM  = 20    # pente de la MM100 mesurée sur 20 jours
JOURS_MIN_MM    = 60    # jours de MM100 exigés → 160 jours de cotation minimum
JOURS_REBOND    = 5     # le rebond doit avoir eu lieu dans les 5 jours précédents

# Seuils par défaut (préréglages du Screening, backtest, journal)
SEUILS = {
    "short": {"pct_cote_min": 80, "rebond_max": 60.0},
    "long":  {"pct_cote_min": 80, "rebond_max": 40.0},
}

STRATEGIES = {
    "tendance_short": {"libelle": "📉 Tendance short",   "sens": "short", "moment": "tout"},
    "rebond_short":   {"libelle": "🔻 Rebond à shorter", "sens": "short", "moment": "entree"},
    "tendance_long":  {"libelle": "📈 Tendance long",    "sens": "long",  "moment": "tout"},
    "repli_long":     {"libelle": "🔺 Repli à acheter",  "sens": "long",  "moment": "entree"},
}


# ---------------------------------------------------------------------------
# Métriques de tendance, jour par jour
# ---------------------------------------------------------------------------

def metriques_series(close: pd.Series, seulement_dernier: bool = False) -> pd.DataFrame:
    """Pour CHAQUE jour t, les métriques calculées avec les seules données ≤ t.

      perf_1an     variation sur la fenêtre (1 an, ou depuis le premier jour)
      pct_sous_mm  % des jours de la fenêtre où la clôture était SOUS la MM100
      pente_mm100  pente actuelle de la MM100, en % par mois (mesurée sur 20 j)
      pire_rebond  pire mouvement CONTRE la tendance sur la fenêtre, en %
                   (plus fort rebond depuis un plus bas si perf < 0, pire chute
                   depuis un plus haut si perf > 0)

    Aucune donnée future : c'est ce qui permet au backtest d'être honnête.
    NaN tant qu'il n'y a pas 160 jours de cotation.
    seulement_dernier=True : pire_rebond n'est calculé que pour le dernier jour
    (la boucle est le seul calcul coûteux — le Screening n'a besoin que d'aujourd'hui).
    """
    c = close.dropna()
    c = c[c > 0].astype(float)
    out = pd.DataFrame(index=c.index, columns=["perf_1an", "pct_sous_mm", "pente_mm100", "pire_rebond"],
                       dtype=float)
    n = len(c)
    if n < MM_TENDANCE + JOURS_MIN_MM:
        return out

    mm = c.rolling(MM_TENDANCE).mean()
    sous = (c < mm).astype(float).where(mm.notna())
    out["pct_sous_mm"] = sous.rolling(JOURS_TENDANCE, min_periods=JOURS_MIN_MM).mean() * 100

    base = c.shift(JOURS_TENDANCE - 1)
    base = base.fillna(c.iloc[0])
    out["perf_1an"] = (c / base - 1) * 100

    out["pente_mm100"] = (mm / mm.shift(JOURS_PENTE_MM) - 1) * 100 * 30 / JOURS_PENTE_MM

    v = c.to_numpy()
    debut = MM_TENDANCE + JOURS_MIN_MM - 1
    indices = [n - 1] if seulement_dernier else range(debut, n)
    rebond = np.full(n, np.nan)
    perf = out["perf_1an"].to_numpy()
    for t in indices:
        w = v[max(0, t - JOURS_TENDANCE + 1): t + 1]
        if perf[t] < 0:
            rebond[t] = (w / np.minimum.accumulate(w) - 1).max() * 100
        else:
            rebond[t] = (1 - w / np.maximum.accumulate(w)).max() * 100
    out["pire_rebond"] = rebond

    # Mêmes exigences que l'ancienne fonction : rien avant 160 jours de cotation
    out.iloc[:debut] = np.nan
    return out.round({"perf_1an": 1, "pct_sous_mm": 1, "pente_mm100": 1, "pire_rebond": 1})


def metriques_du_jour(close: pd.Series) -> dict:
    """Les 4 métriques d'aujourd'hui (None si historique trop court)."""
    # + 100 jours : la MM100 existe sur TOUTE la fenêtre d'un an, comme dans le backtest
    m = metriques_series(close.tail(JOURS_TENDANCE + MM_TENDANCE), seulement_dernier=True)
    if m.empty:
        return {k: None for k in ("perf_1an", "pct_sous_mm", "pente_mm100", "pire_rebond")}
    d = m.iloc[-1].to_dict()
    return {k: (None if pd.isna(v) else float(v)) for k, v in d.items()}


# ---------------------------------------------------------------------------
# Qualification et moment
# ---------------------------------------------------------------------------

def qualifie(perf, pct_sous, pente, rebond, sens: str,
             pct_cote_min: float | None = None, rebond_max: float | None = None):
    """L'actif est-il en tendance longue propre dans ce sens ?

    Fonctionne sur des scalaires comme sur des Series (NaN → False).
    """
    s = SEUILS[sens]
    pct_cote_min = s["pct_cote_min"] if pct_cote_min is None else pct_cote_min
    rebond_max = s["rebond_max"] if rebond_max is None else rebond_max
    perf, pct_sous, pente, rebond = (pd.to_numeric(x, errors="coerce") if isinstance(x, pd.Series)
                                     else (np.nan if x is None else x)
                                     for x in (perf, pct_sous, pente, rebond))
    if sens == "short":
        ok = (perf < 0) & (pct_sous >= pct_cote_min) & (pente < 0)
    else:
        ok = (perf > 0) & ((100 - pct_sous) >= pct_cote_min) & (pente > 0)
    ok = ok & (rebond <= rebond_max)
    return ok.fillna(False) if isinstance(ok, pd.Series) else bool(ok)


def moment_series(close: pd.Series, sens: str) -> pd.Series:
    """Où en est le court terme, PAR RAPPORT au sens de la tendance :

      "contre" : le prix va contre la tendance (au-dessus de la MM10 dans une
                 baisse = rebond ; en dessous dans une hausse = repli).
                 → surveiller, ne pas entrer
      "entree" : le contre-mouvement se retourne AUJOURD'HUI : le prix repasse
                 du bon côté de la MM10, la MM10 tourne dans le sens de la
                 tendance, et il y a eu un contre-mouvement dans les 5 jours
                 précédents. → le signal des stratégies Rebond / Repli
      "suite"  : le prix suit la tendance, sans contre-mouvement récent
    """
    c = close.dropna().astype(float)
    mm10 = c.rolling(MM_COURTE).mean()
    contre = (c > mm10) if sens == "short" else (c < mm10)
    tourne = (mm10 < mm10.shift(1)) if sens == "short" else (mm10 > mm10.shift(1))
    contre_recent = contre.shift(1).rolling(JOURS_REBOND, min_periods=1).max().fillna(0).astype(bool)
    m = pd.Series("suite", index=c.index)
    m[contre] = "contre"
    m[~contre & tourne & contre_recent] = "entree"
    m[mm10.isna()] = None
    return m


def moment_du_jour(close: pd.Series, sens: str) -> str | None:
    """Moment d'aujourd'hui (voir moment_series). None si historique trop court."""
    m = moment_series(close.tail(40), sens)
    return m.iloc[-1] if len(m) else None


def phase_du_jour(close: pd.Series, metriques: dict | None = None) -> dict:
    """Phase d'aujourd'hui pour chaque sens, avec les seuils par défaut.

    {"phase_short": "entree" | "contre" | "suite" | None, "phase_long": ...}
    None = l'actif n'est pas en tendance longue dans ce sens.
    """
    m = metriques if metriques is not None else metriques_du_jour(close)
    sortie = {}
    for sens in ("short", "long"):
        ok = qualifie(m.get("perf_1an"), m.get("pct_sous_mm"), m.get("pente_mm100"),
                      m.get("pire_rebond"), sens)
        sortie[f"phase_{sens}"] = moment_du_jour(close, sens) if ok else None
    return sortie


# Libellés pour l'affichage
LIB_PHASE = {
    "short": {"suite": "📉 Baisse en cours", "contre": "👀 Rebond (surveiller)",
              "entree": "🎯 Rebond qui se retourne"},
    "long":  {"suite": "📈 Hausse en cours", "contre": "👀 Repli (surveiller)",
              "entree": "🎯 Repli qui se retourne"},
}


def libelle_phase(phase_short, phase_long) -> str | None:
    if isinstance(phase_short, str):
        return LIB_PHASE["short"].get(phase_short)
    if isinstance(phase_long, str):
        return LIB_PHASE["long"].get(phase_long)
    return None
