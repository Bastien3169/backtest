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

tab_bt, tab_reel, tab_regles = st.tabs(["🧪 Backtest (passé)", "📒 En réel", "📏 Les règles"])

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
        sens = B.definition(cle)["sens"]
        lignes.append({
            "Stratégie": B.libelle(cle),
            "Sortie": B.SORTIES.get(sortie, {}).get("libelle", "Tenue 20 jours"),
            "Verdict": "— référence" if est_ref else _verdict(app, test, ref.get(sens)),
            "Trades (test)": (test or {}).get("trades"),
            "Gagnants (test)": (test or {}).get("gagnants_pct"),
            "Rend. moyen (test)": (test or {}).get("rend_moy"),
            "Rend. médian (test)": (test or {}).get("rend_med"),
            "Réf. même sens (test)": ref.get(sens),
            "PF apprentissage": (app or {}).get("profit_factor"),
            "PF test": (test or {}).get("profit_factor"),
            "MAE p90": (tout or {}).get("mae_p90"),
            "Levier tenable": (tout or {}).get("levier_tenable"),
            "Durée moy.": (tout or {}).get("jours_moy"),
        })
    df = pd.DataFrame(lignes)
    ordre = {"✅ Tient": 0, "⚠️ À confirmer": 1, "❌ Ne marche pas": 2, "— référence": 3}
    return df.sort_values(["Verdict", "PF test"], key=lambda s: s.map(ordre) if s.name == "Verdict" else -s.fillna(-1))


LECT_VERDICT = {"✅ Tient": "✅ Utilisable", "⚠️ À confirmer": "⚠️ À surveiller",
                "❌ Ne marche pas": "❌ Ne pas utiliser"}


def _synthese(tab: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par stratégie, sa meilleure sortie (choisie sur l'Apprentissage, pas sur le
    Test, sinon le Test ne prouve plus rien). Les deux côtés du filtre de régime restent dans
    le détail : le système complet suffit pour décider."""
    t = tab[tab["Verdict"] != "— référence"].copy()
    t = t[~t["Stratégie"].isin([B.libelle(k) for k in B.REGIMES])]
    t["_o"] = t["Verdict"].map({"✅ Tient": 0, "⚠️ À confirmer": 1, "❌ Ne marche pas": 2})
    t = (t.sort_values(["_o", "PF apprentissage"], ascending=[True, False])
          .drop_duplicates("Stratégie"))
    sortie = t["Sortie"].str.extract(r"(MM\d+)", expand=False)
    utilisable = t["_o"] < 2
    levier = (t["Levier tenable"].fillna(1) / 2).clip(lower=1).astype(int)
    return pd.DataFrame({
        "Stratégie": t["Stratégie"] + sortie.map(lambda s: f" — sortie {s}" if isinstance(s, str) else ""),
        "Verdict": t["Verdict"].map(LECT_VERDICT),
        "Gain moyen par trade": t["Rend. moyen (test)"],
        "Trades": t["Trades (test)"],
        "Levier max": [f"×{l}" if u else "—" for l, u in zip(levier, utilisable)],
    })


def _couleur(v):
    if isinstance(v, str) and v.startswith("✅"):
        return f"color: {VERT}; font-weight: 600"
    if isinstance(v, str) and v.startswith("❌"):
        return f"color: {ROUGE}; font-weight: 600"
    if isinstance(v, str) and (v.startswith("⚠️") or v.startswith("⏳")):
        return f"color: {ORANGE}; font-weight: 600"
    return ""


def _style(df: pd.DataFrame, col: str):
    sty = df.style
    return (getattr(sty, "map", None) or sty.applymap)(_couleur, subset=[col])


with tab_bt:
    zone = st.container()
    with st.expander("🔎 Détails : tableau complet, évolution, trades, actifs écartés"):
        runs = B.charger_runs()
        run = None
        if not runs.empty:
            run = st.selectbox("Lancement", runs["run"].tolist(), index=0,
                               format_func=lambda r: f"{r} ({int(runs.set_index('run').loc[r, 'trades'])} trades)")
            params = json.loads(runs.set_index("run").loc[run, "params"] or "{}")
            resume = B.charger_resume(run)
            tab = _tableau(resume)
            st.caption(
                f"{params.get('actifs', '?')} actifs · depuis {params.get('depuis', '?')} · "
                f"Apprentissage avant le {params.get('coupure_test', '?')}, Test après · "
                f"frais + glissement {2 * (params.get('frais_pct_cote', 0) + params.get('glissement_pct_cote', 0)):.2f} % "
                "par aller-retour · funding non compté · sans levier"
            )
            if "ecartes" not in params:
                st.warning("Lancement antérieur aux garde-fous de données : chiffres faussés, relance.")
            elif params["ecartes"]:
                st.markdown(f"**{len(params['ecartes'])} actifs écartés ou coupés** (données Yahoo)")
                st.write("\n".join(f"- {e}" for e in params["ecartes"]))
            st.markdown("**Tableau complet** (Test = depuis la date de coupure)")
            st.dataframe(_style(tab, "Verdict"), hide_index=True, width="stretch")
            tout = B.charger_resume()
            tout = tout[(tout["periode"] == "Test") & ~tout["strategie"].isin(B.REFERENCES)]
            if tout["run"].nunique() > 1:
                st.markdown("**PF test d'un lancement à l'autre**")
                tout["Stratégie"] = tout["strategie"].map(B.libelle) + " · " + tout["sortie"]
                piv = tout.pivot_table(index="Stratégie", columns="run", values="profit_factor")
                st.dataframe(piv[sorted(piv.columns, reverse=True)[:6]], width="stretch")
            trades = B.charger_trades(run)
            if not trades.empty:
                st.markdown("**Trades**")
                f1, f2 = st.columns(2)
                strat = f1.selectbox("Stratégie", ["Toutes"] + list(S.STRATEGIES) + list(B.COMBINES)
                                     + list(B.REGIMES) + list(B.REFERENCES),
                                     format_func=lambda k: k if k == "Toutes" else B.libelle(k))
                actif = f2.selectbox("Actif", ["Tous"] + sorted(trades["symbol"].unique()))
                t = trades
                if strat in B.COMBINES:
                    t = t[t["strategie"].isin(B.COMBINES[strat]["membres"])]
                elif strat != "Toutes":
                    t = t[t["strategie"] == strat]
                if actif != "Tous":
                    t = t[t["symbol"] == actif]
                t = t.assign(strategie=t["strategie"].map(B.libelle)).sort_values("entree_date", ascending=False)
                st.dataframe(t.drop(columns=["run"]), hide_index=True, width="stretch")

    with zone:
        if st.button("▶️ Lancer un backtest", type="primary",
                     help="Rejoue chaque stratégie depuis 2020 sur tous les actifs. 3 à 6 minutes."):
            barre = st.progress(0.0, text="Démarrage…")
            try:
                r, _ = B.lancer(lambda x, msg: barre.progress(min(max(x, 0.0), 1.0), text=msg))
                barre.progress(1.0, text=f"Terminé : {r}")
                st.rerun()
            except Exception as e:
                st.error(f"Backtest interrompu : {e}")
        if run is None:
            st.info("Aucun backtest enregistré. Clique sur « Lancer un backtest ».")
        else:
            syn = _synthese(tab)
            ok = syn[syn["Verdict"].str.startswith("✅")]["Stratégie"].tolist()
            if ok:
                st.success("**À utiliser :** " + " · ".join(ok))
            else:
                st.warning("**Rien de fiable à trader pour l'instant.**")
            st.dataframe(
                _style(syn, "Verdict"), hide_index=True, width="stretch",
                column_config={
                    "Gain moyen par trade": st.column_config.NumberColumn(
                        format="%+.2f %%", help="Net de frais, sur la période récente (Test)."),
                    "Trades": st.column_config.NumberColumn(
                        help="Sur la période récente. Moins de 30 = trop peu pour être sûr."),
                    "Levier max": st.column_config.TextColumn(
                        help="Moitié du levier qui aurait survécu à 9 trades sur 10. "
                             "Au-delà, un mouvement contraire normal te liquide."),
                },
            )
            st.caption(f"Lancement du {run} · ✅ = gagne sur les deux périodes et mieux que le hasard · "
                       "règles détaillées dans l'onglet « Les règles ».")

# ---------------------------------------------------------------------------
# En réel : journal + signaux OI, en lecture directe
# ---------------------------------------------------------------------------

def _lecture(ecart, n, n_min, seuil, plus, moins):
    if n is None or pd.isna(n) or n < n_min:
        return "⏳ Trop tôt pour juger"
    if ecart is None or pd.isna(ecart) or abs(ecart) < seuil:
        return "➖ Comme le hasard"
    return plus if ecart > 0 else moins


with tab_reel:
    st.caption("Ce qui s'est passé APRÈS chaque signal, en vrai, comparé au reste du marché au "
               "même moment. Écart positif = mieux que le hasard dans le sens du trade.")

    st.markdown("**Stratégies de tendance**")
    _rs = J.resultats_strategies()
    if _rs.empty:
        st.info("Pas encore de données : le journal note la phase de chaque actif depuis cette version.")
    else:
        st.dataframe(_style(pd.DataFrame({
            "Stratégie": _rs["strategie"], "Signaux": _rs["signaux"],
            "Écart vs marché (7 j)": _rs["rend_7"] - _rs["marche_7"],
            "Lecture": [_lecture(r7 - m7, n, 20, 1.0, "✅ Fait mieux que le hasard",
                                 "❌ Fait pire que le hasard")
                        for r7, m7, n in zip(_rs["rend_7"], _rs["marche_7"], _rs["n_7"])],
        }), "Lecture"), hide_index=True, width="stretch",
            column_config={"Écart vs marché (7 j)": st.column_config.NumberColumn(format="%+.2f pts")})

    st.markdown("**Pastilles du radar**")
    _sig = J.resultats_signaux()
    if _sig is None or _sig.empty:
        st.info("Aucun changement de pastille enregistré pour l'instant.")
    else:
        st.dataframe(_style(pd.DataFrame({
            "Pastille": _sig["etat"], "Signaux": _sig["signaux"],
            "Écart vs marché (7 j)": _sig["rend_7"] - _sig["marche_7"],
            "Lecture": [_lecture(r7 - m7, n, 20, 1.0, "✅ Utile", "❌ Fait pire que le hasard")
                        for r7, m7, n in zip(_sig["rend_7"], _sig["marche_7"], _sig["n_7"])],
        }), "Lecture"), hide_index=True, width="stretch",
            column_config={"Écart vs marché (7 j)": st.column_config.NumberColumn(format="%+.2f pts")})

    st.markdown("**Signaux d'open interest** (photos horaires depuis octobre)")
    if st.button("🔬 Analyser les signaux OI", help="Quelques secondes."):
        with st.spinner("Calcul…"):
            st.session_state["_oi_res"] = O.analyser()
    if "_oi_res" in st.session_state:
        _r, _i = st.session_state["_oi_res"]
        if _r.empty or _r["cas"].sum() == 0:
            st.info("Pas assez d'historique continu (7 jours minimum).")
        else:
            _r = _r[~_r["setup"].str.startswith("🎲")]
            sans_sens = _r["setup"].str.contains("prix plat")
            ecart = (_r["ampleur_7"] - _r["marche_amp_7"]).where(sans_sens, _r["moy_7"] - _r["marche_7"])
            lect = [
                _lecture(e, n, 50, 0.5, "✅ Annonce un mouvement plus fort",
                         "❌ Faux signal : bouge moins que le marché") if s else
                _lecture(e, n, 50, 0.5, "🛡️ Résiste mieux : ne pas le shorter",
                         "⚠️ Fait pire : ne pas l'acheter")
                for e, n, s in zip(ecart, _r["n_7"], sans_sens)
            ]
            st.dataframe(_style(pd.DataFrame({
                "Signal": _r["setup"], "Cas": _r["cas"], "Écart vs marché (7 j)": ecart, "Lecture": lect,
            }), "Lecture"), hide_index=True, width="stretch",
                column_config={"Écart vs marché (7 j)": st.column_config.NumberColumn(
                    format="%+.2f pts", help="Prix à 7 j moins le marché au même moment. Pour les "
                                             "signaux « prix plat » (sens inconnu) : taille du mouvement "
                                             "moins celle du marché.")})
            st.caption(f"{_i['actifs']} actifs · du {_i['debut']:%d/%m} au {_i['fin']:%d/%m/%Y} · une "
                       "seule période de marché : une piste, pas une preuve.")
            with st.expander("Détail à 1, 3 et 7 jours"):
                st.dataframe(_r, hide_index=True, width="stretch")

    st.markdown("**Ton setup : compression + z OI fort, dans le sens du BTC**")
    st.caption(f"Alt dont le range s'est resserré par rapport à ses propres habitudes (compression "
               f"< {O.COMPRESSION_MAX:g}) et dont l'OI "
               f"vient de bondir (z OI 24 h ≥ {O.Z_SEUIL:g}). Short si le BTC est sous sa MM20 et sa "
               "MM100, long s'il est au-dessus des deux. Frais déduits. Comparé au même pari pris "
               "sur tous les alts au même moment, c'est-à-dire simplement suivre le BTC.")
    if st.button("🎯 Tester ce setup", help="Quelques secondes (+ l'historique BTC chez Yahoo)."):
        with st.spinner("Calcul…"):
            try:
                st.session_state["_comp_res"] = O.analyser_compression()
            except Exception as e:
                st.error(f"Test impossible : {e}")
    if "_comp_res" in st.session_state:
        _c, _ci = st.session_state["_comp_res"]
        if _c.empty:
            st.info("Pas de données.")
        else:
            def _lect_setup(g, h, n):
                if n is None or n < 30:
                    return "⏳ Trop peu de cas"
                if g > 0 and g > h + 0.5:
                    return "✅ Mieux que suivre le BTC"
                if g < h - 0.5:
                    return "❌ Pire que suivre le BTC"
                return "➖ Pas mieux que suivre le BTC"
            st.dataframe(_style(pd.DataFrame({
                "Setup": _c["setup"], "Cas": _c["cas"],
                "Gagnants (7 j)": _c["gagnants_7"],
                "Gain moyen (7 j)": _c["gain_7"],
                "Suivre le BTC (7 j)": _c["hasard_7"],
                "Lecture": [_lect_setup(g, h, n) for g, h, n in zip(_c["gain_7"], _c["hasard_7"], _c["n_7"])],
            }), "Lecture"), hide_index=True, width="stretch",
                column_config={
                    "Gagnants (7 j)": st.column_config.NumberColumn(format="%.0f %%"),
                    "Gain moyen (7 j)": st.column_config.NumberColumn(
                        format="%+.2f %%", help="Dans le sens du trade, frais déduits, position tenue 7 jours."),
                    "Suivre le BTC (7 j)": st.column_config.NumberColumn(
                        format="%+.2f %%", help="Même sens, sur TOUS les alts au même moment."),
                })
            st.caption(f"Du {_ci['debut']:%d/%m} au {_ci['fin']:%d/%m/%Y} · régime short pendant "
                       f"{_ci['heures_short'] // 24} j, long pendant {_ci['heures_long'] // 24} j · "
                       "les 30 premiers jours servent à calculer la compression.")
            with st.expander("Détail à 1, 3 et 7 jours"):
                st.dataframe(_c, hide_index=True, width="stretch")


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

#### Filtre de régime 🧭
Comme la référence (positions de 20 jours sur tous les actifs, aucun critère sur l'actif), mais
**seulement quand le marché va dans le bon sens** : short si le BTC clôture sous sa
MM{B.MM_REGIME}, long s'il clôture au-dessus. Aucun réglage optimisé : c'est le test de
robustesse — il doit faire mieux que la référence sans filtre **sur les deux périodes**.
Le **système complet** réunit les deux côtés : il est rentable s'il gagne sur les deux périodes,
quel que soit le régime qui domine.

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
