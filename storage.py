"""SQLite storage. Only completed turns become model context."""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app, g


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db(app):
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                specialty TEXT NOT NULL DEFAULT 'general',
                revision INTEGER NOT NULL DEFAULT 0,
                generation TEXT,
                generation_started REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                attachment_name TEXT,
                attachment_text TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_conversation
                ON messages(conversation_id, id);
            CREATE TABLE IF NOT EXISTS ratings (
                message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
                score INTEGER CHECK(score IN (-1, 1)),
                comment TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
        """)
        db.commit()
        _migrate_history(app, db)
        with db:
            if "answer_level" not in {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}:
                db.execute("ALTER TABLE conversations ADD COLUMN answer_level TEXT NOT NULL DEFAULT 'intermediate'")
            if "reasons" not in {row["name"] for row in db.execute("PRAGMA table_info(ratings)")}:
                db.execute("ALTER TABLE ratings ADD COLUMN reasons TEXT NOT NULL DEFAULT '[]'")
        db.executescript("""
            CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(owner, updated_at);
            CREATE TABLE IF NOT EXISTS browser_state (
                owner TEXT PRIMARY KEY,
                active_conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL
            );
            INSERT OR IGNORE INTO browser_state(owner, active_conversation_id)
                SELECT owner, id FROM conversations ORDER BY updated_at DESC, rowid DESC;
        """)
        db.commit()


def _migrate_history(app, db):
    """Remove the legacy one-chat-per-owner constraint without changing IDs or children."""
    indexes = db.execute("PRAGMA index_list(conversations)").fetchall()
    legacy = any(index["unique"] and [row["name"] for row in db.execute(
        "SELECT name FROM pragma_index_info(?)", (index["name"],)
    )] == ["owner"] for index in indexes)
    if not legacy:
        return
    backup_path = Path(app.config["DATABASE"]).with_suffix(".before-history.sqlite3")
    if not backup_path.exists():
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE conversations_history (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                specialty TEXT NOT NULL DEFAULT 'general', revision INTEGER NOT NULL DEFAULT 0,
                generation TEXT, generation_started REAL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            INSERT INTO conversations_history
                SELECT c.id, c.owner, c.specialty, c.revision, c.generation,
                       c.generation_started, c.created_at,
                       COALESCE((SELECT MAX(m.created_at) FROM messages m
                                 WHERE m.conversation_id = c.id), c.created_at)
                FROM conversations c
        """)
        db.execute("DROP TABLE conversations")
        db.execute("ALTER TABLE conversations_history RENAME TO conversations")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("Conversation migration failed its foreign-key check")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_conversation(owner, specialty="general", answer_level="intermediate"):
    db = get_db()
    conversation_id = uuid4().hex
    now = timestamp()
    with db:
        db.execute(
            "INSERT INTO conversations(id, owner, specialty, answer_level, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, owner, specialty, answer_level, now, now),
        )
        db.execute(
            "INSERT INTO browser_state(owner, active_conversation_id) VALUES (?, ?) "
            "ON CONFLICT(owner) DO UPDATE SET active_conversation_id = excluded.active_conversation_id",
            (owner, conversation_id),
        )
    return conversation_for(owner, conversation_id)


def conversation_for(owner, conversation_id=None):
    db = get_db()
    if conversation_id is not None:
        return db.execute("SELECT * FROM conversations WHERE owner = ? AND id = ?",
                          (owner, conversation_id)).fetchone()
    active = db.execute(
        "SELECT c.* FROM browser_state b JOIN conversations c ON c.id = b.active_conversation_id "
        "WHERE b.owner = ? AND c.owner = ?", (owner, owner),
    ).fetchone()
    if active:
        return active
    latest = db.execute(
        "SELECT * FROM conversations WHERE owner = ? ORDER BY updated_at DESC, rowid DESC LIMIT 1",
        (owner,),
    ).fetchone()
    if latest:
        select_conversation(owner, latest["id"])
        return latest
    return create_conversation(owner)


def select_conversation(owner, conversation_id, previous_id=None):
    db = get_db()
    conversation = conversation_for(owner, conversation_id)
    if conversation is None:
        return None
    with db:
        if previous_id and previous_id != conversation_id:
            db.execute(
                "UPDATE conversations SET generation = NULL, generation_started = NULL WHERE owner = ? AND id = ?",
                (owner, previous_id),
            )
        db.execute(
            "INSERT INTO browser_state(owner, active_conversation_id) VALUES (?, ?) "
            "ON CONFLICT(owner) DO UPDATE SET active_conversation_id = excluded.active_conversation_id",
            (owner, conversation_id),
        )
    return conversation


def conversations_for(owner):
    rows = get_db().execute("""
        SELECT c.id, c.specialty, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.role = 'assistant') AS exchange_count,
               (SELECT content FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY id LIMIT 1) AS first_message,
               (SELECT attachment_name FROM messages m WHERE m.conversation_id = c.id AND m.role = 'user' ORDER BY id LIMIT 1) AS filename
        FROM conversations c WHERE c.owner = ? ORDER BY c.updated_at DESC, c.rowid DESC
    """, (owner,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        first = item.pop("first_message")
        filename = item.pop("filename")
        title = f"Résumé : {filename}" if filename else " ".join((first or "Nouvelle conversation").split())
        item["title"] = title[:57] + "…" if len(title) > 60 else title
        result.append(item)
    return result


def delete_conversation(owner, conversation_id):
    db = get_db()
    with db:
        result = db.execute("DELETE FROM conversations WHERE owner = ? AND id = ?", (owner, conversation_id))
    return bool(result.rowcount)


def messages_for(conversation_id, include_source=False):
    columns = "m.*" if include_source else (
        "m.id, m.role, m.content, m.attachment_name, m.created_at"
    )
    rows = get_db().execute(
        f"SELECT {columns}, r.score, r.comment, r.reasons FROM messages m "
        "LEFT JOIN ratings r ON r.message_id = m.id "
        "WHERE m.conversation_id = ? ORDER BY m.id", (conversation_id,),
    ).fetchall()
    messages = []
    for row in rows:
        message = dict(row)
        message["reasons"] = json.loads(message["reasons"] or "[]")
        messages.append(message)
    return messages


def claim_turn(conversation_id):
    """A lease prevents concurrent tabs from interleaving two turns."""
    import time

    db = get_db()
    token = uuid4().hex
    now = time.time()
    with db:
        result = db.execute(
            "UPDATE conversations SET generation = ?, generation_started = ? "
            "WHERE id = ? AND (generation IS NULL OR generation_started < ?)",
            (token, now, conversation_id, now - 180),
        )
    return token if result.rowcount else None


def release_turn(conversation_id, token):
    db = get_db()
    with db:
        db.execute(
            "UPDATE conversations SET generation = NULL, generation_started = NULL "
            "WHERE id = ? AND generation = ?", (conversation_id, token),
        )


def cancel_turn(conversation_id):
    db = get_db()
    with db:
        db.execute("UPDATE conversations SET generation = NULL, generation_started = NULL WHERE id = ?", (conversation_id,))


def save_turn(conversation_id, token, question, answer, filename=None, source=None):
    db = get_db()
    with db:
        active = db.execute(
            "UPDATE conversations SET generation = NULL, generation_started = NULL, updated_at = ? "
            "WHERE id = ? AND generation = ?", (timestamp(), conversation_id, token),
        )
        if not active.rowcount:
            return None  # A clear or a newer request invalidated this generation.
        now = timestamp()
        db.execute(
            "INSERT INTO messages(conversation_id, role, content, attachment_name, "
            "attachment_text, created_at) VALUES (?, 'user', ?, ?, ?, ?)",
            (conversation_id, question, filename, source, now),
        )
        result = db.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) "
            "VALUES (?, 'assistant', ?, ?)", (conversation_id, answer, now),
        )
    return result.lastrowid


def clear_conversation(conversation_id):
    db = get_db()
    with db:
        db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        db.execute(
            "UPDATE conversations SET revision = revision + 1, generation = NULL, "
            "generation_started = NULL, updated_at = ? WHERE id = ?",
            (timestamp(), conversation_id),
        )
