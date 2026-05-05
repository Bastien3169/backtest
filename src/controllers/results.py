"""
results.py
Construction des tableaux de résultats.
"""

import pandas as pd


def build_result_table(strategy_results: dict, durees: list[int], date_ranges=None, is_short: bool = False) -> pd.DataFrame:
    """
    Tableau par stratégie.
    Si date_ranges est fourni, les colonnes sont labelisées avec les dates.
    """
    bnh_label = "Rendement S&H (%)" if is_short else "Rendement B&H (%)"
    rows = {
        "Rendement strat (%)":      [],
        bnh_label:                  [],
        "Alpha vs B&H (%)":         [],
        "Plus-value (€)":           [],
        "Drawdown max (%)":         [],
        "Nb trades":                [],
        "Win rate (%)":             [],
        "Durée moy. détention (h)": [],
    }

    for d in durees:
        r = strategy_results.get(d, {})
        rend = r.get("rendement_pct", 0)
        bnh  = r.get("bnh_rendement", 0)
        rows["Rendement strat (%)"].append(rend)
        rows[bnh_label].append(bnh)
        rows["Alpha vs B&H (%)"].append(round(rend - bnh, 4))
        rows["Plus-value (€)"].append(r.get("plus_value_eur", 0))
        rows["Drawdown max (%)"].append(r.get("drawdown_max", 0))
        rows["Nb trades"].append(r.get("nb_trades", 0))
        rows["Win rate (%)"].append(r.get("win_rate", 0))
        rows["Durée moy. détention (h)"].append(float(r.get("avg_hold_h", 0)))

    # Labels colonnes
    if date_ranges and len(date_ranges) == len(durees):
        col_labels = [f"{d1.strftime('%d/%m/%y')}→{d2.strftime('%d/%m/%y')}"
                      for d1, d2 in date_ranges]
    else:
        col_labels = [f"{d}j" for d in durees]

    return pd.DataFrame(rows, index=col_labels).T


def build_comparison_table(all_results: dict, durees: list[int]) -> pd.DataFrame:
    rows = []
    for name, strategy_results in all_results.items():
        row = {"Stratégie": name}
        for d in durees:
            r = strategy_results.get(d, {})
            row[f"Rendement {d}j (%)"] = r.get("rendement_pct", 0)
            row[f"B&H {d}j (%)"]       = r.get("bnh_rendement", 0)
            row[f"Drawdown {d}j (%)"]   = r.get("drawdown_max", 0)
            row[f"Win rate {d}j (%)"]   = r.get("win_rate", 0)
            row[f"Nb trades {d}j"]      = r.get("nb_trades", 0)
        rows.append(row)
    return pd.DataFrame(rows).set_index("Stratégie")
