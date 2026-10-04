"""
pages/3_📊_Screening.py
Tableau de screening — choisir les actifs à trader sur Hyperliquid.

Rendu en st.dataframe natif plutôt qu'en lignes st.columns dessinées à la
main : tri par clic sur les colonnes, largeurs ajustables, et la sparkline
rendue par LineChartColumn au lieu d'une figure Plotly par ligne (171 figures
par rerun, c'était le poste le plus lourd de la page).

Radar (octobre 2026) : colonnes de signaux ajoutées au MÊME tableau plutôt
qu'une page séparée — elles se lisent avec la tendance et le risque déjà
présents. Deux vitesses de rafraîchissement :
    🔄 Charger / Actualiser     → tout (Yahoo + Hyperliquid), 2-5 min
    ⚡ Actualiser Hyperliquid   → seulement OI, funding, prix live, états : 2 s
"""

import sys
import os

_HERE = os.path.abspath(__file__)
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from src.utils.market_data import load_screening_data, perf_sur, FENETRE_RISQUE
from src.utils.coins_updater import update_coins
from src.utils.data_loader import get_top100_coins
from src.utils.hl_snapshots import fetch_hl_live, record_snapshot, load_history, INTERVALLE_MIN
from src.utils import radar as R
from src.utils import journal as J

st.set_page_config(page_title="Screening Crypto", page_icon="📊", layout="wide")

st.title("📊 Screening Crypto")
st.caption(
    "Survole le titre d'une colonne pour savoir ce qu'elle mesure et comment la lire. "
    f"Risque et tendance calculés sur les {FENETRE_RISQUE} derniers jours, en dollars."
)

_nb_coins = len(get_top100_coins())

# ---------------------------------------------------------------------------
# Guide de lecture du radar
# ---------------------------------------------------------------------------
with st.expander("📖 Guide du radar — à lire une fois", expanded=False):
    g1, g2, g3, g4, g5 = st.tabs(["Ce que fait le radar", "Les indicateurs",
                                  "Les états", "L'historique", "Météo & journal"])

    with g1:
        st.markdown(
            """
**Le radar repère des anomalies, il ne prédit pas les pumps.**

Sur les ~170 actifs du tableau, la plupart du temps il ne se passe rien de
particulier. Le radar sert à isoler les 5 ou 10 où *quelque chose* bouge
d'inhabituel — de l'argent qui entre, des positions qui s'accumulent, une foule
qui s'emballe — pour que tu ailles regarder leur graphique.

Ce qu'il **ne fait pas** :
- Il ne dit pas *quand* acheter. La plupart des signaux apparaissent **pendant**
  le mouvement, pas avant.
- Il ne dit pas toujours *dans quel sens*. Une accumulation de positions
  annonce un mouvement, pas sa direction.
- Ses seuils n'ont pas encore été backtestés : ils sont raisonnables, pas
  prouvés. Une fois quelques semaines d'historique enregistrées, on pourra
  mesurer ce que chaque état a réellement donné ensuite.

**Les indicateurs ont trois rôles différents**, c'est pour ça qu'ils ne sont
pas additionnés dans une note unique :

| Rôle | Indicateurs | Question posée |
|---|---|---|
| Déclencheur | Variation d'OI, volume relatif | Il se passe quelque chose ? |
| Qualité | Alpha vs BTC, compression | C'est propre à l'actif ? Il était prêt à bouger ? |
| Frein | Funding, OI au plafond | La foule est-elle déjà dedans ? |

Additionner un déclencheur et un frein n'a pas de sens : un funding extrême ne
doit pas *augmenter* une note, il doit allumer un voyant.
"""
        )

    with g2:
        st.markdown(
            """
#### Open interest (OI)
Valeur totale des contrats **encore ouverts** sur le perp Hyperliquid. Chaque
contrat a un long d'un côté et un short de l'autre : l'OI mesure combien
d'argent est *engagé en ce moment*.
Différence avec le volume : quelqu'un qui ouvre et ferme 10 fois dans la
journée fait beaucoup de volume, mais l'OI revient à zéro.

#### Δ OI 4 h / 24 h
Variation de l'OI sur la période, **en nombre de jetons** (BTC, SOL…) et non
en dollars. En dollars, l'OI monterait tout seul avec le prix sans qu'aucune
position nouvelle ne soit ouverte.
- 4 h : la tendance de la séance · 24 h : la base des états.

#### z OI 4 h / 24 h
La même variation, mais **comparée aux habitudes de l'actif** sur les 14
derniers jours. En clair : **combien de fois plus que d'habitude**. Chaque z
est placé juste à côté de son Δ. Seul le z 24 h sert aux états ; le 4 h montre
si le mouvement s'accélère pendant la séance.
`z = (variation actuelle − variation moyenne) / écart-type`
- z = 0 : variation banale pour cet actif.
- z = +2 : une hausse qu'on ne voit qu'environ 1 fois sur 40 sur cet actif.
- Pourquoi : +10 % d'OI sur BTC est énorme, sur un petit perp c'est un mardi.
  Le z-score met tous les actifs sur la même échelle.

#### Δ Prix 24 h
Variation du prix Hyperliquid sur 24 h glissantes, à la seconde. Plus frais
que la colonne « 24 h » de Yahoo, qui part de minuit UTC.

#### Amplit. j. (amplitude quotidienne)
La **taille d'une journée normale** pour l'actif : l'écart habituel entre son
plus haut et son plus bas dans la journée, en % (médiane sur 30 jours).
- C'est une **règle graduée**, pas un mouvement : elle n'a pas de sens (ni
  hausse ni baisse), elle dit seulement « d'habitude, ça bouge de tant ».
- Le radar s'en sert pour juger le Δ Prix 24 h : sur un actif à 4 %, +1 % est
  stable, +2 % est une hausse nette.
- Pour toi : le **stop loss minimum** sur cet actif. Plus serré, il se fait
  toucher par le bruit normal de la journée.

#### Volume relatif
- **Vol. rel.** (Yahoo) : volume de la **dernière journée complète** divisé
  par la moyenne des 30 précédentes. 3,00 × = trois fois l'activité normale.
- **Vol. HL rel.** (live) : volume Hyperliquid des 24 dernières heures divisé
  par sa moyenne sur 14 jours. Disponible après 3 jours d'historique.
- Le volume ne dit **pas** si ce sont des acheteurs ou des vendeurs : chaque
  achat a une vente en face.

#### Alpha 7 j
Ce que l'actif a fait **au-delà de ce que le BTC expliquait**.
`alpha = perf 7 j − β × perf BTC 7 j`
Exemple : BTC +5 %, bêta 2 → +10 % était « attendu ». Un actif à +10 % n'a rien
fait de spécial (alpha 0). Un actif à +16 % a une force propre de +6 points.
Ça élimine la moitié des faux signaux, qui ne sont que « tout le marché monte ».

#### Compression
Amplitude moyenne des 5 dernières journées ÷ amplitude médiane sur 30 jours.
- 1,0 : volatilité normale · 0,6 : les journées ne font plus que 60 % de leur
  range habituel, le marché se resserre.
- Un range qui se resserre pendant que l'OI monte = des positions s'accumulent
  sans que le prix bouge. Souvent le prélude à un gros mouvement.

#### ATR 30 j
Volatilité **moyenne** sur 30 jours, en % du prix (Average True Range).
- Proche de *Amplit. j.*, qui est une **médiane** : la journée « typique ».
- L'ATR est une **moyenne** : les journées extrêmes le tirent vers le haut.
- ATR 6 % et amplitude 4 % : d'habitude l'actif fait 4 %, mais quelques
  journées violentes existent. C'est elles qui sortent ton stop loss.

#### Funding /an
Paiement horaire entre longs et shorts qui maintient le perp collé au prix
spot, ici annualisé.
- Positif : trop de longs, **les longs paient** les shorts.
- Négatif : trop de shorts, les shorts paient les longs.
- C'est à la fois un **coût** (0,01 %/h ≈ 88 %/an) et un **signal de foule** :
  très positif = tout le monde est déjà long, il manque d'acheteurs frais.

#### OI au plafond (pas de colonne : visible dans l'État)
Hyperliquid limite l'OI sur certains actifs. Au plafond, plus personne ne peut
ouvrir de position : engouement extrême, et piège si tu comptais entrer — ton
bot ne pourrait même pas ouvrir. Un actif au plafond passe en 🔴 Surchauffe.
"""
        )

    with g3:
        st.markdown(
            f"""
#### Le principe : croiser le prix et l'OI

| Prix | OI | Lecture |
|---|---|---|
| ↑ | ↑ | Argent frais qui entre en long — hausse plutôt solide |
| ↑ | ↓ | Des shorts ferment ou sont liquidés — hausse rapide mais fragile |
| ↓ | ↑ | Argent frais qui entre en short — baisse avec conviction |
| ↓ | ↓ | Des longs ferment ou sont liquidés — purge, souvent près d'un creux |
| = | ↑↑ | Positions qui s'accumulent sans que le prix bouge — mouvement en préparation |

#### Les états (un seul par actif, dans cet ordre de priorité)

| État | Règle | Exemple | Ce qui se passe | Ce que tu en fais |
|---|---|---|---|---|
| {R.ETATS['surchauffe']} | OI au plafond d'Hyperliquid **ou** funding ≥ {R.FUNDING_SURCHAUFFE:.0f} %/an | — | Tout le monde est déjà long, et paie cher pour le rester. Il ne reste presque plus d'acheteurs pour pousser plus haut. | Pas de nouveau long. Le risque est une cascade de liquidations à la baisse. |
| {R.ETATS['squeeze']} | Prix en hausse nette, mais OI en forte baisse | Prix +6 %, OI −20 %. | Le prix monte alors que les positions **ferment**. Ce sont des shorts qui se font liquider ou qui rachètent en panique. Leurs rachats forcés font monter le prix, d'où d'autres liquidations : c'est l'effet domino. **Le piège :** la hausse est spectaculaire mais sans carburant. Une fois les shorts sortis, plus personne n'achète, et le prix retombe souvent. | Ne pas courir derrière en long. Au mieux, attendre la fin du squeeze. |
| {R.ETATS['demarrage']} | OI en forte hausse, alpha 7 j positif, et soit prix en hausse nette, soit prix en hausse modérée avec un volume ≥ {R.VOL_REL_DEMARRAGE} × la normale | Prix +5 %, OI +20 %, volume 2× la normale, et l'actif fait mieux que ce que BTC expliquait. | De l'**argent frais** entre en long. La hausse ne vient pas de shorts qui ferment, elle vient de vrais acheteurs nouveaux, et elle est propre à l'actif, pas un simple suivi du marché. | C'est le meilleur candidat pour ton bot long. Regarde quand même le graphique et la colonne Position 30 j, pour ne pas entrer sur un sommet. |
| {R.ETATS['accumulation']} | Prix stable, OI en forte hausse, journées de plus en plus calmes (compression ≤ {R.COMPRESSION_SEUIL}) | Prix +0,3 % sur 24 h, mais OI +25 %, et la compression à 0,7. | Beaucoup de gens ouvrent des positions, longs et shorts, sans que le prix bouge. Ils se placent et attendent. C'est un ressort qu'on comprime : plus il y a de positions engagées, plus le mouvement sera violent quand il partira, parce que les perdants seront forcés de fermer et accéléreront le mouvement. **Le piège :** on ne sait pas dans quel sens ça part. | Une liste de surveillance. Tu attends que le prix choisisse sa direction, et c'est souvent là qu'il passe en 🔵 ou en 🟣. |
| {R.ETATS['shorts']} | OI en forte hausse, et soit prix en baisse nette, soit prix en baisse modérée avec un volume ≥ {R.VOL_REL_DEMARRAGE} × la normale | Prix −5 %, OI +20 %. | De nouveaux vendeurs ouvrent des shorts avec conviction. La baisse est alimentée par de l'argent frais, c'est le miroir exact du 🔵 Démarrage. | C'est le meilleur candidat pour ton bot short. |
| {R.ETATS['purge']} | Prix en baisse nette, OI en forte baisse | Prix −6 %, OI −20 %. | Des longs se font liquider ou abandonnent. Le marché se vide de ses acheteurs fragiles. C'est le miroir du 🟠 Squeeze. | Ne pas shorter, c'est trop tard, le gros de la baisse est fait. Une purge finit souvent près d'un creux : à surveiller pour un futur long, une fois que ça se stabilise. |
| {R.ETATS['attente']} | Pas encore 24 h de photos | — | Le radar n'a pas encore de photo d'il y a 24 h pour mesurer la variation d'OI. | Patience : voir l'onglet « L'historique ». |
| {R.ETATS['calme']} | Aucune règle ne s'applique | — | Ne veut PAS dire que l'actif est calme : il peut bouger beaucoup (regarde Compress. et Vol. rel.) sans que prix et OI racontent une histoire claire. | Rien à faire sur la base du radar. |

*Exemples donnés pour un actif qui bouge habituellement de 4 % par jour.*

#### Que veut dire « net » ?
- **Prix** : comparé à la colonne *Amplit. j.* (la taille d'une journée
  normale). Net = au moins {R.PRIX_FORT} × cette amplitude ; stable = au plus
  {R.PRIX_STABLE} × ; entre les deux = **modéré** (compte pour 🔵 et 🟣
  seulement si le volume confirme). Sur un actif à 4 % : net dès ±2 %,
  modéré entre ±1 et ±2 %, stable sous ±1 %. Un actif qui fait 8 % par jour n'est pas « en
  hausse » à +3 %.
- **OI** : |z| ≥ {R.Z_SEUIL} dès que le z-score existe. Avant ça, seuil
  provisoire de ±{R.OI_SEUIL_PROVISOIRE:.0f} % sur 24 h, identique pour tous
  les actifs — donc moins fiable.
"""
        )

    with g4:
        st.markdown(
            f"""
#### Pourquoi un historique ?
L'API Hyperliquid donne l'OI **instantané** et rien d'autre : aucun moyen de
demander « l'OI d'hier ». Pour calculer une variation, l'app prend donc une
**photo de tout l'univers toutes les {INTERVALLE_MIN} min** et la garde.
Une par heure suffit : le bot décide à la bougie journalière.

#### Où sont les photos ?
Dans la **même base que les comptes utilisateurs** (table `hl_snapshots`) :
PostgreSQL sur Railway, SQLite en local. Pas de fichier JSON : le disque d'un
conteneur Railway est effacé à chaque redéploiement, et un JSON réécrit
toutes les heures grossit sans fin. Les photos de plus de 30 jours sont
supprimées automatiquement (≈ 145 000 lignes au maximum, une vingtaine de Mo).

#### Qui prend les photos ?
Un enregistreur qui tourne en arrière-plan de l'app Streamlit. Après un
redéploiement Railway, il redémarre à la première visite de l'app. Chaque
clic sur un bouton d'actualisation de cette page prend aussi une photo si la
dernière date de plus de {INTERVALLE_MIN} min.

#### Quand chaque colonne devient disponible
| Après | Colonnes |
|---|---|
| 4 h | Δ OI 4 h |
| 24 h | Δ OI 24 h, et donc les états |
| 3 jours | Vol. HL rel. |
| ~5 jours | z OI 24 h — les états passent du seuil provisoire au seuil propre à chaque actif |
| quelques semaines | assez de recul pour **backtester** les états |
"""
        )

    with g5:
        st.markdown(
            f"""
#### La météo du marché (bandeau au-dessus du tableau)
À lire **avant** les signaux individuels : un 🔵 Démarrage isolé dans un
marché qui purge échoue beaucoup plus souvent.
- **BTC vs sa moyenne {R.METEO_MM} j, et la pente de cette moyenne** : au-dessus
  d'une moyenne plate ou montante = la marée monte. Au-dessus d'une moyenne qui
  baisse encore = simple rebond dans un marché baissier, pas un beau temps.
- **Largeur** : % des actifs du tableau au-dessus de leur propre moyenne {R.METEO_MM} j.
  70 % = presque tout le marché monte ; 25 % = presque tout baisse.
- **États** : nombre d'actifs en 🔵/🟢 (haussiers) contre 🟣/⚫ (baissiers).

| Verdict | Règle |
|---|---|
| {R.METEO_PORTEUR} | BTC au-dessus de sa MM{R.METEO_MM}, MM plate ou montante, **et** largeur ≥ {R.LARGEUR_HAUTE:.0f} % |
| {R.METEO_CONTRAIRE} | BTC en dessous de sa MM{R.METEO_MM}, MM qui baisse, **et** largeur ≤ {R.LARGEUR_BASSE:.0f} % |
| {R.METEO_NEUTRE} | Tout le reste |

« Plate ou montante » : la MM{R.METEO_MM} d'aujourd'hui n'a pas perdu plus de
{abs(R.PENTE_SEUIL):.1f} % par rapport à celle d'il y a {R.PENTE_RECUL} jours.

**Pourquoi la MM{R.METEO_MM} et pas la MM30 :** backtest sur BTC 2015-2026 d'un
filtre « long seulement par vent porteur » (partie BTC de la règle) : MM50 +
pente → +72 %/an, pire baisse −52 %, 14 changements de météo par an ; MM30 +
pente → +67 %/an, pire baisse −58 %, 25 changements par an ; BTC acheté et
gardé → +61 %/an, pire baisse −83 %. La MM50 fait un peu mieux et change
deux fois moins souvent d'avis.

#### Le journal des états
Chaque jour entre 00:05 et 04:00 UTC — juste après la clôture de la bougie
journalière, quand ton bot décide — l'app note l'état et le prix de chaque
actif (table `hl_etats`, conservée sans limite). Les jours suivants, elle
compare les prix.

Le tableau « 📒 Journal des états » en bas de la page répond alors à la seule
question qui compte : **quand un actif était en 🔵 Démarrage, qu'a fait son
prix 1, 3 et 7 jours plus tard — et est-ce mieux que la moyenne du marché ?**

- La première ligne, **Tous les actifs**, est la référence à battre. Si les
  🔵 font +1 % à 3 jours mais que le marché entier a fait +1,5 %, le signal
  ne vaut rien.
- **Ampleur** : taille moyenne du mouvement, quel que soit son sens. C'est la
  bonne mesure pour 🟢 Accumulation, dont on attend un mouvement fort mais de
  sens inconnu.
- **% hausse** : part des cas où le prix a monté. Pour 🟣 et ⚫, un bon signal
  short est un % de hausse BAS.
- Moins de ~30 cas sur une ligne = pas encore significatif, n'en tire rien.
- Le journal ne note rien en dehors de la fenêtre 00:05-04:00 UTC : un état
  noté à 15 h ne serait pas comparable aux autres.

#### Les alertes e-mail
- **La lettre du jour** : juste après que le journal a noté les états :
  🚀 les actifs **passés** en 🔵 ou 🟣 aujourd'hui, ⏩ ceux toujours en cours
  avec leur rendement depuis le changement de pastille, 🔭 les 🟢 classés du
  ressort le plus tendu au moins tendu. Pas d'e-mail les jours sans 🔵, 🟣 ni 🟢.
- **Le lundi** : la lettre ajoute le bilan de la semaine (rendement de chaque
  signal 🔵/🟣 des 7 derniers jours) et le bilan cumulé depuis le début.
- **Nouvel inscrit** : un e-mail dès qu'un compte attend ta validation.
- Envoi via Resend (variable `RESEND_API_KEY` sur Railway) : Railway bloque
  l'envoi direct par Gmail.
"""
        )

# ---------------------------------------------------------------------------
# Mise à jour de la liste des actifs
# ---------------------------------------------------------------------------
with st.expander("🔁 Mettre à jour la liste des actifs (univers Hyperliquid)", expanded=False):
    st.markdown(
        f"Liste actuelle : **{_nb_coins} actifs**, tradables sur Hyperliquid "
        "**et** historisés sur Yahoo Finance.  \n"
        "Ce bouton lit l'univers des perps Hyperliquid, résout le ticker Yahoo de "
        "chacun — y compris les tickers suffixés type `HYPE32196-USD` — et ne garde "
        "que ceux qui ont un historique exploitable.  \n"
        "CoinGecko n'est plus utilisé que pour les noms lisibles.  \n"
        "⏱ Durée estimée : **5-10 minutes** (l'univers HL compte ~200 actifs)."
    )
    if st.button("🚀 Lancer la mise à jour", type="primary", key="update_coins"):
        prog = st.progress(0, text="Lecture de l'univers Hyperliquid...")
        try:
            available, skipped = update_coins(
                progress_cb=lambda p, m: prog.progress(p, text=m)
            )
            prog.empty()
            st.success(f"✅ {len(available)} actifs retenus (Hyperliquid ∩ Yahoo Finance)")
            if skipped:
                st.warning(
                    f"⚠️ {len(skipped)} actifs HL sans historique Yahoo, donc non "
                    f"backtestables : {', '.join(skipped)}"
                )
            st.info("✅ La liste est mise à jour — active au prochain chargement de données.")
        except Exception as e:
            prog.empty()
            st.error(f"❌ Erreur : {e}")

# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
for _cle in ("screening_df", "radar_live", "radar_hist"):
    if _cle not in st.session_state:
        st.session_state[_cle] = None


def _actualiser_hl():
    """Photo HL instantanée + enregistrement + relecture de l'historique : ~2 s."""
    live = fetch_hl_live()
    if live is not None and not live.empty:
        record_snapshot(live)
    st.session_state.radar_live = live
    st.session_state.radar_hist = load_history(jours=R.Z_FENETRE_JOURS + 1)


_b1, _b2, _ = st.columns([1.2, 1.4, 3])
with _b1:
    _tout = st.button("🔄 Charger / Actualiser", type="primary",
                      help="Recharge tout : prix Yahoo (2-5 min) puis contexte Hyperliquid.")
with _b2:
    _hl = st.button("⚡ Actualiser Hyperliquid", disabled=st.session_state.screening_df is None,
                    help="Ne recharge que l'OI, le funding, le prix live et les états (~2 s). "
                         "Les colonnes Yahoo (perfs, bêta, amplitude…) ne bougent pas.")

if _tout:
    progress = st.progress(0, text="Initialisation...")
    st.session_state.screening_df = load_screening_data(
        progress_cb=lambda p, m: progress.progress(p, text=m)
    )
    progress.text("Contexte Hyperliquid et historique d'OI...")
    _actualiser_hl()
    progress.empty()
    st.success(f"✅ {len(st.session_state.screening_df)} actifs chargés")
elif _hl:
    with st.spinner("Lecture d'Hyperliquid..."):
        _actualiser_hl()

df = st.session_state.screening_df
if df is None or df.empty:
    st.info("Cliquez sur **Charger / Actualiser** pour afficher le tableau.")
    st.stop()

_ecartes = df.attrs.get("ecartes") or []
if _ecartes:
    st.warning(
        f"⚠️ {len(_ecartes)} actifs écartés — série de prix figée ou absente chez "
        f"Yahoo, donc chiffres non exploitables : {', '.join(_ecartes)}"
    )

# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------
df = R.compute_radar(df, st.session_state.radar_live,
                     st.session_state.radar_hist if st.session_state.radar_hist is not None
                     else pd.DataFrame(columns=["ts", "coin", "oi", "mark_px", "day_ntl_vlm"]))

if not df.attrs.get("radar_ok"):
    st.info(
        "ℹ️ Hyperliquid n'a pas répondu : funding, open interest, colonnes radar et "
        "états sont vides. Le reste du tableau est valide — réessaie avec "
        "**⚡ Actualiser Hyperliquid**."
    )
else:
    _h = df.attrs.get("historique", {})
    _ts = df.attrs.get("radar_ts")
    _jours = _h.get("jours", 0)
    if _jours < 1:
        _etape = "les états apparaîtront après 24 h d'enregistrement"
    elif not df.attrs.get("z_actif"):
        _etape = (f"z-score dans ~{max(0.0, 5 - _jours):.0f} j — en attendant, seuil "
                  f"provisoire de ±{R.OI_SEUIL_PROVISOIRE:.0f} % d'OI pour tous les actifs")
        _etape = _etape.replace("~0 j", "quelques heures")
    else:
        _etape = "z-score actif — seuils propres à chaque actif"
    _jours_txt = f"{_jours:.1f}".replace(".", ",")
    st.caption(
        f"🛰 Hyperliquid lu à {_ts:%H:%M} UTC · historique d'OI : **{_h.get('photos', 0)} "
        f"photos sur {_jours_txt} j** · {_etape}"
        + ("" if df.attrs.get("plafond_ok") else " · ⚠️ liste des OI au plafond indisponible")
    )

# ---------------------------------------------------------------------------
# Météo du marché
# ---------------------------------------------------------------------------
_m = R.meteo_marche(df)
with st.container(border=True):
    _w1, _w2, _w3, _w4 = st.columns([1.3, 1, 1, 1])
    _w1.metric("Météo du marché", _m["verdict"],
               help="Voir l'onglet « Météo & journal » du guide pour les règles.")
    _btc_txt = {True: "au-dessus", False: "en dessous", None: "—"}[_m["btc_dessus"]]
    if _m["btc_pente"] is not None:
        _btc_txt += (" · ↘ MM qui baisse" if _m["btc_pente"] < R.PENTE_SEUIL
                     else " · ↗ MM plate/montante")
    _w2.metric(f"BTC vs moyenne {R.METEO_MM} j", _btc_txt,
               delta=(f"{_m['btc_perf_7d']:+.1f} % sur 7 j".replace(".", ",")
                      if isinstance(_m["btc_perf_7d"], (int, float)) else None),
               help=f"Prix de BTC vs sa moyenne des {R.METEO_MM} dernières clôtures, et "
                    f"pente de cette moyenne sur {R.PENTE_RECUL} jours. Au-dessus d'une "
                    "moyenne qui monte = la marée monte. Au-dessus d'une moyenne qui "
                    "baisse encore = simple rebond dans un marché baissier.")
    _w3.metric("Largeur", f"{_m['largeur']:.0f} %" if _m["largeur"] is not None else "—",
               help=f"% des actifs du tableau au-dessus de leur propre moyenne {R.METEO_MM} j. "
                    f"≥ {R.LARGEUR_HAUTE:.0f} % = marché large en hausse ; "
                    f"≤ {R.LARGEUR_BASSE:.0f} % = marché large en baisse.")
    _w4.metric("États 🔵🟢 / 🟣⚫", f"{_m['haussiers']} / {_m['baissiers']}",
               help="Nombre d'actifs en Démarrage ou Accumulation contre Shorts en "
                    "force ou Purge. Vide tant que l'historique d'OI n'a pas 24 h.")

# ---------------------------------------------------------------------------
# Perf sur N jours, recalculée à la volée depuis les clôtures déjà chargées
# ---------------------------------------------------------------------------
_cp1, _cp2 = st.columns([1, 3])
with _cp1:
    _n_jours = st.number_input(
        "Colonne perf. personnalisée (jours)", min_value=1, max_value=89, value=14, step=1,
        help="Ajoute une colonne de performance sur la durée de ton choix. "
             "Calculée depuis les clôtures déjà en mémoire — aucun rechargement.",
    )
with _cp2:
    _vue = st.radio(
        "Colonnes affichées", ["Radar", "Tout", "Tendance & risque"], horizontal=True,
        key="scr_vue",
        help="Radar : les signaux de flux (OI, volume, funding, état) — par défaut. "
             "Tout : toutes les colonnes. "
             "Tendance & risque : le screening d'origine, sans le radar.",
    )
df["perf_custom"] = df["closes"].apply(lambda c: perf_sur(pd.Series(c), int(_n_jours)))

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
PRESETS = {
    "Aucun": {},
    "Momentum liquide": {
        "perf_7d_min": 5.0, "amplitude_min": 3.0, "volume_min": 5.0,
        "position_min": 60, "funding_max": 40.0,
    },
    "Calme et profond": {
        "perf_7d_min": -100.0, "amplitude_min": 0.0, "volume_min": 50.0,
        "position_min": 0, "funding_max": 20.0,
    },
    "Signaux radar": {
        "etats": [R.ETATS[k] for k in ("demarrage", "accumulation", "squeeze", "shorts")],
    },
}

with st.expander("🔧 Filtres", expanded=True):
    _preset = st.radio("Préréglage", list(PRESETS), horizontal=True, key="scr_preset")
    _p = PRESETS[_preset]

    f1, f2, f3 = st.columns(3)
    with f1:
        perf_min = st.number_input(
            "Perf. 7 j minimum (%)", value=float(_p.get("perf_7d_min", -100.0)), step=1.0,
            key=f"scr_perf_{_preset}",
        )
        amplitude_min = st.number_input(
            "Amplitude quotidienne minimum (%)", 0.0, 30.0,
            float(_p.get("amplitude_min", 0.0)), 0.5, key=f"scr_ampl_{_preset}",
        )
    with f2:
        volume_min = st.number_input(
            "Volume 24 h minimum (M$)", 0.0, 5000.0,
            float(_p.get("volume_min", 0.0)), 1.0, key=f"scr_vol_{_preset}",
        )
        position_min = st.slider(
            "Position minimum dans le range 30 j", 0, 100,
            int(_p.get("position_min", 0)), key=f"scr_pos_{_preset}",
        )
    with f3:
        funding_max = st.number_input(
            "Funding annualisé maximum (%)", 0.0, 500.0,
            float(_p.get("funding_max", 500.0)), 5.0, key=f"scr_fund_{_preset}",
            help="Coût annualisé de porter un LONG. Au-delà de ~50 %, le portage "
                 "mange une grande partie du mouvement attendu.",
        )
        etats_choisis = st.multiselect(
            "États radar", list(R.ETATS.values()), default=_p.get("etats", []),
            key=f"scr_etats_{_preset}",
            help="Vide = tous les états. Voir l'onglet « Les états » du guide.",
        )

# Un filtre ne doit jamais écarter une ligne parce que la donnée est absente :
# fillna avec la valeur qui laisse passer.
masque = (
    (df["perf_7d"].fillna(-1e9)       >= perf_min) &
    (df["amplitude_med"].fillna(1e9)  >= amplitude_min) &
    (df["volume_24h"].fillna(1e18)    >= volume_min * 1e6) &
    (df["position_range"].fillna(100) >= position_min) &
    (df["funding_annuel"].fillna(0).abs() <= funding_max)
)
if etats_choisis:
    masque &= df["etat"].isin(etats_choisis)
df_filtre = df[masque].copy()

if df_filtre.empty:
    st.warning("Aucun actif ne passe ces filtres. Assouplis un critère.")
    st.stop()

if _vue == "Radar":
    # Les états les plus « actifs » d'abord, puis la plus forte variation d'OI
    df_filtre["_ordre"] = df_filtre["etat"].map(R.ORDRE_ETATS).fillna(99)
    df_filtre["_force"] = df_filtre["oi_z"].abs().fillna(df_filtre["oi_chg_24h"].abs() / 10)
    df_filtre = df_filtre.sort_values(["_ordre", "_force"], ascending=[True, False],
                                      na_position="last")
else:
    df_filtre = df_filtre.sort_values("perf_7d", ascending=False, na_position="last")
df_filtre["volume_m"]    = df_filtre["volume_24h"] / 1e6
df_filtre["oi_m"]        = df_filtre["open_interest"] / 1e6
df_filtre["volume_hl_m"] = df_filtre["volume_hl_24h"] / 1e6

# ---------------------------------------------------------------------------
# Tableau
# ---------------------------------------------------------------------------
COLONNES = {
    "symbol": st.column_config.TextColumn(
        "Actif", width="small", pinned=True,
        help="Symbole. Seuls les actifs tradables sur Hyperliquid ET historisés "
             "sur Yahoo Finance sont listés — donc tous backtestables.",
    ),
    "etat": st.column_config.TextColumn(
        "État", width="medium", pinned=True,
        help="Lecture combinée prix × OI × volume × funding. Règles détaillées "
             "dans le guide, onglet « Les états ». Un repérage, pas un signal "
             "d'achat : les seuils ne sont pas encore backtestés.",
    ),
    "name": st.column_config.TextColumn(
        "Nom", width="small",
        help="Nom lisible du token, tel que renvoyé par CoinGecko lors de la "
             "dernière mise à jour de la liste.",
    ),
    "closes": st.column_config.LineChartColumn(
        "90 j", width="small", color="auto",
        help="Clôtures des 90 derniers jours. Vert si la série monte sur la "
             "fenêtre affichée, rouge si elle descend — la couleur décrit donc "
             "la tendance 90 jours, pas la perf 7 j. La FORME est lisible, pas "
             "l'échelle : chaque tracé est normalisé sur son propre range.",
    ),
    "px_chg_24h": st.column_config.NumberColumn(
        "Δ Prix 24 h", format="%+.2f %%",
        help="Variation du prix Hyperliquid sur 24 h GLISSANTES, à l'instant de "
             "la dernière actualisation HL. Plus fraîche que « 24 h » (Yahoo, "
             "depuis minuit UTC).",
    ),
    "amplitude_med": st.column_config.NumberColumn(
        "Amplit. j. (médiane)", format="%.2f %%",
        help="Amplitude quotidienne médiane : (haut − bas) / clôture, sur 30 "
             "journées complètes. C'est le PLANCHER de stop loss exploitable. Un "
             "SL plus serré que cette valeur se fait toucher par le bruit "
             "ordinaire de la journée. Sert aussi d'étalon au radar : un « net » "
             "mouvement de prix = au moins la moitié de cette amplitude.",
    ),
    "atr_pct": st.column_config.NumberColumn(
        "ATR 30 j (moyenne)", format="%.2f %%",
        help="Volatilité MOYENNE sur 30 journées complètes, en % du prix (Average "
             "True Range, moyenne simple). Comme l'amplitude, mais en moyenne au "
             "lieu de la médiane, et en comptant les écarts d'ouverture. ATR bien "
             "au-dessus de Amplit. j. = quelques journées violentes gonflent le "
             "risque réel : prévoir un SL plus large ou une taille plus petite.",
    ),
    "compression": st.column_config.NumberColumn(
        "Compress.", format="%.2f",
        help="Amplitude moyenne des 5 dernières journées ÷ amplitude médiane 30 j. "
             "1,00 = volatilité normale ; 0,60 = le range s'est resserré à 60 % "
             "de l'habitude. Compression + OI qui monte = mouvement en préparation, "
             "sens inconnu.",
    ),
    "perf_7d": st.column_config.NumberColumn(
        "7 j", format="%+.2f %%", help="Variation sur 7 jours.",
    ),
    "perf_custom": st.column_config.NumberColumn(
        f"{int(_n_jours)} j", format="%+.2f %%",
        help="Perf sur la durée choisie au-dessus du tableau.",
    ),
    "perf_30d": st.column_config.NumberColumn(
        "30 j", format="%+.2f %%",
        help="Variation sur 30 jours. Comparée à la perf 7 j, elle dit si le "
             "mouvement démarre ou s'il s'essouffle.",
    ),
    "alpha_7d": st.column_config.NumberColumn(
        "Alpha 7 j", format="%+.2f pts",
        help="Perf 7 j MOINS ce que le BTC expliquait (β × perf BTC 7 j). "
             "Positif = l'actif a une force propre ; ≈ 0 = il a juste suivi le "
             "marché. BTC +5 %, β 2, actif +16 % → alpha +6 pts.",
    ),
    "position_range": st.column_config.ProgressColumn(
        "Position 30 j", min_value=0, max_value=100, format="%.0f",
        help="Où se situe le prix entre son plus bas et son plus haut des 30 "
             "derniers jours. 100 = sur ses sommets, tendance intacte. 40 = le "
             "mouvement a déjà rendu la moitié du terrain, même si la perf 7 j "
             "est belle.",
    ),
    "beta": st.column_config.NumberColumn(
        "β vs BTC", format="%.2f",
        help="Amplitude relative : quand le BTC bouge de 1 %, l'actif bouge de β %. "
             "β = 2 amplifie le double, dans les deux sens.",
    ),
    "corr_btc": st.column_config.ProgressColumn(
        "Corr. BTC", min_value=0, max_value=100, format="%.0f %%",
        help="À quel point l'actif bouge EN MÊME TEMPS que le BTC. 100 % = ils "
             "montent et descendent ensemble, 50 % = aucun lien. Dit le SENS "
             "commun, pas l'amplitude — c'est le rôle du bêta.",
    ),
    "volume_m": st.column_config.NumberColumn(
        "Vol. veille", format="%.1f M$",
        help="Volume échangé sur la dernière journée COMPLÈTE (source Yahoo).",
    ),
    "volume_rel": st.column_config.NumberColumn(
        "Vol. rel.", format="%.2f ×",
        help="Volume de la dernière journée complète ÷ moyenne des 30 précédentes. "
             "3,00 × = trois fois l'activité habituelle. La journée en cours est "
             "exclue : quelques heures de volume face à des journées entières "
             "donneraient un chiffre faussement bas.",
    ),
    "vol_hl_rel": st.column_config.NumberColumn(
        "Vol. HL rel.", format="%.2f ×",
        help="Volume Hyperliquid des 24 DERNIÈRES HEURES ÷ sa moyenne sur 14 jours. "
             "La version live du volume relatif. Disponible après 3 jours "
             "d'historique.",
    ),
    "volume_hl_m": st.column_config.NumberColumn(
        "Vol. HL", format="%.1f M$",
        help="Volume notionnel 24 h sur Hyperliquid — le marché où tes ordres "
             "partent réellement. C'est lui qui détermine ton slippage.",
    ),
    "oi_m": st.column_config.NumberColumn(
        "Open int.", format="%.1f M$",
        help="Valeur des positions ouvertes sur le perp HL. Mesure la profondeur "
             "réelle du marché, mieux que le market cap du token.",
    ),
    "oi_chg_4h": st.column_config.NumberColumn(
        "Δ OI 4 h", format="%+.1f %%",
        help="Variation de l'OI sur 4 h, en nombre de jetons. La tendance de la séance.",
    ),
    "oi_z_4h": st.column_config.NumberColumn(
        "z OI 4 h", format="%+.1f",
        help="Δ OI 4 h comparé aux habitudes de CET actif : combien de fois plus "
             "que d'habitude. |z| ≥ 2 = inhabituel. Disponible après ~5 jours "
             "d'historique.",
    ),
    "oi_chg_24h": st.column_config.NumberColumn(
        "Δ OI 24 h", format="%+.1f %%",
        help="Variation de l'OI sur 24 h, en nombre de jetons. Base des états. "
             "À lire avec le prix : prix ↑ + OI ↑ = argent frais ; prix ↑ + OI ↓ "
             "= shorts qui sortent.",
    ),
    "oi_z": st.column_config.NumberColumn(
        "z OI 24 h", format="%+.1f",
        help="Variation d'OI 24 h comparée aux habitudes de CET actif (14 jours). "
             "|z| ≥ 2 = inhabituel (~1 fois sur 40). Met BTC et un petit perp sur "
             "la même échelle. Disponible après ~5 jours d'historique.",
    ),
    "funding_annuel": st.column_config.NumberColumn(
        "Funding /an", format="%+.1f %%",
        help="Coût annualisé de porter un LONG (un SHORT l'encaisse). Positif "
             "et élevé = tout le monde est déjà long, et tu paies pour les "
             f"rejoindre. ≥ {R.FUNDING_SURCHAUFFE:.0f} %/an → état Surchauffe.",
    ),
}

VUES = {
    "Radar": ["symbol", "etat", "closes", "px_chg_24h", "amplitude_med", "atr_pct",
              "compression", "alpha_7d", "volume_rel", "vol_hl_rel", "oi_chg_4h", "oi_z_4h", "oi_chg_24h", "oi_z",
              "funding_annuel", "oi_m"],
    "Tendance & risque": ["symbol", "name", "closes", "perf_7d",
                          "perf_custom", "perf_30d", "position_range", "amplitude_med", "atr_pct", "beta",
                          "corr_btc", "volume_m", "volume_rel", "volume_hl_m", "oi_m", "funding_annuel"],
}
VUES["Tout"] = list(COLONNES)
_cols = VUES[_vue]

# Un tableau chargé avant une mise à jour du code n'a pas les nouvelles
# colonnes : on les affiche vides plutôt que de planter (cliquer sur
# Charger / Actualiser les remplit).
for _c in _cols:
    if _c not in df_filtre.columns:
        df_filtre[_c] = None
_affiche = df_filtre[_cols].copy()
_affiche.attrs = {}      # métadonnées internes, non sérialisables par Streamlit
st.dataframe(
    _affiche,
    column_config={k: v for k, v in COLONNES.items() if k in _cols},
    hide_index=True,
    width="stretch",
    height=min(720, 40 * len(df_filtre) + 45),
)

_compte = df["etat"].value_counts()
st.caption(
    f"{len(df_filtre)} actifs affichés sur {len(df)} chargés · "
    + " · ".join(f"{e} : {_compte[e]}" for e in R.ETATS.values()
                 if e in _compte and e not in (R.ETATS["calme"], R.ETATS["attente"]))
    + " · Clique sur un en-tête pour trier · Prix : yfinance (bougies journalières) · "
    "OI, funding, prix live : Hyperliquid"
)

# ---------------------------------------------------------------------------
# Journal des états — est-ce que le radar marche ?
# ---------------------------------------------------------------------------
with st.expander("📒 Journal des états — est-ce que le radar marche ?", expanded=False):
    _res, _info = J.resultats()
    if _res.empty:
        st.info(
            "Le journal est vide pour l'instant. Il note l'état de chaque actif une fois "
            "par jour entre 00:05 et 04:00 UTC (sur Railway, l'app doit tourner). Les "
            "premiers résultats à 1 jour apparaîtront le surlendemain, ceux à 7 jours "
            "après une semaine et demie. Explications : onglet « Météo & journal » du guide."
        )
    else:
        st.markdown("**Depuis le changement de pastille** — la mesure qui compte pour trader")
        st.caption(
            "Un signal = le jour où l'actif PASSE en 🔵, 🟣 ou 🟢 (pas chaque jour où il y "
            "reste). Rendement dans le sens du trade : un 🟣 dont le prix baisse de 5 % "
            "compte +5 %. Pour 🟢 : ampleur du mouvement, quel que soit le sens. "
            "« Marché » = la même mesure sur tous les actifs, le même jour : la référence "
            "à battre."
        )
        _sig = J.resultats_signaux()
        if _sig.empty:
            st.info("Aucun changement de pastille enregistré pour l'instant.")
        else:
            st.dataframe(
                _sig, hide_index=True, width="stretch",
                column_order=["etat", "signaux", "rend_1", "marche_1", "rend_3", "marche_3",
                              "rend_7", "marche_7", "gagnants_7", "n_7"],
                column_config={
                    "etat": st.column_config.TextColumn("Pastille", pinned=True),
                    "signaux": st.column_config.NumberColumn("Signaux"),
                    "rend_1": st.column_config.NumberColumn("Rend. 1 j", format="%+.2f %%"),
                    "marche_1": st.column_config.NumberColumn("Marché 1 j", format="%+.2f %%"),
                    "rend_3": st.column_config.NumberColumn("Rend. 3 j", format="%+.2f %%"),
                    "marche_3": st.column_config.NumberColumn("Marché 3 j", format="%+.2f %%"),
                    "rend_7": st.column_config.NumberColumn("Rend. 7 j", format="%+.2f %%"),
                    "marche_7": st.column_config.NumberColumn("Marché 7 j", format="%+.2f %%"),
                    "gagnants_7": st.column_config.NumberColumn("Gagnants 7 j", format="%d %%"),
                    "n_7": st.column_config.NumberColumn("Mesurés à 7 j"),
                },
            )
        st.markdown("**Jour par jour** — tous les jours passés dans chaque état")
        st.caption(
            f"{_info['jours']} jour(s) notés depuis le {_info['debut']:%d/%m/%Y}. "
            "Variation moyenne du prix et part des hausses, 1, 3 et 7 jours après le "
            "signal. Moins de ~30 cas sur une ligne = pas encore significatif."
        )
        st.dataframe(
            _res,
            hide_index=True,
            width="stretch",
            column_order=["etat", "cas", "moy_1", "hausse_1", "moy_3", "hausse_3",
                          "ampleur_3", "moy_7", "hausse_7", "ampleur_7", "n_7"],
            column_config={
                "etat": st.column_config.TextColumn("État", pinned=True),
                "cas": st.column_config.NumberColumn("Jours × actifs"),
                "moy_1": st.column_config.NumberColumn("Moy. 1 j", format="%+.2f %%"),
                "hausse_1": st.column_config.NumberColumn("% hausse 1 j", format="%d %%"),
                "moy_3": st.column_config.NumberColumn("Moy. 3 j", format="%+.2f %%"),
                "hausse_3": st.column_config.NumberColumn("% hausse 3 j", format="%d %%"),
                "ampleur_3": st.column_config.NumberColumn(
                    "Ampleur 3 j", format="%.2f %%",
                    help="Taille moyenne du mouvement à 3 jours, quel que soit son sens "
                         "(+5 % et −5 % comptent tous deux 5 %). C'est LA mesure pour "
                         "🟢 Accumulation : si elle n'est pas nettement au-dessus de la "
                         "référence, le « ressort » n'existe pas."),
                "moy_7": st.column_config.NumberColumn("Moy. 7 j", format="%+.2f %%"),
                "hausse_7": st.column_config.NumberColumn("% hausse 7 j", format="%d %%"),
                "ampleur_7": st.column_config.NumberColumn(
                    "Ampleur 7 j", format="%.2f %%",
                    help="Taille moyenne du mouvement à 7 jours, quel que soit son sens."),
                "n_7": st.column_config.NumberColumn(
                    "Cas mesurés à 7 j",
                    help="Nombre de cas qui ont déjà 7 jours de recul. Les moyennes à 7 j "
                         "ne portent que sur eux."),
            },
        )
