# JemiChat Django Backend

Réimplémentation backend en **Python Django** pour conserver le frontend actuel (`html/css/js`) et la même base SQLite (`data/chat.sqlite`).

## Ce qui a changé

- Backend PHP remplacé par un backend Django.
- Messagerie temps réel via **polling HTTP** compatible WSGI.
- URLs backend conservées en `.php` pour rester compatibles avec le frontend:
  - `index.php`, `login.php`, `register.php`, `logout.php`
  - `send_message.php`, `upload.php`, `edit_message.php`, `delete_message.php`
  - `download.php`, `view_file.php`, `delete.php`
  - `profile.php`, `admin.php`
- Base SQLite existante réutilisée sans migration destructrice.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
python manage.py runserver 0.0.0.0:8000
```

Puis ouvrir:

```text
http://localhost:8000/index.php
```

## Notes

- Les fichiers statiques existants (`style.css`, `script.js`) sont réutilisés.
- Les uploads restent dans `uploads/`.
- Authentification compatible avec les hashes mot de passe PHP (`bcrypt`, conversion `$2y$` -> `$2b$` côté vérification).
- Le frontend utilise un **polling HTTP** (`poll_messages.php`) toutes les ~2 secondes pour synchroniser nouveaux messages, modifications et suppressions recentes.

## Reset des donnees SQL

```bash
python reset_database.py
```

Ce script:
- conserve le schema de la base
- supprime uniquement les donnees metier (users, conversations, messages, fichiers, logs, sessions)
- recree le salon `Général` si absent
