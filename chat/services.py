import os
import secrets
import threading
from datetime import datetime, timedelta

import bcrypt
from django.conf import settings
from django.db import connection, transaction

MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'application/pdf': 'pdf',
    'application/msword': 'doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.ms-powerpoint': 'ppt',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/zip': 'zip',
    'text/plain': 'txt',
    'application/json': 'json',
    'image/webp': 'webp',
}

_db_initialized = False
_db_init_lock = threading.Lock()
_supports_super_admin_role = None
_legacy_super_admin_user_id = None


def fetch_one(query, params=()):
    with connection.cursor() as cur:
        cur.execute(query, params)
        cols = [c[0] for c in cur.description] if cur.description else []
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(cols, row))


def fetch_all(query, params=()):
    with connection.cursor() as cur:
        cur.execute(query, params)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def php_password_check(plain_password, hashed_password):
    if not hashed_password:
        return False
    encoded = hashed_password.encode('utf-8')
    if encoded.startswith(b'$2y$'):
        encoded = b'$2b$' + encoded[4:]
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), encoded)
    except ValueError:
        return False


def php_password_hash(plain_password):
    value = bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt())
    return value.decode('utf-8').replace('$2b$', '$2y$', 1)


def is_admin_session(request):
    return request.session.get('role') in ('admin', 'super_admin')


def is_super_admin_session(request):
    role = request.session.get('role')
    if role == 'super_admin':
        return True
    if role != 'admin':
        return False
    user_id = request.session.get('user_id')
    return is_user_super_admin(int(user_id)) if user_id else False


def initialize_database():
    global _db_initialized
    if _db_initialized:
        return

    with _db_init_lock:
        if _db_initialized:
            return

        connection.ensure_connection()
        _create_base_tables_if_needed()
        _ensure_users_super_admin_schema()
        _repair_foreign_keys_referencing_users_old()
        _ensure_conversation_members_table()

        general_id = ensure_general_conversation_id()
        _backfill_group_memberships(general_id)
        _ensure_single_super_admin()

        _db_initialized = True


def _create_base_tables_if_needed():
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                profile_picture TEXT DEFAULT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin', 'super_admin')),
                is_blocked INTEGER NOT NULL DEFAULT 0,
                sanction_reason TEXT DEFAULT NULL,
                sanctioned_until TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('group', 'direct')),
                name TEXT DEFAULT NULL,
                created_by INTEGER DEFAULT NULL,
                user_one_id INTEGER DEFAULT NULL,
                user_two_id INTEGER DEFAULT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (user_one_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (user_two_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                description TEXT DEFAULT NULL,
                upload_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL DEFAULT 1,
                user_id INTEGER NOT NULL,
                message TEXT DEFAULT NULL,
                file_id INTEGER DEFAULT NULL,
                is_ephemeral INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER DEFAULT NULL,
                details TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
    _create_supporting_indexes()


def _create_supporting_indexes():
    tables = {row['name'] for row in fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    with connection.cursor() as cur:
        cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_created_at ON chat_messages(created_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON chat_messages(conversation_id, created_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_user_id ON chat_messages(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_messages_expiry ON chat_messages(expires_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_files_upload_date ON files(upload_date)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_admin_logs_created_at ON admin_logs(created_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_conversations_type_created ON conversations(type, created_at)')
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_direct_pair
            ON conversations(type, user_one_id, user_two_id)
            WHERE type = 'direct'
            """
        )
        if 'conversation_members' in tables:
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_members_pair ON conversation_members(conversation_id, user_id)'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS idx_conversation_members_user ON conversation_members(user_id)'
            )


def _ensure_users_super_admin_schema():
    global _supports_super_admin_role

    row = fetch_one("SELECT sql FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1")
    table_sql = str((row or {}).get('sql') or '')
    if table_sql == '':
        return
    if 'super_admin' in table_sql.lower():
        _supports_super_admin_role = True
        return

    old_cols = {item['name'] for item in fetch_all('PRAGMA table_info(users)')}

    def col_expr(name, fallback):
        return name if name in old_cols else fallback

    select_sql = f"""
        SELECT
            {col_expr('id', 'NULL')} AS id,
            {col_expr('username', "'user_' || hex(randomblob(4))") } AS username,
            {col_expr('email', "'legacy_' || hex(randomblob(4)) || '@jemichat.local'") } AS email,
            {col_expr('password', "''")} AS password,
            {col_expr('profile_picture', 'NULL')} AS profile_picture,
            CASE
                WHEN {col_expr('role', "'user'")} IN ('user', 'admin', 'super_admin') THEN {col_expr('role', "'user'")}
                ELSE 'user'
            END AS role,
            {col_expr('is_blocked', '0')} AS is_blocked,
            {col_expr('sanction_reason', 'NULL')} AS sanction_reason,
            {col_expr('sanctioned_until', 'NULL')} AS sanctioned_until,
            COALESCE({col_expr('created_at', 'NULL')}, CURRENT_TIMESTAMP) AS created_at
        FROM users
    """

    raw = connection.connection
    cur = raw.cursor()
    try:
        cur.execute('PRAGMA foreign_keys = OFF')
        cur.execute('BEGIN')
        cur.execute('DROP TABLE IF EXISTS users_new')
        cur.execute(
            """
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                profile_picture TEXT DEFAULT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin', 'super_admin')),
                is_blocked INTEGER NOT NULL DEFAULT 0,
                sanction_reason TEXT DEFAULT NULL,
                sanctioned_until TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO users_new (
                id, username, email, password, profile_picture,
                role, is_blocked, sanction_reason, sanctioned_until, created_at
            )
            {select_sql}
            """
        )
        cur.execute('DROP TABLE users')
        cur.execute('ALTER TABLE users_new RENAME TO users')
        cur.execute('COMMIT')
    except Exception:
        cur.execute('ROLLBACK')
        raise
    finally:
        cur.execute('PRAGMA foreign_keys = ON')
        cur.close()

    _supports_super_admin_role = True


def _repair_foreign_keys_referencing_users_old():
    offenders = fetch_all(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN ('conversations', 'files', 'chat_messages', 'admin_logs', 'conversation_members')
          AND (
                lower(coalesce(sql, '')) LIKE '%users_old%'
                OR lower(coalesce(sql, '')) LIKE '%users_new%'
                OR lower(coalesce(sql, '')) LIKE '%_fkfix_old%'
              )
        """
    )
    if not offenders:
        # Clean potential leftovers from interrupted migrations.
        _drop_stale_backup_tables()
        return

    def create_sql(table_name):
        definitions = {
            'conversations': f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('group', 'direct')),
                name TEXT DEFAULT NULL,
                created_by INTEGER DEFAULT NULL,
                user_one_id INTEGER DEFAULT NULL,
                user_two_id INTEGER DEFAULT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (user_one_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (user_two_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """,
            'files': f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                description TEXT DEFAULT NULL,
                upload_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """,
            'chat_messages': f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL DEFAULT 1,
                user_id INTEGER NOT NULL,
                message TEXT DEFAULT NULL,
                file_id INTEGER DEFAULT NULL,
                is_ephemeral INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE SET NULL
            )
        """,
            'admin_logs': f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER DEFAULT NULL,
                details TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """,
            'conversation_members': f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL
            )
        """,
        }
        return definitions[table_name.split('_repair_new_')[0]]

    raw = connection.connection
    cur = raw.cursor()
    try:
        cur.execute('PRAGMA foreign_keys = OFF')
        cur.execute('BEGIN')

        for item in offenders:
            table = item['name']
            if table not in ('conversations', 'files', 'chat_messages', 'admin_logs', 'conversation_members'):
                continue

            new_table = f'{table}_repair_new_1'
            cur.execute(f'DROP TABLE IF EXISTS {new_table}')
            cur.execute(create_sql(new_table))

            old_cols = [row[1] for row in cur.execute(f'PRAGMA table_info({table})').fetchall()]
            new_cols = [row[1] for row in cur.execute(f'PRAGMA table_info({new_table})').fetchall()]
            common = [col for col in new_cols if col in old_cols]
            if common:
                cols_sql = ', '.join(common)
                cur.execute(
                    f'INSERT INTO {new_table} ({cols_sql}) SELECT {cols_sql} FROM {table}'
                )
            cur.execute(f'DROP TABLE {table}')
            cur.execute(f'ALTER TABLE {new_table} RENAME TO {table}')

        cur.execute('COMMIT')
    except Exception:
        cur.execute('ROLLBACK')
        raise
    finally:
        cur.execute('PRAGMA foreign_keys = ON')
        cur.close()

    _create_supporting_indexes()
    _drop_stale_backup_tables()


def _drop_stale_backup_tables():
    stale = fetch_all(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND (
                name LIKE '%\\_fkfix_old' ESCAPE '\\'
                OR name LIKE '%\\_repair_new\\_%' ESCAPE '\\'
              )
        """
    )
    if not stale:
        return

    with connection.cursor() as cur:
        cur.execute('PRAGMA foreign_keys = OFF')
        for item in stale:
            cur.execute(f"DROP TABLE IF EXISTS {item['name']}")
        cur.execute('PRAGMA foreign_keys = ON')


def _ensure_conversation_members_table():
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_members_pair ON conversation_members(conversation_id, user_id)'
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_conversation_members_user ON conversation_members(user_id)'
        )


def _backfill_group_memberships(general_id):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
            SELECT %s, u.id, NULL
            FROM users u
            """,
            [int(general_id)],
        )

        # Legacy groups previously visible to everyone: keep that behavior if the group has no members yet.
        cur.execute(
            """
            INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
            SELECT c.id, u.id, c.created_by
            FROM conversations c
            JOIN users u ON 1 = 1
            WHERE c.type = 'group'
              AND c.id <> %s
              AND NOT EXISTS (
                  SELECT 1 FROM conversation_members cm
                  WHERE cm.conversation_id = c.id
              )
            """,
            [int(general_id)],
        )


def _ensure_single_super_admin():
    global _legacy_super_admin_user_id

    users_count = fetch_one('SELECT COUNT(*) AS c FROM users')
    if int((users_count or {}).get('c') or 0) == 0:
        return

    supers = fetch_all(
        """
        SELECT id
        FROM users
        WHERE role = 'super_admin'
        ORDER BY datetime(created_at) ASC, id ASC
        """
    )

    if supers:
        keeper_id = int(supers[0]['id'])
        if len(supers) > 1:
            ids = [int(item['id']) for item in supers[1:]]
            with connection.cursor() as cur:
                placeholders = ','.join(['%s'] * len(ids))
                cur.execute(
                    f"UPDATE users SET role = 'admin' WHERE id IN ({placeholders})",
                    ids,
                )
        _legacy_super_admin_user_id = keeper_id
        return

    first_admin = fetch_one(
        """
        SELECT id
        FROM users
        WHERE role = 'admin'
        ORDER BY datetime(created_at) ASC, id ASC
        LIMIT 1
        """
    )
    if first_admin:
        target_id = int(first_admin['id'])
    else:
        first_user = fetch_one(
            """
            SELECT id
            FROM users
            ORDER BY datetime(created_at) ASC, id ASC
            LIMIT 1
            """
        )
        target_id = int((first_user or {}).get('id') or 0)

    if target_id > 0:
        with connection.cursor() as cur:
            cur.execute("UPDATE users SET role = 'super_admin' WHERE id = %s", [target_id])
        _legacy_super_admin_user_id = target_id


def database_supports_super_admin_role():
    global _supports_super_admin_role
    if _supports_super_admin_role is not None:
        return _supports_super_admin_role

    row = fetch_one("SELECT sql FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1")
    sql = str((row or {}).get('sql') or '')
    _supports_super_admin_role = 'super_admin' in sql.lower()
    return _supports_super_admin_role


def get_legacy_super_admin_user_id():
    global _legacy_super_admin_user_id
    if _legacy_super_admin_user_id is not None:
        return _legacy_super_admin_user_id

    row = fetch_one(
        """
        SELECT id
        FROM users
        WHERE role = 'admin'
        ORDER BY datetime(created_at) ASC, id ASC
        LIMIT 1
        """
    )
    _legacy_super_admin_user_id = int((row or {}).get('id') or 0)
    return _legacy_super_admin_user_id


def login_user(username, password):
    initialize_database()

    user = fetch_one(
        """
        SELECT id, username, password, role, is_blocked, sanction_reason, sanctioned_until
        FROM users
        WHERE username = %s
        LIMIT 1
        """,
        [username.strip()],
    )
    if not user or not php_password_check(password, user['password']):
        return False, "Nom d'utilisateur ou mot de passe incorrect.", None

    if int(user.get('is_blocked') or 0) == 1:
        return False, 'Compte bloque. Contactez un administrateur.', None

    sanctioned_until = user.get('sanctioned_until')
    if sanctioned_until:
        dt = parse_db_dt(sanctioned_until)
        if dt > datetime.utcnow():
            return False, f"Compte temporairement sanctionne jusqu'au {dt.strftime('%d/%m/%Y %H:%M')}.", None

    return True, None, user


def register_user(username, password):
    initialize_database()

    username = username.strip()
    email = f"{username}.{secrets.token_hex(4)}@jemichat.local"

    exists = fetch_one('SELECT id FROM users WHERE username = %s OR email = %s LIMIT 1', [username, email])
    if exists:
        return False, "Nom d'utilisateur ou email deja utilise."

    first = fetch_one('SELECT COUNT(*) AS c FROM users')
    role = 'super_admin' if int((first or {}).get('c') or 0) == 0 else 'user'

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)',
                [username, email, php_password_hash(password), role],
            )
            new_user_id = int(cur.lastrowid)

    ensure_member_in_general_group(new_user_id)
    return True, None


def ensure_general_conversation_id():
    row = fetch_one(
        """
        SELECT id
        FROM conversations
        WHERE type='group' AND lower(coalesce(name, '')) = lower(%s)
        LIMIT 1
        """,
        ['Général'],
    )
    if row:
        return int(row['id'])

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (type, name, created_by) VALUES ('group', %s, NULL)",
                ['Général'],
            )
            cid = int(cur.lastrowid)

    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
            SELECT %s, id, NULL FROM users
            """,
            [cid],
        )

    return cid


def ensure_member_in_general_group(user_id):
    group_id = ensure_general_conversation_id()
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
            VALUES (%s, %s, NULL)
            """,
            [int(group_id), int(user_id)],
        )


def get_user_by_id(user_id):
    return fetch_one(
        """
        SELECT id, username, email, profile_picture, role, is_blocked, sanction_reason, sanctioned_until, created_at
        FROM users
        WHERE id = %s
        LIMIT 1
        """,
        [int(user_id)],
    )


def is_user_super_admin(user_id):
    initialize_database()

    user_id = int(user_id)
    if user_id <= 0:
        return False

    if database_supports_super_admin_role():
        row = fetch_one('SELECT role FROM users WHERE id = %s LIMIT 1', [user_id])
        return bool(row and row.get('role') == 'super_admin')

    return user_id == get_legacy_super_admin_user_id()


def moderation_message(user):
    if not user:
        return None
    if int(user.get('is_blocked') or 0) == 1:
        return "Votre compte est bloque par l'administration."

    if user.get('sanctioned_until'):
        dt = parse_db_dt(user['sanctioned_until'])
        if dt > datetime.utcnow():
            msg = f"Compte temporairement sanctionne jusqu'au {dt.strftime('%d/%m/%Y %H:%M')}."
            if user.get('sanction_reason'):
                msg += f" Motif: {user['sanction_reason']}"
            return msg
    return None


def get_user_conversations(user_id):
    initialize_database()

    return fetch_all(
        """
        SELECT c.id, c.type, c.name, c.created_at, c.user_one_id, c.user_two_id,
               lm.message AS last_message, lm.created_at AS last_message_at, lm.file_id AS last_file_id,
               CASE
                   WHEN c.type = 'group' THEN COALESCE(c.name, 'Groupe')
                   WHEN c.user_one_id = %s THEN u2.username
                   ELSE u1.username
               END AS display_name
        FROM conversations c
        LEFT JOIN users u1 ON u1.id = c.user_one_id
        LEFT JOIN users u2 ON u2.id = c.user_two_id
        LEFT JOIN (
            SELECT m.conversation_id, m.message, m.created_at, m.file_id
            FROM chat_messages m
            INNER JOIN (
                SELECT conversation_id, MAX(id) AS last_id
                FROM chat_messages
                GROUP BY conversation_id
            ) latest ON latest.last_id = m.id
        ) lm ON lm.conversation_id = c.id
        WHERE c.is_archived = 0
          AND (
                (c.type = 'group' AND EXISTS (
                    SELECT 1
                    FROM conversation_members cm
                    WHERE cm.conversation_id = c.id AND cm.user_id = %s
                ))
                OR (c.type = 'direct' AND (c.user_one_id = %s OR c.user_two_id = %s))
              )
        ORDER BY datetime(COALESCE(lm.created_at, c.created_at)) DESC, c.id DESC
        """,
        [int(user_id), int(user_id), int(user_id), int(user_id)],
    )


def get_conversation_for_user(conversation_id, user_id):
    initialize_database()

    return fetch_one(
        """
        SELECT c.*,
               CASE
                   WHEN c.type = 'group' THEN COALESCE(c.name, 'Groupe')
                   WHEN c.user_one_id = %s THEN u2.username
                   ELSE u1.username
               END AS display_name
        FROM conversations c
        LEFT JOIN users u1 ON u1.id = c.user_one_id
        LEFT JOIN users u2 ON u2.id = c.user_two_id
        WHERE c.id = %s
          AND c.is_archived = 0
          AND (
                (c.type = 'group' AND EXISTS (
                    SELECT 1 FROM conversation_members cm
                    WHERE cm.conversation_id = c.id AND cm.user_id = %s
                ))
                OR (c.type = 'direct' AND (c.user_one_id = %s OR c.user_two_id = %s))
              )
        LIMIT 1
        """,
        [int(user_id), int(conversation_id), int(user_id), int(user_id), int(user_id)],
    )


def get_conversation_messages(conversation_id, limit=100):
    return fetch_all(
        """
        SELECT cm.*, u.username, u.profile_picture, f.original_name, f.file_type, f.file_size
        FROM chat_messages cm
        JOIN users u ON cm.user_id = u.id
        LEFT JOIN files f ON cm.file_id = f.id
        WHERE cm.conversation_id = %s
        ORDER BY datetime(cm.created_at) DESC, cm.id DESC
        LIMIT %s
        """,
        [int(conversation_id), int(limit)],
    )


def get_conversation_messages_after_id(conversation_id, after_id=0, limit=60):
    return fetch_all(
        """
        SELECT cm.*, u.username, u.profile_picture, f.original_name, f.file_type, f.file_size
        FROM chat_messages cm
        JOIN users u ON cm.user_id = u.id
        LEFT JOIN files f ON cm.file_id = f.id
        WHERE cm.conversation_id = %s
          AND cm.id > %s
        ORDER BY cm.id ASC
        LIMIT %s
        """,
        [int(conversation_id), int(after_id), int(limit)],
    )


def get_online_users():
    return fetch_all(
        """
        SELECT u.id, u.username, MAX(cm.created_at) AS last_activity
        FROM users u
        JOIN chat_messages cm ON cm.user_id = u.id
        WHERE datetime(cm.created_at) >= datetime('now', '-5 minutes')
        GROUP BY u.id, u.username
        ORDER BY datetime(last_activity) DESC
        """
    )


def get_inbox_candidates(current_user_id):
    return fetch_all(
        """
        SELECT id, username
        FROM users
        WHERE id != %s
          AND is_blocked = 0
          AND (sanctioned_until IS NULL OR datetime(sanctioned_until) <= datetime('now'))
        ORDER BY username ASC
        """,
        [int(current_user_id)],
    )


def get_or_create_direct_conversation(current_user_id, target_user_id):
    current_user_id = int(current_user_id)
    target_user_id = int(target_user_id)
    if current_user_id <= 0 or target_user_id <= 0 or current_user_id == target_user_id:
        return 0

    u1 = min(current_user_id, target_user_id)
    u2 = max(current_user_id, target_user_id)

    row = fetch_one(
        """
        SELECT id
        FROM conversations
        WHERE type='direct' AND user_one_id=%s AND user_two_id=%s
        LIMIT 1
        """,
        [u1, u2],
    )
    if row:
        return int(row['id'])

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (type, name, created_by, user_one_id, user_two_id)
                VALUES ('direct', NULL, %s, %s, %s)
                """,
                [current_user_id, u1, u2],
            )
            return int(cur.lastrowid)


def save_upload(uploaded_file, allowed_types=None, max_size=MAX_FILE_SIZE):
    if uploaded_file.size > max_size:
        raise ValueError('Fichier trop volumineux.')

    mime = uploaded_file.content_type or 'application/octet-stream'
    allowed = allowed_types or ALLOWED_TYPES
    if mime not in allowed:
        raise ValueError('Type de fichier non autorise.')

    ext = allowed[mime]
    filename = f"{secrets.token_hex(16)}.{ext}"
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    path = os.path.join(settings.MEDIA_ROOT, filename)
    with open(path, 'wb') as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)

    return {
        'filename': filename,
        'original_name': os.path.basename(uploaded_file.name),
        'file_type': mime,
        'file_size': int(uploaded_file.size),
    }


def insert_message(user_id, conversation_id, message, file_meta=None, ephemeral_week=False):
    expires_at = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S') if ephemeral_week else None

    with transaction.atomic():
        file_id = None
        if file_meta:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO files (user_id, filename, original_name, file_type, file_size, description)
                    VALUES (%s, %s, %s, %s, %s, NULL)
                    """,
                    [int(user_id), file_meta['filename'], file_meta['original_name'], file_meta['file_type'], int(file_meta['file_size'])],
                )
                file_id = int(cur.lastrowid)

        final_message = message.strip() if message.strip() else 'a partage un fichier'
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_messages (conversation_id, user_id, message, file_id, is_ephemeral, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [int(conversation_id), int(user_id), final_message, file_id, 1 if ephemeral_week else 0, expires_at],
            )
            return int(cur.lastrowid)


def update_own_message(message_id, conversation_id, user_id, new_message):
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE chat_messages
            SET message = %s
            WHERE id = %s AND conversation_id = %s AND user_id = %s
            """,
            [new_message.strip(), int(message_id), int(conversation_id), int(user_id)],
        )
        updated = cur.rowcount > 0

    return updated


def delete_own_message(message_id, conversation_id, user_id):
    target = fetch_one(
        """
        SELECT cm.id, cm.file_id, f.filename
        FROM chat_messages cm
        LEFT JOIN files f ON f.id = cm.file_id
        WHERE cm.id = %s AND cm.conversation_id = %s AND cm.user_id = %s
        LIMIT 1
        """,
        [int(message_id), int(conversation_id), int(user_id)],
    )
    if not target:
        return False

    file_id = target.get('file_id')
    filename = target.get('filename')

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('DELETE FROM chat_messages WHERE id = %s', [int(message_id)])
            if file_id:
                cur.execute('SELECT COUNT(*) FROM chat_messages WHERE file_id = %s', [int(file_id)])
                remain = int(cur.fetchone()[0])
                if remain == 0:
                    cur.execute('DELETE FROM files WHERE id = %s', [int(file_id)])

    if file_id and filename:
        path = os.path.join(settings.MEDIA_ROOT, os.path.basename(filename))
        if os.path.isfile(path):
            os.remove(path)

    return True


def get_user_stats(user_id):
    stats = fetch_one(
        'SELECT COUNT(*) AS file_count, COALESCE(SUM(file_size), 0) AS total_size FROM files WHERE user_id = %s',
        [int(user_id)],
    )
    files = fetch_all(
        """
        SELECT id, original_name, file_type, file_size, upload_date
        FROM files
        WHERE user_id = %s
        ORDER BY datetime(upload_date) DESC
        LIMIT 100
        """,
        [int(user_id)],
    )
    return stats or {'file_count': 0, 'total_size': 0}, files


def update_profile_picture(user_id, uploaded_file):
    if uploaded_file.size > 5 * 1024 * 1024:
        return False, 'Image trop volumineuse (max 5MB).'

    allowed = {
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/gif': 'gif',
        'image/webp': 'webp',
    }
    mime = uploaded_file.content_type or ''
    if mime not in allowed:
        return False, 'Seules les images JPG, PNG, GIF ou WEBP sont autorisees.'

    ext = allowed[mime]
    final_name = f"profile_{int(user_id)}_{secrets.token_hex(8)}.{ext}"
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    final_path = os.path.join(settings.MEDIA_ROOT, final_name)

    with open(final_path, 'wb') as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)

    old = fetch_one('SELECT profile_picture FROM users WHERE id = %s LIMIT 1', [int(user_id)])
    old_name = (old or {}).get('profile_picture')

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('UPDATE users SET profile_picture = %s WHERE id = %s', [final_name, int(user_id)])

    if old_name:
        old_path = os.path.join(settings.MEDIA_ROOT, os.path.basename(old_name))
        if os.path.isfile(old_path) and os.path.basename(old_path) != final_name:
            os.remove(old_path)

    return True, None


def get_admin_stats():
    stats = fetch_one(
        """
        SELECT
            COUNT(*) AS total_users,
            SUM(CASE WHEN role IN ('admin', 'super_admin') THEN 1 ELSE 0 END) AS admin_count,
            SUM(CASE WHEN is_blocked = 1 THEN 1 ELSE 0 END) AS blocked_count,
            SUM(CASE WHEN sanctioned_until IS NOT NULL AND datetime(sanctioned_until) > datetime('now') THEN 1 ELSE 0 END) AS sanctioned_count
        FROM users
        """
    )
    return {
        'total_users': int((stats or {}).get('total_users') or 0),
        'admin_count': int((stats or {}).get('admin_count') or 0),
        'blocked_count': int((stats or {}).get('blocked_count') or 0),
        'sanctioned_count': int((stats or {}).get('sanctioned_count') or 0),
    }


def get_users_for_admin(filters):
    q = (filters.get('q') or '').strip()
    role = filters.get('role') or 'all'
    status = filters.get('status') or 'all'
    sort = filters.get('sort') or 'created_desc'
    per_page = max(5, min(50, int(filters.get('per_page') or 12)))
    page = max(1, int(filters.get('page') or 1))

    where = ['1=1']
    params = []

    if q:
        where.append('(u.username LIKE %s OR coalesce(u.email, "") LIKE %s)')
        params.extend([f'%{q}%', f'%{q}%'])

    if role == 'admin':
        where.append("u.role IN ('admin', 'super_admin')")
    elif role == 'user':
        where.append("u.role = 'user'")

    if status == 'active':
        where.append("u.is_blocked = 0 AND (u.sanctioned_until IS NULL OR datetime(u.sanctioned_until) <= datetime('now'))")
    elif status == 'blocked':
        where.append('u.is_blocked = 1')
    elif status == 'sanctioned':
        where.append("u.sanctioned_until IS NOT NULL AND datetime(u.sanctioned_until) > datetime('now')")

    order_by = 'datetime(u.created_at) DESC, u.id DESC'
    if sort == 'created_asc':
        order_by = 'datetime(u.created_at) ASC, u.id ASC'
    elif sort == 'username_asc':
        order_by = 'lower(u.username) ASC, u.id ASC'
    elif sort == 'username_desc':
        order_by = 'lower(u.username) DESC, u.id DESC'

    where_sql = ' AND '.join(where)
    count = fetch_one(f'SELECT COUNT(*) AS c FROM users u WHERE {where_sql}', params)
    total = int((count or {}).get('c') or 0)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    users = fetch_all(
        f"""
        SELECT
            u.id, u.username, u.email, u.profile_picture, u.role,
            u.is_blocked, u.sanction_reason, u.sanctioned_until, u.created_at,
            COALESCE(msg.msg_count, 0) AS msg_count,
            COALESCE(f.file_count, 0) AS file_count
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS msg_count
            FROM chat_messages
            GROUP BY user_id
        ) msg ON msg.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS file_count
            FROM files
            GROUP BY user_id
        ) f ON f.user_id = u.id
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )

    return {
        'users': users,
        'total': total,
        'total_pages': total_pages,
        'page': page,
        'per_page': per_page,
    }


def create_user_by_admin(username, password, email, role):
    initialize_database()

    username = username.strip()
    email = (email or '').strip() or f"{username}.{secrets.token_hex(4)}@jemichat.local"

    if role not in ('user', 'admin'):
        return False, 'Role invalide.', None
    if len(password) < 6:
        return False, 'Mot de passe trop court (minimum 6 caracteres).', None

    exists = fetch_one('SELECT id FROM users WHERE username = %s OR email = %s LIMIT 1', [username, email])
    if exists:
        return False, "Nom d'utilisateur ou email deja utilise.", None

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)',
                [username, email, php_password_hash(password), role],
            )
            uid = int(cur.lastrowid)

    ensure_member_in_general_group(uid)
    return True, None, uid


def _admin_count():
    row = fetch_one("SELECT COUNT(*) AS c FROM users WHERE role IN ('admin', 'super_admin')")
    return int((row or {}).get('c') or 0)


def check_manage_target_permissions(actor_id, target_id, allow_self=False):
    actor_id = int(actor_id)
    target_id = int(target_id)

    actor = get_user_by_id(actor_id)
    if not actor or actor.get('role') not in ('admin', 'super_admin'):
        return False, 'Action non autorisee.', None

    target = get_user_by_id(target_id)
    if not target:
        return False, 'Utilisateur introuvable.', None

    if not allow_self and actor_id == target_id:
        return False, 'Vous ne pouvez pas vous auto-modifier.', None

    if is_user_super_admin(target_id):
        return False, 'Le super admin ne peut pas etre modifie.', None

    actor_is_super = is_user_super_admin(actor_id)
    target_role = str(target.get('role') or 'user')
    if not actor_is_super and target_role in ('admin', 'super_admin'):
        return False, 'Seul le super admin peut gerer un administrateur.', None

    return True, None, target


def update_user_role(actor_id, target_id, role):
    role = str(role)
    if role not in ('user', 'admin'):
        return False, 'Role invalide.'

    ok, err, target = check_manage_target_permissions(actor_id, target_id, allow_self=False)
    if not ok:
        return False, err

    actor_is_super = is_user_super_admin(actor_id)
    if role == 'admin' and not actor_is_super:
        return False, 'Seul le super admin peut attribuer le role admin.'

    current_role = str(target.get('role') or 'user')
    if current_role in ('admin', 'super_admin') and role == 'user' and _admin_count() <= 1:
        return False, 'Impossible de retirer le dernier administrateur.'

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('UPDATE users SET role = %s WHERE id = %s', [role, int(target_id)])

    return True, None


def block_user(target_id, reason):
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE users SET is_blocked = 1, sanction_reason = %s, sanctioned_until = NULL WHERE id = %s',
                [reason, int(target_id)],
            )


def unblock_user(target_id):
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE users SET is_blocked = 0, sanctioned_until = NULL, sanction_reason = NULL WHERE id = %s',
                [int(target_id)],
            )


def sanction_user(target_id, hours, reason):
    until = (datetime.utcnow() + timedelta(hours=max(1, int(hours)))).strftime('%Y-%m-%d %H:%M:%S')
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE users SET is_blocked = 0, sanctioned_until = %s, sanction_reason = %s WHERE id = %s',
                [until, reason, int(target_id)],
            )


def clear_sanction(target_id):
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE users SET sanctioned_until = NULL, sanction_reason = NULL WHERE id = %s',
                [int(target_id)],
            )


def reset_password(target_id, new_password):
    if len(new_password) < 6:
        return False, 'Mot de passe trop court (minimum 6 caracteres).'

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                'UPDATE users SET password = %s WHERE id = %s',
                [php_password_hash(new_password), int(target_id)],
            )
    return True, None


def delete_user_with_assets(target_id):
    target_id = int(target_id)

    files = fetch_all('SELECT filename FROM files WHERE user_id = %s', [target_id])
    profile = fetch_one('SELECT profile_picture FROM users WHERE id = %s LIMIT 1', [target_id])

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('DELETE FROM users WHERE id = %s', [target_id])

    for item in files:
        path = os.path.join(settings.MEDIA_ROOT, os.path.basename(item['filename']))
        if os.path.isfile(path):
            os.remove(path)

    if profile and profile.get('profile_picture'):
        path = os.path.join(settings.MEDIA_ROOT, os.path.basename(profile['profile_picture']))
        if os.path.isfile(path):
            os.remove(path)


def search_users_for_group(query, limit=30):
    query = (query or '').strip()
    if query == '':
        return []

    return fetch_all(
        """
        SELECT id, username, role
        FROM users
        WHERE lower(username) LIKE lower(%s)
        ORDER BY username ASC
        LIMIT %s
        """,
        [f'%{query}%', int(limit)],
    )


def get_admin_group_overview():
    general_id = ensure_general_conversation_id()
    return fetch_all(
        """
        SELECT c.id, c.name, c.created_at,
               COALESCE(u.username, 'Système') AS created_by_name,
               COUNT(cm.user_id) AS member_count
        FROM conversations c
        LEFT JOIN users u ON u.id = c.created_by
        LEFT JOIN conversation_members cm ON cm.conversation_id = c.id
        WHERE c.type = 'group' AND c.is_archived = 0 AND c.id <> %s
        GROUP BY c.id, c.name, c.created_at, created_by_name
        ORDER BY datetime(c.created_at) DESC, c.id DESC
        """,
        [int(general_id)],
    )


def create_group_with_members(admin_id, name, member_ids):
    admin_id = int(admin_id)
    name = (name or '').strip()
    if name == '':
        return False, 'Nom du groupe obligatoire.', None

    unique_members = {int(uid) for uid in member_ids if str(uid).isdigit() and int(uid) > 0}
    unique_members.add(admin_id)

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (type, name, created_by) VALUES ('group', %s, %s)",
                [name, admin_id],
            )
            conversation_id = int(cur.lastrowid)

            member_list = sorted(unique_members)
            if member_list:
                placeholders = ','.join(['%s'] * len(member_list))
                cur.execute(
                    f"""
                    INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
                    SELECT %s, u.id, %s
                    FROM users u
                    WHERE u.id IN ({placeholders})
                    """,
                    [conversation_id, admin_id] + member_list,
                )

    return True, None, conversation_id


def add_users_to_group(admin_id, group_id, member_ids):
    admin_id = int(admin_id)
    group_id = int(group_id)

    group = fetch_one(
        """
        SELECT id, type, is_archived
        FROM conversations
        WHERE id = %s
        LIMIT 1
        """,
        [group_id],
    )
    if not group or group.get('type') != 'group' or int(group.get('is_archived') or 0) == 1:
        return False, 'Groupe invalide.'

    user_ids = sorted({int(uid) for uid in member_ids if str(uid).isdigit() and int(uid) > 0})
    if not user_ids:
        return False, 'Selectionnez au moins un utilisateur.'

    with transaction.atomic():
        with connection.cursor() as cur:
            placeholders = ','.join(['%s'] * len(user_ids))
            cur.execute(
                f"""
                INSERT OR IGNORE INTO conversation_members (conversation_id, user_id, added_by)
                SELECT %s, u.id, %s
                FROM users u
                WHERE u.id IN ({placeholders})
                """,
                [group_id, admin_id] + user_ids,
            )

    return True, None


def get_group_members(group_id):
    return fetch_all(
        """
        SELECT u.id, u.username, u.role
        FROM conversation_members cm
        JOIN users u ON u.id = cm.user_id
        WHERE cm.conversation_id = %s
        ORDER BY lower(u.username) ASC
        """,
        [int(group_id)],
    )


def log_admin_action(admin_id, action, target_type='user', target_id=None, details=None):
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_logs (admin_id, action, target_type, target_id, details)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [int(admin_id), action, target_type, target_id, details],
            )


def get_admin_logs(limit=35):
    return fetch_all(
        """
        SELECT al.*, u.username AS admin_name
        FROM admin_logs al
        JOIN users u ON u.id = al.admin_id
        ORDER BY datetime(al.created_at) DESC
        LIMIT %s
        """,
        [int(limit)],
    )


def get_file_by_id(file_id):
    return fetch_one('SELECT * FROM files WHERE id = %s LIMIT 1', [int(file_id)])


def delete_owned_file(file_id, user_id):
    file_row = fetch_one(
        'SELECT * FROM files WHERE id = %s AND user_id = %s LIMIT 1',
        [int(file_id), int(user_id)],
    )
    if not file_row:
        return False

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('DELETE FROM files WHERE id = %s', [int(file_id)])

    path = os.path.join(settings.MEDIA_ROOT, os.path.basename(file_row['filename']))
    if os.path.isfile(path):
        os.remove(path)
    return True


def parse_db_dt(value):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return datetime.utcnow()
