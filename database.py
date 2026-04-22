import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
from dotenv import load_dotenv

from config.settings import get_settings
from crypto import encrypt_sensitive_data, decrypt_sensitive_data

# Загружаем .env файл
load_dotenv()

settings = get_settings()
DB_PATH = str(settings.db_path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db() -> None:
    settings.data_path.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                original_path TEXT,
                anonymized_path TEXT,
                anonymized_text TEXT,
                anonymization_log TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing'
            );

            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                tool_calls_trace TEXT
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chat_id TEXT,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                file_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.commit()
        await _ensure_messages_tool_trace_column(db)


async def _ensure_messages_tool_trace_column(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(messages)") as cur:
        rows = await cur.fetchall()
    col_names = {row[1] for row in rows}
    if "tool_calls_trace" not in col_names:
        await db.execute("ALTER TABLE messages ADD COLUMN tool_calls_trace TEXT")
        await db.commit()


# ── Projects ──────────────────────────────────────────────────────────────────

async def create_project(db: aiosqlite.Connection, name: str, goal: str) -> dict:
    now = _now()
    pid = _new_id()
    await db.execute(
        "INSERT INTO projects (id, name, goal, created_at, updated_at) VALUES (?,?,?,?,?)",
        (pid, name, goal, now, now),
    )
    await db.commit()
    return await get_project(db, pid)


async def get_project(db: aiosqlite.Connection, project_id: str) -> dict | None:
    async with db.execute("SELECT * FROM projects WHERE id=?", (project_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_projects(db: aiosqlite.Connection) -> list[dict]:
    async with db.execute("SELECT * FROM projects ORDER BY created_at DESC") as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_project(db: aiosqlite.Connection, project_id: str) -> None:
    await db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    await db.commit()


async def update_project(db: aiosqlite.Connection, project_id: str, name: str, goal: str) -> dict | None:
    await db.execute(
        "UPDATE projects SET name=?, goal=?, updated_at=? WHERE id=?",
        (name, goal, _now(), project_id),
    )
    await db.commit()
    return await get_project(db, project_id)


# ── Documents ─────────────────────────────────────────────────────────────────

async def add_document(
    db: aiosqlite.Connection,
    project_id: str,
    name: str,
    description: str,
    filename: str,
    file_type: str,
    original_path: str,
) -> dict:
    did = _new_id()
    await db.execute(
        """INSERT INTO documents
           (id, project_id, name, description, filename, file_type, original_path, created_at, status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (did, project_id, name, description, filename, file_type, original_path, _now(), "processing"),
    )
    await db.commit()
    return await get_document(db, did)


async def get_document(db: aiosqlite.Connection, doc_id: str) -> dict | None:
    async with db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    # Безопасный парсинг anonymization_log
    if d.get("anonymization_log"):
        try:
            d["anonymization_log"] = json.loads(d["anonymization_log"])
        except json.JSONDecodeError:
            # Если не JSON, оставляем как строку
            d["anonymization_log"] = d["anonymization_log"]
    else:
        d["anonymization_log"] = []
    return d


async def list_documents(db: aiosqlite.Connection, project_id: str) -> list[dict]:
    async with db.execute(
        "SELECT * FROM documents WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Безопасный парсинг anonymization_log
        if d.get("anonymization_log"):
            try:
                d["anonymization_log"] = json.loads(d["anonymization_log"])
            except json.JSONDecodeError:
                # Если не JSON, оставляем как строку
                d["anonymization_log"] = d["anonymization_log"]
        else:
            d["anonymization_log"] = []
        result.append(d)
    return result


async def delete_document(db: aiosqlite.Connection, doc_id: str) -> None:
    await db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    await db.commit()


async def count_documents(db: aiosqlite.Connection, project_id: str) -> int:
    """Подсчет общего количества документов в проекте"""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM documents WHERE project_id=?",
        (project_id,)
    )
    result = await cursor.fetchone()
    return result[0] if result else 0


async def list_documents_paginated(
    db: aiosqlite.Connection, 
    project_id: str, 
    offset: int, 
    limit: int
) -> list[dict]:
    """Получение документов с пагинацией"""
    cursor = await db.execute(
        """SELECT id, project_id, name, description, filename, file_type,
                  original_path, anonymized_path, anonymized_text, anonymization_log,
                  created_at, status
           FROM documents 
           WHERE project_id=?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (project_id, limit, offset)
    )
    
    rows = await cursor.fetchall()
    documents = []
    
    for row in rows:
        doc = dict(row)
        # Парсим JSON поля
        if doc.get("anonymization_log"):
            try:
                doc["anonymization_log"] = json.loads(doc["anonymization_log"])
            except (json.JSONDecodeError, TypeError):
                doc["anonymization_log"] = None
        
        documents.append(doc)
    
    return documents


async def update_document_status(
    db: aiosqlite.Connection,
    doc_id: str,
    status: str,
    anonymized_path: str | None = None,
    anonymized_text: str | None = None,
    anonymization_log: list | None = None,
) -> None:
    log_json = json.dumps(anonymization_log) if anonymization_log is not None else None
    await db.execute(
        """UPDATE documents
           SET status=?, anonymized_path=?, anonymized_text=?, anonymization_log=?
           WHERE id=?""",
        (status, anonymized_path, anonymized_text, log_json, doc_id),
    )
    await db.commit()


# ── Chats ─────────────────────────────────────────────────────────────────────

async def create_chat(db: aiosqlite.Connection, project_id: str, name: str) -> dict:
    cid = _new_id()
    await db.execute(
        "INSERT INTO chats (id, project_id, name, created_at) VALUES (?,?,?,?)",
        (cid, project_id, name, _now()),
    )
    await db.commit()
    return await get_chat(db, cid)


async def get_chat(db: aiosqlite.Connection, chat_id: str) -> dict | None:
    async with db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_chats(db: aiosqlite.Connection, project_id: str) -> list[dict]:
    async with db.execute(
        "SELECT * FROM chats WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_chat(db: aiosqlite.Connection, chat_id: str) -> None:
    await db.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    await db.commit()


# ── Messages ──────────────────────────────────────────────────────────────────

async def add_message(
    db: aiosqlite.Connection,
    chat_id: str,
    role: str,
    content: str,
    tool_calls_trace: str | None = None,
) -> dict:
    mid = _new_id()
    await db.execute(
        "INSERT INTO messages (id, chat_id, role, content, created_at, tool_calls_trace) VALUES (?,?,?,?,?,?)",
        (mid, chat_id, role, content, _now(), tool_calls_trace),
    )
    await db.commit()
    async with db.execute("SELECT * FROM messages WHERE id=?", (mid,)) as cur:
        row = await cur.fetchone()
    return _parse_message_row(row)


def _parse_message_row(row: aiosqlite.Row) -> dict:
    d = dict(row)
    raw_trace = d.get("tool_calls_trace")
    if raw_trace:
        try:
            d["tool_calls_trace"] = json.loads(raw_trace)
        except (json.JSONDecodeError, TypeError):
            d["tool_calls_trace"] = None
    else:
        d["tool_calls_trace"] = None
    return d


async def get_messages(db: aiosqlite.Connection, chat_id: str) -> list[dict]:
    async with db.execute(
        "SELECT * FROM messages WHERE chat_id=? ORDER BY created_at ASC", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [_parse_message_row(r) for r in rows]


async def count_messages(db: aiosqlite.Connection, chat_id: str) -> int:
    """Подсчет общего количества сообщений в чате"""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id=?",
        (chat_id,)
    )
    result = await cursor.fetchone()
    return result[0] if result else 0


async def get_messages_paginated(
    db: aiosqlite.Connection, 
    chat_id: str, 
    offset: int, 
    limit: int
) -> list[dict]:
    """Получение сообщений с пагинацией"""
    cursor = await db.execute(
        """SELECT * FROM messages 
           WHERE chat_id=? 
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (chat_id, limit, offset)
    )
    
    rows = await cursor.fetchall()
    return [_parse_message_row(r) for r in rows]


# ── Artifacts ─────────────────────────────────────────────────────────────────

async def save_artifact(
    db: aiosqlite.Connection,
    project_id: str,
    chat_id: str | None,
    name: str,
    content: str,
    file_path: str | None = None,
) -> dict:
    aid = _new_id()
    await db.execute(
        "INSERT INTO artifacts (id, project_id, chat_id, name, content, file_path, created_at) VALUES (?,?,?,?,?,?,?)",
        (aid, project_id, chat_id, name, content, file_path, _now()),
    )
    await db.commit()
    async with db.execute("SELECT * FROM artifacts WHERE id=?", (aid,)) as cur:
        row = await cur.fetchone()
    return dict(row)


async def list_artifacts(db: aiosqlite.Connection, project_id: str) -> list[dict]:
    async with db.execute(
        "SELECT * FROM artifacts WHERE project_id=? ORDER BY created_at DESC", (project_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_artifact(db: aiosqlite.Connection, artifact_id: str) -> None:
    await db.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
    await db.commit()


# ── App settings ──────────────────────────────────────────────────────────────

async def get_setting(db: aiosqlite.Connection, key: str, decrypt: bool = True) -> str | None:
    """
    Получает настройку из базы данных.
    
    Args:
        db: Соединение с базой данных
        key: Ключ настройки
        decrypt: Нужно ли дешифровать значение (по умолчанию True)
    
    Returns:
        Значение настройки или None если не найдено
    """
    async with db.execute("SELECT value FROM app_settings WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    
    if row:
        value = row[0]
        if decrypt:
            return decrypt_sensitive_data(key, value)
        return value
    return None


async def set_setting(db: aiosqlite.Connection, key: str, value: str, encrypt: bool = True) -> None:
    """
    Сохраняет настройку в базу данных.
    
    Args:
        db: Соединение с базой данных
        key: Ключ настройки
        value: Значение настройки
        encrypt: Нужно ли шифровать значение (по умолчанию True)
    """
    value_to_store = encrypt_sensitive_data(key, value) if encrypt else value
    
    await db.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value_to_store),
    )
    await db.commit()


async def get_all_settings(db: aiosqlite.Connection, decrypt: bool = True) -> dict:
    """
    Получает все настройки из базы данных.
    
    Args:
        db: Соединение с базой данных
        decrypt: Нужно ли дешифровать значения
    
    Returns:
        Словарь всех настроек
    """
    settings = {}
    async with db.execute("SELECT key, value FROM app_settings") as cur:
        rows = await cur.fetchall()
        for row in rows:
            key = row[0]
            value = row[1]
            if decrypt:
                settings[key] = decrypt_sensitive_data(key, value)
            else:
                settings[key] = value
    return settings
