#!/usr/bin/env python3
"""Vide uniquement les donnees de la base SQLite (schema conserve)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'chat.sqlite'


def has_django(python_bin: Path) -> bool:
    if not python_bin.exists():
        return False
    result = subprocess.run(
        [str(python_bin), '-c', 'import django'],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def resolve_python_with_django() -> Path:
    env_override = os.environ.get('DJANGO_PYTHON')
    candidates: list[Path] = []
    if env_override:
        candidates.append(Path(env_override))

    candidates.extend(
        [
            Path(sys.executable),
            BASE_DIR / '.venv' / 'bin' / 'python',
            Path.home() / 'djangoEnv' / 'bin' / 'python',
            Path('/usr/bin/python3'),
        ]
    )

    for candidate in candidates:
        if has_django(candidate):
            return candidate

    raise RuntimeError(
        "Aucun interpreteur Python avec Django n'a ete trouve. "
        "Active ton virtualenv ou exporte DJANGO_PYTHON=/chemin/vers/python."
    )


def ensure_schema_ready(python_bin: Path) -> None:
    cmd = [
        str(python_bin),
        'manage.py',
        'shell',
        '-c',
        'from chat import services; services.initialize_database(); print("schema_ready")',
    ]
    print('> ' + ' '.join(cmd))
    subprocess.run(cmd, cwd=BASE_DIR, check=True)


def clear_database_data() -> None:
    if not DB_PATH.exists():
        print('Base inexistante, rien a vider.')
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys = OFF')
        cur.execute('BEGIN')

        tables = {
            row[0]
            for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

        # Ordre adapte aux dependances FK.
        if 'admin_logs' in tables:
            cur.execute('DELETE FROM admin_logs')
        if 'chat_messages' in tables:
            cur.execute('DELETE FROM chat_messages')
        if 'files' in tables:
            cur.execute('DELETE FROM files')
        if 'conversation_members' in tables:
            cur.execute('DELETE FROM conversation_members')
        if 'conversations' in tables:
            cur.execute("DELETE FROM conversations WHERE lower(coalesce(name,'')) != lower('Général')")
        if 'users' in tables:
            cur.execute('DELETE FROM users')
        if 'django_session' in tables:
            cur.execute('DELETE FROM django_session')

        if 'sqlite_sequence' in tables:
            cur.execute(
                """
                DELETE FROM sqlite_sequence
                WHERE name IN (
                    'admin_logs', 'chat_messages', 'files',
                    'conversation_members', 'conversations', 'users'
                )
                """
            )

        # Conserver ou recreer le salon general.
        if 'conversations' in tables:
            cur.execute(
                """
                INSERT INTO conversations (type, name, created_by)
                SELECT 'group', 'Général', NULL
                WHERE NOT EXISTS (
                    SELECT 1 FROM conversations
                    WHERE type = 'group' AND lower(coalesce(name,'')) = lower('Général')
                )
                """
            )

        cur.execute('COMMIT')
    except Exception:
        cur.execute('ROLLBACK')
        raise
    finally:
        cur.execute('PRAGMA foreign_keys = ON')
        conn.close()


def main() -> int:
    print('Vidage des donnees SQL en cours...')
    python_bin = resolve_python_with_django()
    print(f'Interpreteur detecte: {python_bin}')

    ensure_schema_ready(python_bin)
    clear_database_data()

    print('Vidage termine avec succes.')
    print('Le schema de la base est conserve.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
