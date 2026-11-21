"""
src/utils/bilan.py
Statistiques et verdict partagés par la page Historique et l'Analyse marché.
"""

import numpy as np
import pandas as pd

TRADES_MIN = 30         # en dessous, une période ne permet pas de juger


def stats(t: pd.DataFrame, entree: str = "entree", duree: str = "jours") -> dict:
    """Statistiques d'une liste de trades (colonnes rend_pct, mae_pct, symbol)."""
    if t is None or t.empty:
        return {"trades": 0}
    r = t["rend_pct"]
    pertes = -r[r < 0].sum()
    mae90 = float(t["mae_pct"].quantile(0.9))
    tenable = round(min(100 / mae90, 50), 1) if mae90 > 0 else None
    # Rendement par actif : capital réinvesti trade après trade sur CHAQUE actif (ses
    # positions ne se chevauchent pas), puis moyenne — même mesure que « Rendement (%) »
    # des pages d'analyse technique.
    par_actif = t.sort_values(entree).groupby("symbol")["rend_pct"].apply(
        lambda x: ((1 + x / 100).prod() - 1) * 100)
    return {
        "trades": len(r), "actifs": int(par_actif.size),
        "gagnants": round((r > 0).mean() * 100, 1),
        "rend_moy": round(r.mean(), 2), "rend_med": round(r.median(), 2),
        "rend_actif": round(float(par_actif.mean()), 2),
        "gain_gagnants": round(r[r > 0].mean(), 2) if (r > 0).any() else None,
        "perte_perdants": round(r[r < 0].mean(), 2) if (r < 0).any() else None,
        "pf": round(r[r > 0].sum() / pertes, 2) if pertes > 0 else None,
        "mae_med": round(float(t["mae_pct"].median()), 1), "mae_p90": round(mae90, 1),
        "levier_tenable": tenable,
        # Levier conseillé : la moitié de celui qui aurait survécu à 9 trades sur 10
        "levier_max": max(1, int(tenable / 2)) if tenable else None,
        "duree_moy": round(t[duree].mean(), 1) if duree in t else None,
    }


def verdict(periodes: list[tuple[dict, dict]], avec_oi: bool = False) -> str:
    """periodes : [(stats de la stratégie, stats de la référence), …].

    ✅ si, sur CHAQUE période : au moins 30 trades, profit factor > 1 et rendement
    moyen par trade supérieur à la référence. Une seule règle, partout dans l'app."""
    def bonne(s, ref):
        return (s.get("pf") or 0) > 1 and (s.get("rend_moy") or -1e9) > (ref.get("rend_moy") or -1e9)

    jugeables = [(s, ref) for s, ref in periodes if s.get("trades", 0) >= TRADES_MIN]
    if not jugeables:
        return f"⏳ Trop peu de trades pour juger ({TRADES_MIN} minimum par période)"
    nb_bonnes = sum(bonne(s, ref) for s, ref in jugeables)
    if nb_bonnes == 0:
        return "❌ Ne marche pas"
    if avec_oi:
        return "⚠️ Prometteur, mais OI disponible seulement depuis octobre"
    if nb_bonnes == len(periodes) and len(periodes) >= 2:
        return "✅ Tient sur toutes les périodes"
    if len(periodes) == 1:
        return "⚠️ Une seule période testée : ajoutes-en pour confirmer"
    return f"⚠️ Tient sur {nb_bonnes} période(s) sur {len(periodes)}"


def stats_gains(gains: list[float]) -> dict:
    """Mêmes clés que stats() utiles au verdict, à partir d'une simple liste de gains (%)
    — le format des trades du moteur d'origine (src/controllers/backtest.py)."""
    r = pd.Series(gains, dtype=float)
    if r.empty:
        return {"trades": 0}
    pertes = -r[r < 0].sum()
    return {"trades": len(r), "gagnants": round((r > 0).mean() * 100, 1),
            "rend_moy": round(r.mean(), 2),
            "pf": round(r[r > 0].sum() / pertes, 2) if pertes > 0 else None}


def alpha(s: dict, ref: dict):
    """Rendement moyen par trade de la stratégie moins celui de la référence."""
    if not s.get("trades"):
        return None
    return round((s.get("rend_moy") or 0) - (ref.get("rend_moy") or 0), 2)
