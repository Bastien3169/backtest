# Authentification : inscription, rôles, page admin

Aucun fichier d'origine n'a été modifié. Tu remets chaque fichier à sa place toi-même.

## Où va chaque fichier

| Fichier dans `_Claude/`       | Destination                  | Nature                                                        |
|-------------------------------|------------------------------|---------------------------------------------------------------|
| `app.py`                      | `app.py`                     | **remplacé** : devient le routeur (auth + menu selon le rôle) |
| `pages/0_📈_Backtest.py`      | `pages/0_📈_Backtest.py`     | **nouveau** : ton ancien `app.py`, seules les lignes 1 à 11 changent |
| `pages/4_📈_BotLive.py`       | `pages/4_📈_BotLive.py`      | **remplacé** : le bloc BOT_PASSWORD devient `require_admin()` |
| `pages/5_👑_Admin.py`         | `pages/5_👑_Admin.py`        | **nouveau** : gestion des utilisateurs                        |
| `src/auth/__init__.py`        | `src/auth/__init__.py`       | nouveau (vide)                                                |
| `src/auth/db.py`              | `src/auth/db.py`             | nouveau : connexion + tables                                  |
| `src/auth/users.py`           | `src/auth/users.py`          | nouveau : logique métier (sans Streamlit)                     |
| `src/auth/ui.py`              | `src/auth/ui.py`             | nouveau : cookie, page de connexion, Mon compte               |
| `requirements.txt`            | `requirements.txt`           | 3 lignes ajoutées à la fin (sqlalchemy, psycopg2-binary, bcrypt) |

Pages 1, 2 et 3 : **inchangées**.

À ajouter à `.gitignore` : `*.db` (base SQLite locale de dev).

## Qui voit quoi

| Page                                  | Non connecté | user | admin |
|---------------------------------------|:------------:|:----:|:-----:|
| Connexion / Inscription               | ✅ (et comptes en attente) |      |       |
| Backtest, Optimisation, Multi-actifs, Screening | ❌ | ✅ | ✅ |
| Mon compte                            | ❌           | ✅   | ✅    |
| Bot Live                              | ❌           | ❌   | ✅    |
| Utilisateurs (admin)                  | ❌           | ❌   | ✅    |

Une page absente du menu n'est pas non plus accessible par son URL (`st.navigation`).
Bot Live et Admin gardent en plus un `require_admin()` en tête de fichier.

⚠️ Avec `st.navigation`, Streamlit ne scanne plus le dossier `pages/` :
**toute nouvelle page doit être déclarée dans `app.py`**.

## Railway

1. Projet Railway → **+ New → Database → PostgreSQL**.
2. Service de l'app → **Variables** :
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (référence au service Postgres, réseau privé)
   - `ADMIN_EMAIL` = ton email
   - `ADMIN_PASSWORD` = phrase de passe de **14 caractères minimum** (pas de règle de complexité)
   - `BOT_PASSWORD` : peut être supprimée, elle ne sert plus.
3. Redéployer. Au démarrage, les tables sont créées et ton compte admin aussi.

Pour changer le mot de passe admin : modifier `ADMIN_PASSWORD` sur Railway puis redéployer.
Ça ferme toutes tes sessions admin ouvertes.

## En local

- Sans `DATABASE_URL` dans `.env` → base SQLite `users.db` créée automatiquement (bandeau d'avertissement sur la page admin).
- Pour travailler sur la vraie base : `DATABASE_URL=` = la valeur **`DATABASE_PUBLIC_URL`** du service Postgres (l'URL interne ne marche pas hors de Railway).
- Mets aussi `ADMIN_EMAIL` et `ADMIN_PASSWORD` dans `.env`.

## Règles de sécurité

- Utilisateurs : 10 caractères minimum + minuscule, majuscule, chiffre, caractère spécial.
- Mots de passe hachés avec bcrypt. Cookie = jeton aléatoire ; en base, seulement son SHA-256.
- 5 échecs de connexion → compte bloqué 15 min (déblocage possible depuis la page admin).
- Même message pour « email inconnu » et « mauvais mot de passe ».
- Session : 12 h, ou 30 jours avec « Rester connecté », prolongée tant que tu reviens. 5 sessions max par compte.
- Le compte `ADMIN_EMAIL` ne peut être ni dégradé, ni supprimé, ni réinitialisé depuis l'interface.
- Passer un utilisateur « admin » depuis la page admin lui donne accès à **Bot Live** (argent réel).

## Validation des inscriptions

- Un nouvel inscrit est **en attente** : il peut créer son compte mais pas se connecter.
  S'il tape le bon mot de passe, il voit « Compte en attente de validation ».
- Dans le menu, la page admin affiche « Utilisateurs (n en attente) » quand il y a des demandes.
- En haut de la page admin : un bouton **Valider** ou **Refuser** par demande (refuser supprime la demande).
- Tu peux aussi **Suspendre** un compte validé : il perd l'accès tout de suite, sans être supprimé.
- Migration : si la table `users` existe déjà, la colonne `approved` est ajoutée automatiquement
  au démarrage, et les comptes existants restent validés.

## Page admin

Liste des inscrits (date d'inscription, dernière connexion, sessions actives, blocage), filtre par email,
et pour un utilisateur : valider / suspendre, changer le rôle, fermer ses sessions, débloquer, réinitialiser le mot de passe, supprimer.

## Tests effectués

- Logique métier : 39 tests (dont attente, validation, suspension et migration d'une base existante) sur PostgreSQL 16 et SQLite. Tous verts, y compris quand on les rejoue sur une base existante.
- Routage (AppTest Streamlit) : un anonyme n'a que la page de connexion. Un user n'atteint ni Bot Live ni Admin, même par l'URL. Un jeton forgé renvoie vers la page de connexion. La connexion et l'inscription par formulaire fonctionnent. Un inscrit en attente est refusé, et le bouton Valider de la page admin le débloque.
- **À vérifier à la main** (il faut un vrai navigateur) : se connecter avec « Rester connecté », faire F5, puis fermer et rouvrir l'onglet.
