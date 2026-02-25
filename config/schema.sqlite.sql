PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA cache_size = -20000;

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
);

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
);

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
);

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
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER DEFAULT NULL,
    details TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_created_at ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON chat_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_expiry ON chat_messages(expires_at);
CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id);
CREATE INDEX IF NOT EXISTS idx_files_upload_date ON files(upload_date);
CREATE INDEX IF NOT EXISTS idx_admin_logs_created_at ON admin_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_type_created ON conversations(type, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_direct_pair ON conversations(type, user_one_id, user_two_id) WHERE type = 'direct';
