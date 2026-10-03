"""
src/utils/alertes.py
Alertes par e-mail : nouvel inscrit à valider, signaux radar du jour.

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


def signaux_du_jour(df, meteo: dict, etats: dict) -> bool:
    """Résumé quotidien envoyé juste après la bougie (appelé par le journal).

    N'envoie rien s'il n'y a ni 🔵 Démarrage, ni 🟣 Shorts en force, ni
    🟢 Accumulation : un e-mail « rien aujourd'hui » chaque matin finit par ne
    plus être lu.
    """
    a_signaler = [etats["demarrage"], etats["shorts"], etats["accumulation"]]
    if df is None or df.empty or not df["etat"].isin(a_signaler).any():
        print("[alerte] aucun 🔵/🟣/🟢 aujourd'hui — pas d'e-mail")
        return False

    def _n(v, fmt):
        try:
            return fmt.format(float(v)).replace(".", ",") if v == v and v is not None else "—"
        except (TypeError, ValueError):
            return "—"

    def _bloc(etat: str, titre: str) -> str:
        g = df[df["etat"] == etat]
        if g.empty:
            return ""
        g = g.assign(_f=g["oi_z"].abs().fillna(0)).sort_values("_f", ascending=False)
        lignes = "".join(
            "<tr>"
            f"<td><b>{html.escape(str(r['symbol']))}</b></td>"
            f"<td>{_n(r.get('px_chg_24h'), '{:+.1f} %')}</td>"
            f"<td>{_n(r.get('oi_chg_24h'), '{:+.1f} %')}</td>"
            f"<td>{_n(r.get('oi_z'), '{:+.1f}')}</td>"
            f"<td>{_n(r.get('alpha_7d'), '{:+.1f}')}</td>"
            f"<td>{_n(r.get('funding_annuel'), '{:+.0f} %')}</td>"
            "</tr>"
            for _, r in g.iterrows()
        )
        return (f"<h3>{html.escape(titre)} ({len(g)})</h3>"
                '<table cellpadding="4" style="border-collapse:collapse">'
                "<tr><th align=left>Actif</th><th>Δ Prix 24 h</th><th>Δ OI 24 h</th>"
                "<th>z OI</th><th>Alpha 7 j</th><th>Funding /an</th></tr>"
                f"{lignes}</table>")

    n_long  = int((df["etat"] == etats["demarrage"]).sum())
    n_short = int((df["etat"] == etats["shorts"]).sum())
    n_surv  = int((df["etat"] == etats["accumulation"]).sum())
    corps = (
        f"<p><b>Météo du marché : {html.escape(meteo.get('verdict', '—'))}</b> · "
        f"largeur {_n(meteo.get('largeur'), '{:.0f} %')} · "
        f"BTC {'au-dessus' if meteo.get('btc_dessus') else 'en dessous'} de sa moyenne 30 j</p>"
        + _bloc(etats["demarrage"], "🔵 Démarrage — candidats long")
        + _bloc(etats["shorts"], "🟣 Shorts en force — candidats short")
        + _bloc(etats["accumulation"], "🟢 Accumulation — à surveiller")
        + "<p style='color:#888'>Repérage, pas signal d'achat : vérifie le graphique "
          "et la Position 30 j. Les résultats réels de chaque état sont dans le "
          "Journal des états, en bas de la page Screening.</p>"
        + _lien_app("Ouvrir la page Screening")
    )
    return envoyer(f"📡 Radar : {n_long} 🔵 / {n_short} 🟣 / {n_surv} 🟢 — "
                   f"{meteo.get('verdict', '')}", corps)
