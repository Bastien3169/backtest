"""
src/auth/db.py
Connexion à la base des utilisateurs + définition des tables.

- Sur Railway : DATABASE_URL est fournie par le service PostgreSQL
  (variable de référence ${{Postgres.DATABASE_URL}} à ajouter au service de l'app).
- En local sans DATABASE_URL : repli sur un fichier SQLite (DATA_DIR/users.db),
  pratique pour développer sans rien installer. Un avertissement est affiché.

Les tables sont décrites avec SQLAlchemy Core (et non en SQL brut) pour que le
même code tourne sur PostgreSQL ET sur SQLite.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table,
    create_engine, inspect, text, true,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_ROOT, ".env"))


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        # Certains hébergeurs donnent encore "postgres://", refusé par SQLAlchemy 2
        # On force aussi le pilote psycopg2 (celui de requirements.txt) : depuis
        # SQLAlchemy 2.1, "postgresql://" pointe par défaut vers psycopg v3.
        for prefixe in ("postgres://", "postgresql://"):
            if url.startswith(prefixe):
                url = "postgresql+psycopg2://" + url[len(prefixe):]
        return url

    data_dir = os.getenv("DATA_DIR", _ROOT)
    os.makedirs(data_dir, exist_ok=True)
    chemin = os.path.join(data_dir, "users.db")
    print(f"[auth] ⚠️ DATABASE_URL absente — base SQLite locale : {chemin}")
    return f"sqlite:///{chemin}"


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,       # connexion morte (Postgres Railway redémarré) → rouverte
    **({} if IS_SQLITE else {"pool_size": 3, "max_overflow": 5}),
)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255), unique=True, nullable=False),
    Column("password_hash", String(100), nullable=False),
    Column("role", String(20), nullable=False, default="user"),   # 'user' | 'admin'
    Column("created_at", DateTime, nullable=False),
    Column("last_login", DateTime),
    # Anti force brute : 5 échecs → compte bloqué 15 min
    Column("failed_attempts", Integer, nullable=False, default=0),
    Column("locked_until", DateTime),
    # Validation par l'admin : un nouvel inscrit ne peut rien faire tant que
    # approved est faux. server_default=true → les comptes déjà existants au
    # moment de la migration restent actifs.
    Column("approved", Boolean, nullable=False, server_default=true()),
)

sessions = Table(
    "sessions", metadata,
    # On stocke le SHA-256 du jeton, jamais le jeton lui-même : une fuite de la
    # base ne permet pas de se faire passer pour quelqu'un.
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"),
           nullable=False, index=True),
    Column("created_at", DateTime, nullable=False),
    Column("expires_at", DateTime, nullable=False, index=True),
    Column("duration_h", Integer, nullable=False),   # pour l'expiration glissante
)


def init_db() -> None:
    """Crée les tables manquantes + colonnes ajoutées après coup. Idempotent, non destructif."""
    metadata.create_all(engine)

    # create_all ne modifie pas une table existante : migrations à la main.
    colonnes = {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "approved" not in colonnes:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN approved BOOLEAN NOT NULL DEFAULT TRUE"))
