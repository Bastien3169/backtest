"""
src/auth/users.py
Logique métier des comptes : inscription, connexion, sessions, administration.
Aucun import Streamlit ici → testable seul.
"""

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from sqlalchemy import delete, func, insert, select, update

from src.auth.db import engine, init_db, sessions, users

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
SESSION_COURTE_H = 12            # sans « Rester connecté »
SESSION_LONGUE_H = 30 * 24       # avec « Rester connecté »
MAX_SESSIONS_PAR_USER = 5
MAX_ECHECS = 5
BLOCAGE_MIN = 15

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

# Utilisateurs : 10 caractères mini + minuscule + majuscule + chiffre + spécial
MDP_MIN_USER = 10
MDP_RE_USER = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{%d,}$" % MDP_MIN_USER)
MDP_REGLE_USER = (
    f"Au moins {MDP_MIN_USER} caractères, avec une minuscule, une majuscule, "
    "un chiffre et un caractère spécial."
)

# Admin : pas de règle de complexité, mais une LONGUEUR minimale.
# Une phrase de passe (« velo trail fourviere 2026 ») est facile à taper et bien
# plus solide que « Aa1!aa ». Ce compte pilote des ordres en argent réel.
MDP_MIN_ADMIN = 14

MSG_IDENTIFIANTS = "❌ Email ou mot de passe incorrect."
MSG_ATTENTE = "⏳ Compte en attente de validation par l'administrateur."


def _now() -> datetime:
    """UTC naïf (colonnes DateTime sans fuseau, identiques Postgres/SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_mdp(mdp: str) -> str:
    return bcrypt.hashpw(mdp.encode(), bcrypt.gensalt()).decode()


def _verif_mdp(mdp: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(mdp.encode(), h.encode())
    except ValueError:
        return False


def _hash_jeton(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


# Hash factice : on fait tourner bcrypt même quand l'email n'existe pas, pour
# que le temps de réponse ne révèle pas quels emails sont inscrits.
_HASH_FACTICE = _hash_mdp(secrets.token_hex(8))


# ---------------------------------------------------------------------------
# Initialisation (appelée une fois par process)
# ---------------------------------------------------------------------------
def setup() -> None:
    init_db()
    sync_admin_from_env()
    purger_sessions_expirees()


def sync_admin_from_env() -> None:
    """ADMIN_EMAIL / ADMIN_PASSWORD (variables Railway) font foi pour le compte admin.

    - compte absent            → créé avec le rôle admin
    - compte présent           → rôle forcé à admin, mot de passe resynchronisé
                                 s'il a changé dans les variables
    Changer ADMIN_PASSWORD sur Railway puis redéployer suffit à changer le mot
    de passe admin. Pas de valeur par défaut : sans variables, pas d'admin.
    """
    email = _norm_email(os.getenv("ADMIN_EMAIL", ""))
    mdp = os.getenv("ADMIN_PASSWORD", "")
    if not email or not mdp:
        print("[auth] ⚠️ ADMIN_EMAIL / ADMIN_PASSWORD absents — aucun admin synchronisé")
        return
    if len(mdp) < MDP_MIN_ADMIN:
        print(f"[auth] ❌ ADMIN_PASSWORD trop court (< {MDP_MIN_ADMIN} caractères) — ignoré (admin non créé / non modifié)")
        return

    with engine.begin() as conn:
        row = conn.execute(
            select(users.c.id, users.c.password_hash, users.c.role, users.c.approved)
            .where(users.c.email == email)
        ).first()
        if row is None:
            conn.execute(insert(users).values(
                email=email, password_hash=_hash_mdp(mdp), role="admin",
                created_at=_now(), failed_attempts=0, approved=True,
            ))
            print(f"[auth] ✅ Admin créé : {email}")
            return
        valeurs = {}
        if row.role != "admin":
            valeurs["role"] = "admin"
        if not row.approved:
            valeurs["approved"] = True
        if not _verif_mdp(mdp, row.password_hash):
            valeurs["password_hash"] = _hash_mdp(mdp)
            # Nouveau mot de passe → on déconnecte les anciennes sessions admin
            conn.execute(delete(sessions).where(sessions.c.user_id == row.id))
        if valeurs:
            conn.execute(update(users).where(users.c.id == row.id).values(**valeurs))
            print(f"[auth] 🔄 Admin resynchronisé : {email} ({', '.join(valeurs)})")


def is_admin_email(email: str) -> bool:
    return _norm_email(email) == _norm_email(os.getenv("ADMIN_EMAIL", ""))


# ---------------------------------------------------------------------------
# Inscription / connexion
# ---------------------------------------------------------------------------
def register(email: str, mdp: str) -> tuple[bool, str]:
    email = _norm_email(email)
    if not EMAIL_RE.match(email):
        return False, "❌ Email invalide."
    if is_admin_email(email):
        return False, "❌ Cet email est déjà utilisé."
    if not MDP_RE_USER.match(mdp or ""):
        return False, f"❌ Mot de passe trop faible. {MDP_REGLE_USER}"

    with engine.begin() as conn:
        existe = conn.execute(select(users.c.id).where(users.c.email == email)).first()
        if existe:
            return False, "❌ Cet email est déjà utilisé."
        conn.execute(insert(users).values(
            email=email, password_hash=_hash_mdp(mdp), role="user",
            created_at=_now(), failed_attempts=0, approved=False,
        ))
    return True, ("✅ Compte créé. Il sera actif dès que l'administrateur l'aura validé.")


def login(email: str, mdp: str, rester_connecte: bool = False) -> tuple[bool, str, Optional[str]]:
    """Renvoie (succès, message, jeton). Le jeton va dans le cookie du navigateur."""
    email = _norm_email(email)
    now = _now()

    with engine.begin() as conn:
        u = conn.execute(select(users).where(users.c.email == email)).first()

        if u is None:
            _verif_mdp(mdp or "", _HASH_FACTICE)          # temps constant
            return False, MSG_IDENTIFIANTS, None

        if u.locked_until and u.locked_until > now:
            reste = int((u.locked_until - now).total_seconds() // 60) + 1
            return False, f"🔒 Trop d'échecs. Réessaie dans {reste} min.", None

        if not _verif_mdp(mdp or "", u.password_hash):
            echecs = (u.failed_attempts or 0) + 1
            valeurs = {"failed_attempts": echecs}
            if echecs >= MAX_ECHECS:
                valeurs = {"failed_attempts": 0,
                           "locked_until": now + timedelta(minutes=BLOCAGE_MIN)}
            conn.execute(update(users).where(users.c.id == u.id).values(**valeurs))
            return False, MSG_IDENTIFIANTS, None

        # Mot de passe bon mais compte pas encore validé : on le dit (seul le
        # vrai titulaire du mot de passe voit ce message).
        if not u.approved:
            return False, MSG_ATTENTE, None

        # Succès
        conn.execute(update(users).where(users.c.id == u.id).values(
            failed_attempts=0, locked_until=None, last_login=now))

        # Ménage : sessions expirées de ce compte + plafond de sessions actives
        conn.execute(delete(sessions).where(
            (sessions.c.user_id == u.id) & (sessions.c.expires_at <= now)))
        anciennes = conn.execute(
            select(sessions.c.token_hash).where(sessions.c.user_id == u.id)
            .order_by(sessions.c.created_at.desc()).offset(MAX_SESSIONS_PAR_USER - 1)
        ).scalars().all()
        if anciennes:
            conn.execute(delete(sessions).where(sessions.c.token_hash.in_(anciennes)))

        jeton = secrets.token_urlsafe(32)
        duree = SESSION_LONGUE_H if rester_connecte else SESSION_COURTE_H
        conn.execute(insert(sessions).values(
            token_hash=_hash_jeton(jeton), user_id=u.id, created_at=now,
            expires_at=now + timedelta(hours=duree), duration_h=duree,
        ))
    return True, "✅ Connexion réussie.", jeton


def user_from_token(jeton: Optional[str]) -> Optional[dict]:
    """Utilisateur associé à un jeton valide (expiration glissante), sinon None."""
    if not jeton:
        return None
    now = _now()
    th = _hash_jeton(jeton)
    with engine.begin() as conn:
        row = conn.execute(
            select(users.c.id, users.c.email, users.c.role,
                   sessions.c.expires_at, sessions.c.duration_h)
            .join(sessions, sessions.c.user_id == users.c.id)
            .where((sessions.c.token_hash == th) & (sessions.c.expires_at > now)
                   & users.c.approved)
        ).first()
        if row is None:
            return None
        fenetre = timedelta(hours=row.duration_h)
        # On ne réécrit que si moins de la moitié de la fenêtre reste
        # (Streamlit appelle cette fonction à chaque interaction)
        if row.expires_at - now < fenetre / 2:
            conn.execute(update(sessions).where(sessions.c.token_hash == th)
                         .values(expires_at=now + fenetre))
    return {"id": row.id, "email": row.email, "role": row.role}


def logout(jeton: Optional[str]) -> None:
    if not jeton:
        return
    with engine.begin() as conn:
        conn.execute(delete(sessions).where(sessions.c.token_hash == _hash_jeton(jeton)))


def purger_sessions_expirees() -> None:
    with engine.begin() as conn:
        conn.execute(delete(sessions).where(sessions.c.expires_at <= _now()))


def changer_mon_mdp(user_id: int, ancien: str, nouveau: str, est_admin: bool) -> tuple[bool, str]:
    if est_admin:
        return False, "Le mot de passe admin se change via la variable ADMIN_PASSWORD sur Railway."
    if not MDP_RE_USER.match(nouveau or ""):
        return False, f"❌ Mot de passe trop faible. {MDP_REGLE_USER}"
    with engine.begin() as conn:
        h = conn.execute(select(users.c.password_hash).where(users.c.id == user_id)).scalar()
        if h is None or not _verif_mdp(ancien or "", h):
            return False, "❌ Ancien mot de passe incorrect."
        conn.execute(update(users).where(users.c.id == user_id)
                     .values(password_hash=_hash_mdp(nouveau)))
    return True, "✅ Mot de passe modifié."


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
def admin_liste_users() -> list[dict]:
    now = _now()
    nb_sessions = (
        select(sessions.c.user_id, func.count().label("n"))
        .where(sessions.c.expires_at > now).group_by(sessions.c.user_id).subquery()
    )
    with engine.connect() as conn:
        rows = conn.execute(
            select(users.c.id, users.c.email, users.c.role, users.c.created_at,
                   users.c.last_login, users.c.locked_until, users.c.approved,
                   func.coalesce(nb_sessions.c.n, 0).label("sessions_actives"))
            .outerjoin(nb_sessions, nb_sessions.c.user_id == users.c.id)
            .order_by(users.c.id)
        ).mappings().all()
    return [dict(r) for r in rows]


def _proteger_admin_env(conn, user_id: int) -> Optional[str]:
    """Empêche de dégrader/supprimer le compte admin défini dans les variables."""
    email = conn.execute(select(users.c.email).where(users.c.id == user_id)).scalar()
    if email is None:
        return "❌ Utilisateur introuvable."
    if is_admin_email(email):
        return "⛔ Compte admin principal : géré par ADMIN_EMAIL / ADMIN_PASSWORD."
    return None


def admin_set_role(user_id: int, role: str) -> tuple[bool, str]:
    if role not in ("user", "admin"):
        return False, "❌ Rôle inconnu."
    with engine.begin() as conn:
        err = _proteger_admin_env(conn, user_id)
        if err:
            return False, err
        conn.execute(update(users).where(users.c.id == user_id).values(role=role))
        conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
    return True, f"✅ Rôle passé à « {role} » (sessions de l'utilisateur fermées)."


def admin_reset_mdp(user_id: int, nouveau: str) -> tuple[bool, str]:
    if not MDP_RE_USER.match(nouveau or ""):
        return False, f"❌ Mot de passe trop faible. {MDP_REGLE_USER}"
    with engine.begin() as conn:
        err = _proteger_admin_env(conn, user_id)
        if err:
            return False, err
        conn.execute(update(users).where(users.c.id == user_id).values(
            password_hash=_hash_mdp(nouveau), failed_attempts=0, locked_until=None))
        conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
    return True, "✅ Mot de passe réinitialisé (sessions fermées)."


def nb_en_attente() -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(users).where(~users.c.approved)).scalar() or 0


def admin_valider(user_id: int, valide: bool) -> tuple[bool, str]:
    """Valide (True) ou suspend (False) un compte. Suspendre ferme ses sessions."""
    with engine.begin() as conn:
        if not valide:
            err = _proteger_admin_env(conn, user_id)
            if err:
                return False, err
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
        n = conn.execute(update(users).where(users.c.id == user_id)
                         .values(approved=valide)).rowcount
    if not n:
        return False, "❌ Utilisateur introuvable."
    return True, "✅ Compte validé." if valide else "⏸️ Compte suspendu (sessions fermées)."


def admin_debloquer(user_id: int) -> tuple[bool, str]:
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id)
                     .values(failed_attempts=0, locked_until=None))
    return True, "✅ Compte débloqué."


def admin_fermer_sessions(user_id: int) -> tuple[bool, str]:
    with engine.begin() as conn:
        n = conn.execute(delete(sessions).where(sessions.c.user_id == user_id)).rowcount
    return True, f"✅ {n} session(s) fermée(s)."


def admin_supprimer(user_id: int) -> tuple[bool, str]:
    with engine.begin() as conn:
        err = _proteger_admin_env(conn, user_id)
        if err:
            return False, err
        # Suppression explicite des sessions : SQLite n'applique pas ON DELETE CASCADE
        conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
        conn.execute(delete(users).where(users.c.id == user_id))
    return True, "🗑️ Utilisateur supprimé."
