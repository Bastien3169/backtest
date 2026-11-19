"""
pages/6_📜_Historique.py
Historique des stratégies : ce qui marche, ce qui ne marche pas.

Deux sources, une seule question :
    🧪 Backtest   → le PASSÉ : chaque stratégie du Screening rejouée depuis 2020,
                   découpée en Apprentissage / Test, contre une référence au hasard
    📒 En réel    → le PRÉSENT : le journal quotidien note la phase de chaque
                   actif ; on mesure ce qui s'est passé après chaque signal

Les règles viennent toutes de src/utils/strategies.py : ce qui est testé ici
est exactement ce que le Screening affiche.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json

import pandas as pd
import streamlit as st

from src.auth.ui import require_admin
from src.utils import backtest_oi as O
from src.utils import backtest_strategies as B
from src.utils import journal as J
from src.utils import strategies as S

st.set_page_config(page_title="Historique des stratégies", page_icon="📜", layout="wide")
require_admin()

st.title("📜 Historique des stratégies")
st.caption("Ce qui marche et ce qui ne marche pas — sur le passé (backtest) et en réel (journal).")

VERT, ROUGE, ORANGE = "#2e9e5b", "#d64545", "#d98e04"

tab_bt, tab_oi, tab_reel, tab_regles = st.tabs(["🧪 Backtest (passé)", "🔬 Signaux OI",
                                                "📒 En réel (journal)", "📏 Les règles"])

# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def _verdict(ligne_app, ligne_test, ref_test) -> str:
    """✅ tient · ⚠️ à confirmer · ❌ ne marche pas. Règle affichée dans l'onglet Règles."""
    if ligne_test is None or pd.isna(ligne_test.get("profit_factor")):
        return "❌ Ne marche pas"
    pf_t = ligne_test["profit_factor"]
    pf_a = ligne_app["profit_factor"] if ligne_app is not None else None
    bat_ref = ref_test is None or ligne_test["rend_moy"] > ref_test
    if pf_t <= 1 or not bat_ref:
        return "❌ Ne marche pas"
    if pf_t >= 1.2 and pf_a is not None and pf_a >= 1.2 and ligne_test["trades"] >= 30:
        return "✅ Tient"
    return "⚠️ À confirmer"


def _tableau(resume: pd.DataFrame) -> pd.DataFrame:
    idx = resume.set_index(["strategie", "sortie", "periode"])
    ref = {sens: (idx.loc[(k, "20j", "Test"), "rend_moy"] if (k, "20j", "Test") in idx.index else None)
           for k, sens in (("ref_short", "short"), ("ref_long", "long"))}
    lignes = []
    for (cle, sortie), _ in resume.groupby(["strategie", "sortie"], sort=False):
        g = lambda p: (idx.loc[(cle, sortie, p)].to_dict() if (cle, sortie, p) in idx.index else None)
        app, test, tout = g("Apprentissage"), g("Test"), g("Tout")
        est_ref = cle in B.REFERENCES
        sens = (B.REFERENCES if est_ref else S.STRATEGIES)[cle]["sens"]
        lignes.append({
            "Stratégie": B.libelle(cle),
            "Sortie": B.SORTIES.get(sortie, {}).get("libelle", "Tenue 20 jours"),
            "Verdict": "— référence" if est_ref else _verdict(app, test, ref[sens]),
            "Trades (test)": (test or {}).get("trades"),
            "Gagnants (test)": (test or {}).get("gagnants_pct"),
            "Rend. moyen (test)": (test or {}).get("rend_moy"),
            "Rend. médian (test)": (test or {}).get("rend_med"),
            "Réf. même sens (test)": ref[sens],
            "PF apprentissage": (app or {}).get("profit_factor"),
            "PF test": (test or {}).get("profit_factor"),
            "MAE p90": (tout or {}).get("mae_p90"),
            "Levier tenable": (tout or {}).get("levier_tenable"),
            "Durée moy.": (tout or {}).get("jours_moy"),
        })
    df = pd.DataFrame(lignes)
    ordre = {"✅ Tient": 0, "⚠️ À confirmer": 1, "❌ Ne marche pas": 2, "— référence": 3}
    return df.sort_values(["Verdict", "PF test"], key=lambda s: s.map(ordre) if s.name == "Verdict" else -s.fillna(-1))


def _couleur_verdict(v):
    if isinstance(v, str) and v.startswith("✅"):
        return f"color: {VERT}; font-weight: 600"
    if isinstance(v, str) and v.startswith("❌"):
        return f"color: {ROUGE}; font-weight: 600"
    if isinstance(v, str) and v.startswith("⚠️"):
        return f"color: {ORANGE}; font-weight: 600"
    return ""


with tab_bt:
    c1, c2 = st.columns([1, 3])
    with c1:
        lancer = st.button("▶️ Lancer un backtest", type="primary",
                           help="Télécharge l'historique Yahoo de tout l'univers depuis 2020 "
                                "et rejoue chaque stratégie. 3 à 6 minutes.")
    with c2:
        st.caption("Chaque lancement est conservé : tu peux comparer les résultats d'un "
                   "lancement à l'autre (après un changement de règle, par exemple).")
    if lancer:
        barre = st.progress(0.0, text="Démarrage…")
        try:
            run, _ = B.lancer(lambda x, msg: barre.progress(min(max(x, 0.0), 1.0), text=msg))
            barre.progress(1.0, text=f"Terminé : {run}")
        except Exception as e:
            st.error(f"Backtest interrompu : {e}")

    runs = B.charger_runs()
    if runs.empty:
        st.info("Aucun backtest enregistré. Clique sur « Lancer un backtest ».")
    else:
        run = st.selectbox("Lancement", runs["run"].tolist(), index=0,
                           format_func=lambda r: f"{r} ({int(runs.set_index('run').loc[r, 'trades'])} trades)")
        params = json.loads(runs.set_index("run").loc[run, "params"] or "{}")
        resume = B.charger_resume(run)
        st.caption(
            f"{params.get('actifs', '?')} actifs · depuis {params.get('depuis', '?')} · "
            f"**Apprentissage** avant le {params.get('coupure_test', '?')}, **Test** après · "
            f"frais + glissement {2 * (params.get('frais_pct_cote', 0) + params.get('glissement_pct_cote', 0)):.2f} % "
            "par aller-retour · funding non compté · sans levier"
        )
        if params.get("ecartes"):
            with st.expander(f"⚠️ {len(params['ecartes'])} actifs écartés ou coupés (données Yahoo)"):
                st.caption("Mauvais ticker = Yahoo cote un AUTRE token sous ce symbole : à corriger "
                           "dans la liste des actifs. Historique coupé = Yahoo a réutilisé le "
                           "symbole d'un ancien token ; seule la partie récente est gardée.")
                st.write("\n".join(f"- {e}" for e in params["ecartes"]))
        elif "ecartes" not in params:
            st.warning("Lancement antérieur aux garde-fous de données : certains actifs avaient "
                       "un mauvais ticker Yahoo (ARB, JUP, UNI, LIT…) et faussent les chiffres, "
                       "surtout ceux des références. Relance un backtest.")
        tab = _tableau(resume)
        st.dataframe(
            tab.style.map(_couleur_verdict, subset=["Verdict"]), hide_index=True, width="stretch",
            column_config={
                "Gagnants (test)": st.column_config.NumberColumn(format="%.0f %%"),
                "Rend. moyen (test)": st.column_config.NumberColumn(
                    format="%+.2f %%", help="Rendement moyen par trade, net de frais, sur la période Test."),
                "Rend. médian (test)": st.column_config.NumberColumn(
                    format="%+.2f %%",
                    help="Le trade du milieu : la moitié des trades fait mieux, la moitié moins "
                         "bien. Négatif avec une moyenne positive = beaucoup de petites pertes "
                         "et quelques gros gains (normal en suivi de tendance)."),
                "Réf. même sens (test)": st.column_config.NumberColumn(
                    format="%+.2f %%",
                    help="Même sens, sans aucun critère : des positions de 20 jours prises au "
                         "hasard sur tous les actifs. Si la stratégie ne fait pas mieux, ses gains "
                         "viennent du marché (tout baissait), pas de la règle."),
                "PF apprentissage": st.column_config.NumberColumn(
                    format="%.2f", help="Profit factor = somme des gains ÷ somme des pertes. "
                                        "> 1 = gagnant. Période ancienne."),
                "PF test": st.column_config.NumberColumn(
                    format="%.2f", help="Profit factor sur le dernier tiers, jamais utilisé pour "
                                        "régler quoi que ce soit. C'est lui qui compte."),
                "MAE p90": st.column_config.NumberColumn(
                    format="%.0f %%", help="9 trades sur 10 n'ont jamais été plus loin que ça "
                                           "contre toi avant la sortie."),
                "Levier tenable": st.column_config.NumberColumn(
                    format="×%.1f", help="Levier qui aurait survécu à 9 trades sur 10 "
                                         "(liquidation ≈ 100 % ÷ levier). Prends nettement moins."),
                "Durée moy.": st.column_config.NumberColumn(format="%.0f j"),
            },
        )

        # Évolution d'un lancement à l'autre
        tout = B.charger_resume()
        tout = tout[(tout["periode"] == "Test") & ~tout["strategie"].isin(B.REFERENCES)]
        if tout["run"].nunique() > 1:
            st.markdown("**Évolution du PF test d'un lancement à l'autre**")
            tout["Stratégie"] = tout["strategie"].map(B.libelle) + " · " + tout["sortie"]
            piv = tout.pivot_table(index="Stratégie", columns="run", values="profit_factor")
            st.dataframe(piv[sorted(piv.columns, reverse=True)[:6]], width="stretch")

        with st.expander("🔎 Détail des trades"):
            trades = B.charger_trades(run)
            if trades.empty:
                st.info("Aucun trade pour ce lancement.")
            else:
                f1, f2, f3 = st.columns(3)
                strat = f1.selectbox("Stratégie", ["Toutes"] + list(S.STRATEGIES) + list(B.REFERENCES),
                                     format_func=lambda k: k if k == "Toutes" else B.libelle(k))
                sortie = f2.selectbox("Sortie", ["Toutes", "mm100", "mm20", "20j"])
                actif = f3.selectbox("Actif", ["Tous"] + sorted(trades["symbol"].unique()))
                t = trades
                if strat != "Toutes":
                    t = t[t["strategie"] == strat]
                if sortie != "Toutes":
                    t = t[t["sortie"] == sortie]
                if actif != "Tous":
                    t = t[t["symbol"] == actif]
                st.caption(f"{len(t)} trades · rendement moyen {t['rend_pct'].mean():+.2f} %")
                t = t.assign(strategie=t["strategie"].map(B.libelle)).sort_values("entree_date", ascending=False)
                st.dataframe(
                    t.drop(columns=["run"]), hide_index=True, width="stretch",
                    column_config={
                        "rend_pct": st.column_config.NumberColumn("Rend. net", format="%+.2f %%"),
                        "mae_pct": st.column_config.NumberColumn("MAE", format="%.1f %%"),
                    },
                )

# ---------------------------------------------------------------------------
# Signaux OI — sur les photos horaires enregistrées par l'app
# ---------------------------------------------------------------------------
with tab_oi:
    st.caption(
        "Yahoo n'a pas d'historique d'open interest : ce test utilise les photos horaires "
        "Hyperliquid que l'app enregistre depuis début octobre 2026. Quelques semaines, un "
        "seul régime de marché : c'est une **piste**, pas une preuve. Relance-le dans un mois, "
        "il aura plus de cas."
    )
    if st.button("🔬 Analyser les signaux OI", type="primary",
                 help="Lit toutes les photos enregistrées. Quelques secondes."):
        with st.spinner("Lecture des photos et calcul…"):
            st.session_state["_oi_res"] = O.analyser()
    if "_oi_res" in st.session_state:
        _r, _i = st.session_state["_oi_res"]
        if _r.empty or _r["cas"].sum() == 0:
            st.info("Pas assez d'historique continu : il faut au moins 7 jours de photos horaires "
                    "sans trou pour calculer les premiers z-scores (c'est le cas sur Railway, pas "
                    "forcément en local).")
        else:
            st.caption(f"{_i['actifs']} actifs · du {_i['debut']:%d/%m/%Y} au {_i['fin']:%d/%m/%Y} · "
                       f"{_i['photos']} photos · un signal = la 1re heure où la condition est "
                       f"remplie, puis 24 h de pause pour l'actif")
            st.markdown(
                "**Comment lire** : pour 🔍 et 🟢 (le sens est inconnu), compare **Ampleur** à "
                "**Ampleur marché** — le signal vaut quelque chose si l'actif bouge plus que le "
                "reste du marché. Pour les autres, compare **Prix** à **Marché** dans le sens "
                "attendu. Peu de cas = à prendre avec des pincettes."
            )
            cc = {"setup": st.column_config.TextColumn("Signal", pinned=True, width="large"),
                  "cas": st.column_config.NumberColumn("Cas"),
                  "actifs": st.column_config.NumberColumn("Actifs")}
            for j in (1, 3, 7):
                cc[f"moy_{j}"] = st.column_config.NumberColumn(
                    f"Prix {j} j", format="%+.2f %%", help="Variation moyenne du prix, avec son signe.")
                cc[f"marche_{j}"] = st.column_config.NumberColumn(
                    f"Marché {j} j", format="%+.2f %%", help="Tous les actifs, au même moment.")
                cc[f"hausse_{j}"] = st.column_config.NumberColumn(f"% hausse {j} j", format="%d %%")
                cc[f"ampleur_{j}"] = st.column_config.NumberColumn(
                    f"Ampleur {j} j", format="%.2f %%", help="Taille du mouvement, quel que soit le sens.")
                cc[f"marche_amp_{j}"] = st.column_config.NumberColumn(
                    f"Ampleur marché {j} j", format="%.2f %%")
                cc[f"n_{j}"] = st.column_config.NumberColumn(f"n {j} j")
            st.dataframe(_r, hide_index=True, width="stretch", column_config=cc)

# ---------------------------------------------------------------------------
# En réel
# ---------------------------------------------------------------------------
with tab_reel:
    st.markdown("**Stratégies de tendance** — depuis le jour où l'actif entre dans la stratégie")
    _rs = J.resultats_strategies()
    if _rs.empty:
        st.info("Pas encore de données : le journal note la phase de chaque actif depuis cette "
                "version. Premiers résultats à 3 jours le surlendemain du premier signal, à 30 "
                "jours au bout d'un mois.")
    else:
        cc = {"strategie": st.column_config.TextColumn("Stratégie", pinned=True),
              "signaux": st.column_config.NumberColumn("Signaux")}
        for n in J.HORIZONS_STRAT_J:
            cc[f"rend_{n}"] = st.column_config.NumberColumn(f"Rend. {n} j", format="%+.2f %%",
                                                            help="Dans le sens du trade : un short dont le prix baisse de 5 % compte +5 %.")
            cc[f"marche_{n}"] = st.column_config.NumberColumn(f"Marché {n} j", format="%+.2f %%",
                                                              help="Le même pari (même sens) sur tous les actifs ce jour-là : la référence à battre.")
            cc[f"gagnants_{n}"] = st.column_config.NumberColumn(f"Gagnants {n} j", format="%d %%")
            cc[f"n_{n}"] = st.column_config.NumberColumn(f"n {n} j")
        st.dataframe(_rs, hide_index=True, width="stretch", column_config=cc)

    st.markdown("**Pastilles du radar** — depuis le changement de pastille")
    _sig = J.resultats_signaux()
    if _sig is None or _sig.empty:
        st.info("Aucun changement de pastille enregistré pour l'instant.")
    else:
        st.dataframe(
            _sig, hide_index=True, width="stretch",
            column_order=["etat", "signaux", "rend_1", "marche_1", "rend_3", "marche_3",
                          "rend_7", "marche_7", "gagnants_7", "n_7"],
            column_config={
                "etat": st.column_config.TextColumn("Pastille", pinned=True),
                **{f"rend_{n}": st.column_config.NumberColumn(f"Rend. {n} j", format="%+.2f %%")
                   for n in J.HORIZONS_J},
                **{f"marche_{n}": st.column_config.NumberColumn(f"Marché {n} j", format="%+.2f %%")
                   for n in J.HORIZONS_J},
                "gagnants_7": st.column_config.NumberColumn("Gagnants 7 j", format="%d %%"),
            },
        )

# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------
with tab_regles:
    s_short, s_long = S.SEUILS["short"], S.SEUILS["long"]
    st.markdown(f"""
#### Tendance longue (condition commune)
Sur 1 an (ou depuis le listing, 160 jours minimum) :
- **Short** : perf négative, au moins **{s_short['pct_cote_min']} %** des jours sous la MM100,
  MM100 qui baisse, pire rebond ≤ **{s_short['rebond_max']:.0f} %**.
- **Long** : perf positive, au moins **{s_long['pct_cote_min']} %** des jours au-dessus de la MM100,
  MM100 qui monte, pire chute ≤ **{s_long['rebond_max']:.0f} %**.

#### Les 4 stratégies
| Stratégie | Entrée |
|---|---|
| 📉 Tendance short | dès que la condition est remplie |
| 🔻 Rebond à shorter | après un rebond (prix au-dessus de la MM{S.MM_COURTE} dans les {S.JOURS_REBOND} jours précédents), le jour où le prix repasse sous la MM{S.MM_COURTE} et où la MM{S.MM_COURTE} baisse |
| 📈 Tendance long | dès que la condition est remplie |
| 🔺 Repli à acheter | miroir du Rebond à shorter, en hausse |

Pour chacune, deux sorties : **MM100** (laisser courir) ou **MM20** (sortir plus vite). Rebond et
Repli ont en plus un stop au-delà de l'extrême des {B.JOURS_STOP} derniers jours.

#### Simulation
Décision à la clôture, exécution à l'ouverture suivante. Une position à la fois par actif, sans
levier. Frais {B.FRAIS_PCT} % + glissement {B.GLISSEMENT_PCT} % par côté. Funding non compté.

#### Verdict
- **✅ Tient** : profit factor ≥ 1,2 en Apprentissage **et** en Test, au moins 30 trades en Test,
  et rendement moyen en Test supérieur à la référence au hasard du même sens.
- **⚠️ À confirmer** : gagnante en Test et meilleure que la référence, mais pas toutes les
  conditions ci-dessus (peu de trades, Apprentissage faible…).
- **❌ Ne marche pas** : profit factor ≤ 1 en Test, ou pas mieux que le hasard.

#### Limites à garder en tête
- L'univers = les actifs encore cotés aujourd'hui : les tokens morts manquent (les longs sont un
  peu flattés, les shorts un peu pénalisés).
- Si tout l'univers a baissé sur la période, n'importe quel short gagne : c'est pour ça que la
  colonne **Réf. même sens** existe.
- Un résultat de backtest n'est qu'une présomption : l'onglet **En réel** confirme ou dément.
""")
