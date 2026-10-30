"""
src/utils/alertes.py
Alertes par e-mail : nouvel inscrit à valider, signaux radar du jour,
entrées / sorties de position des bots et problèmes de protection (SL).

Pourquoi Resend et pas Gmail en SMTP
------------------------------------
Railway bloque les ports SMTP sortants (25/465/587) sur les offres Trial et
Hobby : un envoi via smtp.gmail.com échouerait en silence une fois déployé.
Resend s'appelle en HTTPS (port 443, jamais bloqué) et l'offre gratuite
suffit largement (quelques e-mails par jour).

Variables d'environnement (Railway + .env en local)
---------------------------------------------------
    RESEND_API_KEY   clé API Resend (re_...)                      — obligatoire
    ALERT_EMAIL      destinataire (défaut : ADMIN_EMAIL)
    ALERT_FROM       expéditeur (défaut : BacktestBot <onboarding@resend.dev>)
    APP_URL          adresse de l'app, pour mettre un lien dans les e-mails

Sans domaine vérifié chez Resend, l'expéditeur de test onboarding@resend.dev
ne peut écrire QU'À l'adresse du compte Resend : crée le compte Resend avec
l'adresse qui doit recevoir les alertes.

Un envoi raté n'est JAMAIS bloquant : ni l'inscription ni le journal ne
doivent échouer à cause d'un e-mail.
"""

import html
import os
import threading

import requests

RESEND_URL = "https://api.resend.com/emails"


def _config() -> tuple[str, str, str]:
    cle  = os.getenv("RESEND_API_KEY", "").strip()
    dest = (os.getenv("ALERT_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
    exp  = os.getenv("ALERT_FROM", "BacktestBot <onboarding@resend.dev>").strip()
    return cle, dest, exp


def envoyer(sujet: str, corps_html: str) -> bool:
    """Envoie un e-mail. Retourne True si Resend l'a accepté. Jamais d'exception."""
    cle, dest, exp = _config()
    if not cle or not dest:
        print(f"[alerte] e-mail non envoyé (RESEND_API_KEY ou ALERT_EMAIL absent) : {sujet}")
        return False
    try:
        r = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
            json={"from": exp, "to": [dest], "subject": sujet, "html": corps_html},
            timeout=10,
        )
        if r.status_code >= 300:
            print(f"[alerte] Resend a refusé l'e-mail ({r.status_code}) : {r.text[:200]}")
            return False
        print(f"[alerte] e-mail envoyé : {sujet}")
        return True
    except Exception as e:
        print(f"[alerte] envoi impossible : {e}")
        return False


def envoyer_en_fond(sujet: str, corps_html: str) -> None:
    """Même chose sans faire attendre l'utilisateur (inscription)."""
    threading.Thread(target=envoyer, args=(sujet, corps_html), daemon=True).start()


def _lien_app(texte: str) -> str:
    url = os.getenv("APP_URL", "").strip()
    return f'<p><a href="{html.escape(url)}">{html.escape(texte)}</a></p>' if url else ""


# ---------------------------------------------------------------------------
# Alertes
# ---------------------------------------------------------------------------

def nouvel_inscrit(email: str) -> None:
    e = html.escape(email)
    envoyer_en_fond(
        f"🆕 Nouvel inscrit à valider : {email}",
        f"<p><b>{e}</b> vient de créer un compte sur BacktestBot.</p>"
        "<p>Il ne peut rien faire tant que tu ne l'as pas validé : "
        "menu <b>Admin → Utilisateurs</b>.</p>" + _lien_app("Ouvrir l'app"),
    )


def _n(v, fmt):
    try:
        if v is None or v != v:
            return "—"
        return fmt.format(float(v)).replace(".", ",")
    except (TypeError, ValueError):
        return "—"


_TABLE = '<table cellpadding="4" style="border-collapse:collapse;font-size:14px">'


def _tableau(entetes: list[str], lignes: list[list[str]]) -> str:
    th = "".join(f"<th align=left>{html.escape(e)}</th>" for e in entetes)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in l) + "</tr>" for l in lignes)
    return f"{_TABLE}<tr>{th}</tr>{tr}</table>"


def _colonnes_signal(r) -> list[str]:
    return [
        f"<b>{html.escape(str(r['symbol']))}</b>",
        _n(r.get("px_chg_24h"), "{:+.1f} %"),
        _n(r.get("oi_chg_24h"), "{:+.1f} %"),
        _n(r.get("oi_z"), "{:+.1f}"),
        _n(r.get("rsi_14"), "{:.0f}"),
        _n(r.get("funding_annuel"), "{:+.0f} %"),
    ]


_ENTETES_SIGNAL = ["Actif", "Δ Prix 24 h", "Δ OI 24 h", "z OI", "RSI 14 j", "Funding /an"]


def lettre_du_jour(df, meteo: dict, journal, jour) -> bool:
    """La lettre quotidienne, envoyée juste après la bougie (appelée par le journal).

    1. 🚀 Ça part : actifs PASSÉS en 🔵 ou 🟣 aujourd'hui (nouveaux signaux).
    2. ⏩ Toujours en cours : 🔵 / 🟣 des jours précédents, avec le rendement
       depuis le changement de pastille.
    3. 🔭 Ressorts les plus tendus : les 🟢, classés par z OI puis compression.
    4. Le lundi : 📊 bilan de la semaine et bilan cumulé depuis le début.

    Pas d'e-mail un jour sans 🔵, 🟣 ni 🟢 — sauf le lundi (bilan).
    """
    from src.utils.radar import ETATS
    from src.utils import journal as J

    bleu, violet, vert = ETATS["demarrage"], ETATS["shorts"], ETATS["accumulation"]
    lundi = pd_jour(jour).weekday() == 0
    if df is None or df.empty:
        return False
    a_signaler = df["etat"].isin([bleu, violet, vert]).any()
    if not a_signaler and not lundi:
        print("[alerte] aucun 🔵/🟣/🟢 aujourd'hui — pas d'e-mail")
        return False

    anc = J.anciennete(journal, jour) if journal is not None and len(journal) else {}
    trans = J.transitions(journal) if journal is not None and len(journal) else None
    par_coin = df.set_index("hl_name")
    df = df.assign(_anc=df["hl_name"].map(anc).fillna(1).astype(int),
                   _force=df["oi_z"].abs().fillna(df["oi_chg_24h"].abs() / 10).fillna(0))

    corps = (
        f"<p><b>Météo du marché : {html.escape(meteo.get('verdict', '—'))}</b> · "
        f"largeur {_n(meteo.get('largeur'), '{:.0f} %')} · "
        f"BTC {'au-dessus' if meteo.get('btc_dessus') else 'en dessous'} de sa moyenne 50 j"
        f" (pente {_n(meteo.get('btc_pente'), '{:+.1f} %')} sur 5 j)</p>"
    )

    # 1. Ça part aujourd'hui
    nouveaux = df[df["etat"].isin([bleu, violet]) & (df["_anc"] == 1)].sort_values("_force", ascending=False)
    corps += "<h3>🚀 Ça part aujourd'hui</h3>"
    if nouveaux.empty:
        corps += "<p>Aucun nouveau 🔵 ni 🟣.</p>"
    else:
        corps += _tableau(["", *_ENTETES_SIGNAL],
                          [[("🔵 long" if r["etat"] == bleu else "🟣 short"), *_colonnes_signal(r)]
                           for _, r in nouveaux.iterrows()])

    # 2. Toujours en cours
    en_cours = df[df["etat"].isin([bleu, violet]) & (df["_anc"] > 1)].sort_values("_anc")
    if not en_cours.empty:
        lignes = []
        for _, r in en_cours.iterrows():
            rend = None
            if trans is not None and not trans.empty:
                t = trans[(trans["coin"] == r["hl_name"]) & (trans["etat"] == r["etat"])]
                rend = t["rend_actuel"].iloc[0] if len(t) else None
            lignes.append([("🔵" if r["etat"] == bleu else "🟣"),
                           f"<b>{html.escape(str(r['symbol']))}</b>",
                           f"depuis {int(r['_anc'])} j", _n(rend, "{:+.1f} %")])
        corps += ("<h3>⏩ Toujours en cours</h3>"
                  + _tableau(["", "Actif", "Ancienneté", "Rendement depuis le signal"], lignes)
                  + "<p style='color:#888'>Rendement dans le sens du trade : un 🟣 dont le "
                    "prix baisse de 5 % affiche +5 %.</p>")

    # 3. Ressorts les plus tendus
    verts = df[df["etat"] == vert].copy()
    if not verts.empty:
        verts["_comp"] = verts["compression"].fillna(1)
        verts = verts.sort_values(["_force", "_comp"], ascending=[False, True])
        lignes = [[f"<b>{html.escape(str(r['symbol']))}</b>",
                   "🆕" if r["_anc"] == 1 else f"{int(r['_anc'])} j",
                   _n(r.get("oi_z"), "{:+.1f}"), _n(r.get("oi_chg_24h"), "{:+.1f} %"),
                   _n(r.get("compression"), "{:.2f}"), _n(r.get("px_chg_24h"), "{:+.1f} %")]
                  for _, r in verts.head(5).iterrows()]
        reste = f"<p>… et {len(verts) - 5} autre(s).</p>" if len(verts) > 5 else ""
        corps += ("<h3>🔭 Ressorts les plus tendus (🟢 à surveiller)</h3>"
                  + _tableau(["Actif", "Ancienneté", "z OI", "Δ OI 24 h", "Compress.", "Δ Prix 24 h"], lignes)
                  + reste
                  + "<p style='color:#888'>Classés par intensité (z OI, puis compression la "
                    "plus forte) — pas par probabilité : le journal dira si l'ordre compte. "
                    "Sens du mouvement inconnu : on attend qu'ils passent en 🔵 ou 🟣.</p>")

    # 4. Le lundi : bilan
    if lundi:
        corps += _bilan_html(trans, jour)

    corps += ("<p style='color:#888'>Repérage, pas signal d'achat : vérifie le graphique "
              "et la Position 30 j.</p>" + _lien_app("Ouvrir la page Screening"))

    n_b = int(nouveaux["etat"].eq(bleu).sum())
    n_v = int(nouveaux["etat"].eq(violet).sum())
    sujet = (f"📡 Radar : {n_b} nouveau(x) 🔵 · {n_v} 🟣 · {len(verts)} 🟢 — "
             f"{meteo.get('verdict', '')}" + (" · 📊 bilan de la semaine" if lundi else ""))
    return envoyer(sujet, corps)


def pd_jour(jour):
    import pandas as pd
    return pd.Timestamp(jour)


def _bilan_html(trans, jour) -> str:
    from src.utils import journal as J
    import pandas as pd

    if trans is None or trans.empty:
        return ("<h3>📊 Bilan de la semaine</h3><p>Pas encore assez d'historique : le "
                "journal doit d'abord voir des pastilles changer.</p>")
    debut = pd.Timestamp(jour) - pd.Timedelta(days=7)
    semaine = trans[(trans["jour"] >= debut) & (trans["sens"] != 0)]
    h = "<h3>📊 Bilan de la semaine — signaux 🔵 / 🟣 des 7 derniers jours</h3>"
    if semaine.empty:
        h += "<p>Aucun passage en 🔵 ou 🟣 cette semaine.</p>"
    else:
        lignes = [[("🔵" if r["sens"] > 0 else "🟣"), f"<b>{html.escape(str(r['coin']))}</b>",
                   f"{r['jour']:%d/%m}", _n(r["rend_actuel"], "{:+.1f} %")]
                  for _, r in semaine.iterrows()]
        moy = semaine["rend_actuel"].mean()
        h += (_tableau(["", "Actif", "Passé le", "Rendement à ce jour"], lignes)
              + f"<p>Moyenne de la semaine : <b>{_n(moy, '{:+.1f} %')}</b> par signal "
                f"({len(semaine)} signaux).</p>")

    cumul = J.resultats_signaux(trans)
    if not cumul.empty:
        lignes = [[html.escape(r["etat"]), str(r["signaux"]),
                   f"{_n(r['rend_7'], '{:+.1f} %')} (marché {_n(r['marche_7'], '{:+.1f} %')})",
                   _n(r["gagnants_7"], "{:.0f} %"), str(r["n_7"])]
                  for _, r in cumul.iterrows()]
        h += ("<h3>📈 Depuis le début</h3>"
              + _tableau(["Pastille", "Signaux", "Rendement moyen à 7 j", "Gagnants", "Mesurés à 7 j"], lignes)
              + "<p style='color:#888'>Pour 🟢, « rendement » = ampleur du mouvement quel que "
                "soit son sens. Moins de ~30 signaux mesurés = pas encore significatif.</p>")
    return h


# ---------------------------------------------------------------------------
# Bots de trading (bot_mainnet.py) — entrées, sorties, alertes de protection
# ---------------------------------------------------------------------------
# Envoi en arrière-plan : un e-mail lent ne doit jamais retarder un ordre
# (la pose du SL suit l'entrée de quelques millisecondes).

def _prix(v) -> str:
    """Prix lisible quel que soit l'actif : 95 000 pour BTC, 0,00001234 pour PEPE."""
    import math
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v != v or v == 0:
        return "—" if v != v else "0"
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    dec = min(10, max(2, 4 - int(math.floor(math.log10(abs(v))))))
    return f"{v:.{dec}f}".rstrip("0").rstrip(".").replace(".", ",")


def _nom_bot(prefixe: str) -> str:
    return str(prefixe).strip("[]") or "BOT"


def _fiche(lignes: list[tuple[str, str]]) -> str:
    tr = "".join(f"<tr><td style='color:#888'>{html.escape(k)}</td><td><b>{v}</b></td></tr>"
                 for k, v in lignes)
    return f"{_TABLE}{tr}</table>"


def bot_entree(prefixe, side, symbol, prix, notional, marge, levier,
               tp=None, sl=None, protection="", protege=True, adoptee=False) -> None:
    """Position ouverte par le bot, ou trouvée sur HL et adoptée."""
    bot, sym = _nom_bot(prefixe), html.escape(str(symbol))
    if not protege:
        sujet = f"🚨 [{bot}] {side} {symbol} ouvert SANS STOP — intervention requise"
    elif adoptee:
        sujet = f"📥 [{bot}] Position {side} {symbol} adoptée @ {_prix(prix)}"
    else:
        sujet = f"🟢 [{bot}] {side} {symbol} ouvert @ {_prix(prix)}"
    lignes = [("Bot", html.escape(bot)), ("Actif", sym), ("Sens", html.escape(str(side))),
              ("Prix d'entrée", _prix(prix)), ("Taille (notional)", _n(notional, "{:.2f} $"))]
    if marge:
        lignes.append(("Marge engagée", _n(marge, "{:.2f} $") + f" (x{levier})"))
    lignes += [("Take profit", _prix(tp) if tp else "aucun"),
               ("Stop loss", _prix(sl) if sl else "aucun")]
    if protection:
        lignes.append(("Protection", html.escape(protection)))
    note = ("<p>Position présente sur Hyperliquid mais pas ouverte par le bot "
            "(ouverture manuelle ?). Le bot la gère désormais.</p>") if adoptee else ""
    envoyer_en_fond(sujet, note + _fiche(lignes) + _lien_app("Ouvrir le Bot Live"))


def bot_sortie(prefixe, side, symbol, entree, sortie, pnl_usd, pnl_pct, raison,
               frais=None, estime=False) -> None:
    """Position fermée (par le bot ou par un TP/SL natif côté HL)."""
    bot = _nom_bot(prefixe)
    try:
        gagnant = float(pnl_usd) >= 0
    except (TypeError, ValueError):
        gagnant = True
    sujet = (f"{'✅' if gagnant else '🔴'} [{bot}] {side} {symbol} fermé "
             f"({raison}) : {_n(pnl_usd, '{:+.2f} $')} ({_n(pnl_pct, '{:+.2f} %')})")
    lignes = [("Bot", html.escape(bot)), ("Actif", html.escape(str(symbol))),
              ("Sens", html.escape(str(side))), ("Raison", html.escape(str(raison))),
              ("Prix d'entrée", _prix(entree)), ("Prix de sortie", _prix(sortie)),
              ("PnL", f"{_n(pnl_usd, '{:+.2f} $')} ({_n(pnl_pct, '{:+.2f} %')})")]
    if frais:
        lignes.append(("Frais de clôture", _n(frais, "{:.2f} $")))
    note = ("<p style='color:#c60'>⚠️ Exécution introuvable sur Hyperliquid : prix de sortie "
            "et PnL <b>estimés</b> à partir du dernier prix vu par le bot. "
            "Vérifie sur hyperliquid.xyz.</p>") if estime else ""
    envoyer_en_fond(sujet, _fiche(lignes) + note + _lien_app("Ouvrir le Bot Live"))


def bot_alerte(prefixe, titre: str, message: str, emoji: str = "🚨") -> None:
    """Problème de protection ou d'exécution qui demande ton attention."""
    bot = _nom_bot(prefixe)
    envoyer_en_fond(f"{emoji} [{bot}] {titre}",
                    f"<p><b>{html.escape(titre)}</b></p><p>{html.escape(message)}</p>"
                    "<p>Vérifie la position et ses ordres sur hyperliquid.xyz.</p>"
                    + _lien_app("Ouvrir le Bot Live"))

