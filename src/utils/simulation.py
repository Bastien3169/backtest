"""
src/utils/simulation.py
Moteur de trades partagé par le backtest des stratégies (page Historique) et
l'Analyse marché.

Règles, identiques partout :
  - décision à la clôture de la bougie t, exécution à l'OUVERTURE de t+1
  - une position à la fois, sans levier
  - sorties (la première atteinte) :
      stop    : niveau fixe (stop_niveau, lu sur la bougie du signal) ou stop en %
      objectif: take profit en %
      (stop et objectif touchés sur la même bougie : on suppose le pire, le stop)
      duree   : sortie à l'ouverture après `bougies` bougies
      mm      : clôture de l'autre côté de la MM → sortie à l'ouverture suivante
      fin     : position encore ouverte à la dernière bougie, fermée à sa clôture
  - pas de nouvelle entrée sur la bougie d'un stop ou d'un objectif
  - mae_pct : pire mouvement contre la position pendant le trade (levier tenable)
"""

import numpy as np
import pandas as pd


def simuler(df: pd.DataFrame, signal: np.ndarray, sens, *, bougies: int = 0,
            sl: float = 0.0, tp: float = 0.0, mm: np.ndarray | None = None,
            stop_niveau: np.ndarray | None = None, frais_ar: float = 0.19) -> list[dict]:
    """df : Open/High/Low/Close. signal[t] : entrer à l'ouverture de t+1.
    sens : +1 / −1 (constant) ou tableau par bougie (0 = pas de trade)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    dates = df.index
    n = len(df)
    sens = np.full(n, sens) if np.isscalar(sens) else np.asarray(sens)
    trades, pos, entrer = [], None, 0

    def fermer(t, prix, motif):
        brut = pos["s"] * (prix / pos["px"] - 1) * 100
        trades.append({"t_entree": pos["t"], "t_sortie": t, "entree": dates[pos["t"]],
                       "sortie": dates[t], "entree_px": pos["px"], "sortie_px": prix,
                       "sens": pos["s"], "motif": motif, "rend_pct": brut - frais_ar,
                       "mae_pct": pos["mae"], "bougies": t - pos["t"],
                       "jours": int((dates[t] - dates[pos["t"]]).days)})

    for t in range(n):
        if pos is None and entrer:
            stop = None
            if stop_niveau is not None:
                stop = stop_niveau[t - 1]
            elif sl:
                stop = o[t] * (1 - entrer * sl / 100)
            pos = {"t": t, "px": o[t], "s": entrer, "mae": 0.0, "sortir": None, "stop": stop,
                   "tp": o[t] * (1 + entrer * tp / 100) if tp else None}
        entrer = 0

        if pos is not None:
            s = pos["s"]
            if pos["sortir"]:
                fermer(t, o[t], pos["sortir"])
                pos = None
            elif bougies and t - pos["t"] >= bougies:
                fermer(t, o[t], "duree")
                pos = None
            else:
                adverse = (1 - l[t] / pos["px"]) if s > 0 else (h[t] / pos["px"] - 1)
                pos["mae"] = max(pos["mae"], adverse * 100)
                stop, cible = pos["stop"], pos["tp"]
                if stop is not None and ((s > 0 and l[t] <= stop) or (s < 0 and h[t] >= stop)):
                    fermer(t, min(o[t], stop) if s > 0 else max(o[t], stop), "stop")
                    pos = None
                    continue
                if cible is not None and ((s > 0 and h[t] >= cible) or (s < 0 and l[t] <= cible)):
                    fermer(t, max(o[t], cible) if s > 0 else min(o[t], cible), "objectif")
                    pos = None
                    continue
                if mm is not None and not np.isnan(mm[t]) and s * (c[t] - mm[t]) < 0:
                    pos["sortir"] = "mm"
            if pos is not None:
                continue

        if t < n - 1 and signal[t] and sens[t] != 0:
            entrer = int(sens[t])

    if pos is not None:
        fermer(n - 1, c[n - 1], "fin")
    return trades
