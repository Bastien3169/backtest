# Panneau de prise de position manuelle (page BotLive)

| Fichier ici | À remettre dans |
|---|---|
| `pages/4_📈_BotLive.py` | `app_backtest/pages/4_📈_BotLive.py` |

Basé sur ta version actuelle, correctifs de log inclus. Rien d'autre n'a bougé.

## Ce que faisait le bouton avant

Il n'improvisait pas : il reprenait la section 2.

```
marge    = solde HL × size_pct %
notional = marge × leverage
TP / SL  = tp_pct / sl_pct de la section 2
```

Le problème n'était pas l'absence de règle, c'était qu'il fallait remonter dans
une autre section pour la changer, et raisonner en % du solde au lieu de dollars.

## Ce que ça devient

Le bouton est maintenant un `st.popover` : **rien de plus sur la page tant qu'on
ne clique pas**. Au clic, le panneau s'ouvre avec les mêmes briques que l'onglet
➕ Renforcer :

- **Montant au choix** — `USDC` ou `% du solde`, sélecteur horizontal.
  Pré-rempli avec ce que donne la section 2.
- **TP/SL** via `saisie_tp_sl()` — le widget du renfort, en `%` **ou** en prix de
  déclenchement, avec le gain et la perte en dollars affichés dessous.
- **Récapitulatif** avant validation : marge × levier = notional, TP et SL en %.
- Avertissement si aucun SL, blocage si un niveau est du mauvais côté du prix.
- Bouton **✅ Confirmer l'ouverture** à l'intérieur du panneau.

Les valeurs sont pré-remplies depuis la section 2 **à la première ouverture** ;
ensuite Streamlit garde tes dernières saisies (comportement normal des widgets
à clé).

## Deux décisions à connaître

**1. Les TP/SL manuels sont enregistrés dans la stratégie du bot, pas ceux de la
section 2.** Sinon : tu ouvres à la main avec un SL à 3 %, la section 2 dit 2 %,
tu démarres le bot → le bot croit le SL à 2 % et coupe la position alors que
l'ordre réellement posé sur HL est à 3 %. Le bot doit voir ce qui existe
vraiment.

**2. `size_pct` reste celui de la section 2.** Il pilote les entrées FUTURES du
bot, pas la position que tu viens d'ouvrir. Une prise manuelle de 30 USDC ne doit
pas reconfigurer silencieusement ton bot à 30 % du solde.

## Correctif au passage

`last_entry_date` était écrit en heure **locale** alors que le bot le compare en
**UTC**. Une prise manuelle après 22 h (heure de Paris) datait donc du lendemain
et bloquait l'entrée automatique du bot le jour suivant. Passé en UTC.

## Vérifié

- Syntaxe sous Python 3.12 ;
- `_go_prise` bien défini dans le popover avant d'être testé ;
- les `_tpsl[...]` restants (lignes 584-593) sont ceux de la section 2, intacts ;
- `use_container_width` retiré du popover : API dépréciée dans les Streamlit
  récents, ton venv est en 1.56.

Non vérifié : le rendu réel, je n'ai pas lancé Streamlit. `st.popover` demande
Streamlit ≥ 1.32 — ton `requirements.txt` l'exige déjà, et ton venv est en 1.56.

---

## Rendu réel — exécuté, plus seulement compilé

Le panneau a été exécuté pour de vrai avec `streamlit.testing.v1.AppTest` (le
moteur Streamlit sans navigateur), sur le **code réel** du fichier, avec des
valeurs simulées : solde 99,43 USDC, BTC à 76 534 $, SHORT, x1, TP 5 % / SL 2 %.

Aucune exception dans aucun scénario. Ce qui s'affiche :

```
radio        'Montant exprimé en'      ['USDC', '% du solde']        → USDC
number_input 'Marge engagée (USDC)'    99.43   (min 0, pas de 10)
radio        'Exprimer le TP / SL en'  ['%', 'Prix ($)']             → %
number_input 'TP de la position (%)'   5.0     (0 → 100, pas 0.5)
number_input 'SL de la position (%)'   2.0     (0 → 50,  pas 0.5)
caption      Sur 99.43 $ de position : TP 5.00 % (72707.30 $) → +4.97 $
                                     · SL 2.00 % (78064.68 $) → −1.99 $
caption      ➡️ Entrée au marché sur BTC en SHORT — 99.43 USDC de marge × 1
                = 99.43 USDC de position · TP 5.00 % / SL 2.00 %
button       '✅ Confirmer l'ouverture SHORT'   disabled=False
```

Scénarios vérifiés :

| # | Action | Résultat |
|---|---|---|
| 1 | Montant → `% du solde` | champ « % du solde HL » à 100, récap inchangé |
| 2 | Marge → 30 USDC | récap et gain/perte recalculés (+1.50 / −0.60 $) |
| 3 | TP/SL → `Prix ($)` | champs pré-remplis à 72 707,30 et 78 064,68 |
| 4 | SL → 0 % | « aucun SL » dans le récap + avertissement rouge |
| 5 | SL à 70 000 $ sur un SHORT | erreur « doit être AU-DESSUS du prix actuel » + **bouton désactivé** |
| 6 | Marge à 0 ou 5 USDC | erreur « marge trop faible » + **bouton désactivé** |

Le scénario 6 a révélé un défaut corrigé dans la foulée : le minimum de ~10 USDC
n'était vérifié qu'**après** le clic. Il est maintenant contrôlé dans le panneau,
et le bouton est grisé tant que la marge est insuffisante.

Reste non vérifié : l'apparence (couleurs, largeur du popover, alignement des
colonnes). AppTest rend l'arbre des composants, pas des pixels. Le test a tourné
sous Streamlit 1.63 ; ton venv est en 1.56 — même API pour tout ce qui est utilisé ici.

---

## Ajout — choix LONG / SHORT dans le panneau

Avant, le sens était imposé par la section 2 : pour ouvrir dans l'autre sens il
fallait reconfigurer toute la stratégie du bot. Un `st.radio` « Sens de la
position » (🟢 LONG / 🔴 SHORT) est maintenant la première ligne du panneau,
pré-positionné sur le sens de la section 2.

L'étiquette du bouton devient neutre : **« 🎯 Prendre une position sur BTC »**,
puisque le sens se choisit à l'intérieur.

Le sens choisi (`_short_prise`) pilote **tout** le reste :

- validation TP/SL (`saisie_tp_sl` reçoit `_short_prise`) — sur un LONG le TP
  doit être au-dessus du prix, sur un SHORT en dessous ;
- l'ordre envoyé : `short()` ou `buy()` ;
- le calcul des prix TP/SL natifs et l'appel `set_tp_sl(is_short=...)` ;
- `state["strategy"]["is_short"]`, pour que le bot gère la position qui existe
  réellement et pas celle de la section 2.

**Avertissement si le sens diffère de la section 2.** Les indicateurs d'entrée et
de sortie du bot, eux, restent ceux de la section 2 et sont écrits pour l'autre
sens. Le panneau le dit explicitement : vérifie la section 2 avant de démarrer le
bot sur une position ouverte à contre-sens.

### Vérifié (AppTest, code réel)

| Scénario | Résultat |
|---|---|
| Défaut, section 2 en SHORT | radio sur 🔴 SHORT, TP 72 707 $ / SL 78 065 $ |
| Bascule en LONG | TP passe à 80 361 $, SL à 75 003 $ — les côtés s'inversent ✅ |
| LONG + mode Prix ($) | niveaux cohérents, aucune erreur ✅ |
| LONG alors que section 2 = SHORT | avertissement affiché ✅ |

Aucune exception dans aucun scénario.
