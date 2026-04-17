"""
ProjectChat — FastAPI application entry point.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
import secrets
from base64 import b64decode
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import aiosqlite
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from ai_client import AIClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
from anonymizer import anonymize
from config.settings import Settings, get_settings
from database import (
    DB_PATH,
    add_document,
    add_message,
    create_chat,
    create_project,
    delete_artifact,
    delete_chat,
    delete_document,
    delete_project,
    get_chat,
    get_document,
    get_db,
    get_messages,
    get_project,
    get_setting,
    init_db,
    list_artifacts,
    list_chats,
    list_documents,
    list_projects,
    save_artifact,
    set_setting,
    update_document_status,
    update_project,
)
from file_parser import extract_text

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_DOC_CHARS = 200_000
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

settings: Settings = get_settings()

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

async def validate_api_key(provider: str, api_key: str) -> bool:
    """Validate API key by making a test request to the provider."""
    import httpx
    
    logger.info(f"Validating {provider} API key...")
    
    if not api_key or not api_key.startswith(("sk-", "sk-or-")):
        logger.warning(f"Invalid API key format for {provider}")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "openrouter":
                url = "https://openrouter.ai/api/v1/models"
                logger.debug(f"Testing OpenRouter key at {url}")
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"}
                )
            else:  # deepseek
                url = "https://api.deepseek.com/models"
                logger.debug(f"Testing DeepSeek key at {url}")
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"}
                )
            
            logger.info(f"{provider} API key validation: HTTP {response.status_code}")
            if response.status_code != 200:
                # Log only status and brief error message, not full response
                error_msg = response.text[:50] if response.text else "No error message"
                logger.warning(f"{provider} API key validation failed (HTTP {response.status_code}): {error_msg}")
            
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Error validating {provider} API key: {str(e)}")
        return False


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    
    # Загружаем настройки из базы данных при старте
    effective_settings = await _get_effective_settings()
    startup_settings = Settings(
        AI_PROVIDER=effective_settings["AI_PROVIDER"],
        OPENROUTER_API_KEY=effective_settings["OPENROUTER_API_KEY"],
        OPENROUTER_MODEL=effective_settings["OPENROUTER_MODEL"],
        DEEPSEEK_API_KEY=effective_settings["DEEPSEEK_API_KEY"],
        DEEPSEEK_MODEL=effective_settings["DEEPSEEK_MODEL"],
        PORT=settings.PORT,
        DATA_PATH=settings.DATA_PATH,
    )
    app.state.ai_client = AIClient(startup_settings)
    logger.info(f"AI client initialized with provider: {startup_settings.AI_PROVIDER}, model: {startup_settings.OPENROUTER_MODEL if startup_settings.AI_PROVIDER == 'openrouter' else startup_settings.DEEPSEEK_MODEL}")
    
    yield
    await app.state.ai_client.close()


app = FastAPI(title="ProjectChat", lifespan=lifespan)

# Настройка CORS
cors_origins = []
if settings.CORS_ALLOW_ORIGINS:
    cors_origins = [origin.strip() for origin in settings.CORS_ALLOW_ORIGINS.split(",")]
else:
    cors_origins = ["*"]  # Fallback для совместимости

# Middleware для обработки OPTIONS запросов (должен быть ПЕРЕД CORSMiddleware)
@app.middleware("http")
async def options_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=204)
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

security = HTTPBasic()

# ── Аутентификация ───────────────────────────────────────────────────────────

async def check_auth(request: Request) -> bool:
    if not settings.AUTH_ENABLED:
        logger.debug("Аутентификация отключена, пропускаем проверку")
        return True
    
    # Пытаемся получить credentials
    try:
        credentials = await security(request)
    except HTTPException as e:
        # Если credentials не предоставлены
        if not settings.AUTH_ENABLED:
            # Если аутентификация отключена, игнорируем ошибку
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Если credentials = None (не предоставлены)
    if credentials is None:
        if not settings.AUTH_ENABLED:
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    if not settings.AUTH_PASSWORD:
        logger.warning("Аутентификация включена, но пароль не установлен в .env")
        return True
    
    correct_username = secrets.compare_digest(credentials.username, settings.AUTH_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.AUTH_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учетные данные",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return True

AuthDep = Annotated[bool, Depends(check_auth)]

# ── Helpers ───────────────────────────────────────────────────────────────────

DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]


def _mask_key(key: str) -> str:
    if not key or len(key) < 4:
        return "****"
    return "****" + key[-4:]


def _project_dir(project_id: str) -> Path:
    return settings.data_path / "projects" / project_id


def build_system_prompt(project: dict, documents: list[dict]) -> str:
    ready_docs = [d for d in documents if d.get("status") == "ready"]
    docs_context = "\n\n".join(
        f"### {d['name']}\nКонтекст: {d.get('description') or '—'}\n\n"
        f"{(d.get('anonymized_text') or '')[:MAX_DOC_CHARS]}"
        for d in ready_docs
    )
    docs_section = docs_context if docs_context else "(документы не загружены)"
    return (
        "Ты AI-ассистент, работающий в рамках проекта.\n\n"
        f"ПРОЕКТ: {project['name']}\n"
        f"ЦЕЛЬ ПРОЕКТА: {project.get('goal') or '—'}\n\n"
        "ЗАГРУЖЕННЫЕ ДОКУМЕНТЫ:\n"
        f"{docs_section}\n\n"
        "Используй информацию из документов при ответах. "
        "Если просят сохранить результат — сообщи об этом явно."
    )


async def _get_effective_settings() -> dict:
    """Merge DB overrides on top of env-based settings."""
    result = {
        "AI_PROVIDER": settings.AI_PROVIDER,
        "OPENROUTER_MODEL": settings.OPENROUTER_MODEL,
        "DEEPSEEK_MODEL": settings.DEEPSEEK_MODEL,
        "OPENROUTER_API_KEY": settings.OPENROUTER_API_KEY,
        "DEEPSEEK_API_KEY": settings.DEEPSEEK_API_KEY,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key in result:
            val = await get_setting(db, key)
            if val is not None:
                result[key] = val
    return result


async def _rebuild_ai_client(app_state) -> None:
    """Re-instantiate AIClient from current effective settings."""
    effective = await _get_effective_settings()
    new_settings = Settings(
        AI_PROVIDER=effective["AI_PROVIDER"],
        OPENROUTER_API_KEY=effective["OPENROUTER_API_KEY"],
        OPENROUTER_MODEL=effective["OPENROUTER_MODEL"],
        DEEPSEEK_API_KEY=effective["DEEPSEEK_API_KEY"],
        DEEPSEEK_MODEL=effective["DEEPSEEK_MODEL"],
        PORT=settings.PORT,
        DATA_PATH=settings.DATA_PATH,
    )
    old_client: AIClient = app_state.ai_client
    app_state.ai_client = AIClient(new_settings)
    await old_client.close()


# ── Background task ───────────────────────────────────────────────────────────

async def process_document(doc_id: str, original_path: str, file_type: str) -> None:
    """Parse and anonymize a document. Runs after the upload request completes."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        try:
            text = extract_text(original_path, file_type)
            anon_text, log = anonymize(text)

            orig_path = Path(original_path)
            anon_dir = orig_path.parent.parent / "anonymized"
            anon_dir.mkdir(parents=True, exist_ok=True)
            anon_path = anon_dir / orig_path.name
            anon_path.write_text(anon_text, encoding="utf-8")

            await update_document_status(
                db,
                doc_id,
                "ready",
                anonymized_path=str(anon_path),
                anonymized_text=anon_text,
                anonymization_log=log,
            )
        except Exception as e:
            print(f"[process_document] Error for doc {doc_id}: {e}")
            await update_document_status(db, doc_id, "error")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    response = FileResponse("static/index.html")
    # Упрощенные заголовки Content-Security-Policy для тестирования
    response.headers["Content-Security-Policy"] = (
        "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
        "script-src * 'unsafe-inline' 'unsafe-eval' blob: data:; "
        "style-src * 'unsafe-inline'; "
        "connect-src *;"
    )
    return response


@app.get("/api/health")
async def health(request: Request, auth: AuthDep):
    ai: AIClient = request.app.state.ai_client
    return {"status": "ok", "provider": ai.provider, "model": ai.model, "auth_enabled": settings.AUTH_ENABLED}


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    goal: str = ""


class ProjectUpdate(BaseModel):
    name: str
    goal: str = ""


@app.get("/api/projects")
async def get_projects(db: DbDep, auth: AuthDep):
    return await list_projects(db)


@app.post("/api/projects", status_code=201)
async def create_new_project(body: ProjectCreate, db: DbDep, auth: AuthDep):
    project = await create_project(db, body.name, body.goal)
    project_dir = _project_dir(project["id"])
    for sub in ("original", "anonymized", "artifacts"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    return project


@app.get("/api/projects/{project_id}")
async def get_project_detail(project_id: str, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    documents = await list_documents(db, project_id)
    chats = await list_chats(db, project_id)
    artifacts = await list_artifacts(db, project_id)
    return {**project, "documents": documents, "chats": chats, "artifacts": artifacts}


@app.put("/api/projects/{project_id}")
async def update_project_detail(project_id: str, body: ProjectUpdate, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await update_project(db, project_id, body.name, body.goal)


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await delete_project(db, project_id)
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)
    return {"ok": True}


# ── Documents ─────────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/documents", status_code=201)
async def upload_document(
    project_id: str,
    db: DbDep,
    auth: AuthDep,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    anonymized_text: str = Form(""),
    anonymization_map: str = Form(""),
):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Validate extension
    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read and size-check
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "File too large (max 50 MB)")

    # Save original file
    orig_dir = _project_dir(project_id) / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}_{filename}"
    orig_path = orig_dir / safe_name
    orig_path.write_bytes(content)

    # Parse anonymization map
    anonymization_log = ""
    try:
        if anonymization_map:
            map_data = json.loads(anonymization_map)
            anonymization_log = json.dumps({
                "map": map_data,
                "anonymized_text_length": len(anonymized_text),
                "original_text_length": len(anonymized_text)  # Приблизительно
            })
    except json.JSONDecodeError:
        anonymization_log = json.dumps({"error": "Invalid anonymization map"})

    # Create DB record with anonymized text
    async with aiosqlite.connect(DB_PATH) as raw_db:
        raw_db.row_factory = aiosqlite.Row
        await raw_db.execute("""
            INSERT INTO documents 
            (id, project_id, name, description, filename, file_type, original_path, 
             anonymized_text, anonymization_log, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_id, project_id, name, description, filename, ext, str(orig_path),
            anonymized_text, anonymization_log, _now(), "ready"
        ))
        await raw_db.commit()

    # Get the created document
    async with aiosqlite.connect(DB_PATH) as raw_db:
        raw_db.row_factory = aiosqlite.Row
        async with raw_db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)) as cursor:
            row = await cursor.fetchone()
            doc = dict(row) if row else None

    return doc


@app.get("/api/projects/{project_id}/documents")
async def get_documents(project_id: str, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_documents(db, project_id)


@app.get("/api/projects/{project_id}/documents/paginated")
async def get_documents_paginated(
    project_id: str, 
    db: DbDep, 
    auth: AuthDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Получаем общее количество документов
    total = await count_documents(db, project_id)
    
    # Рассчитываем offset
    offset = (page - 1) * page_size
    
    # Получаем документы для страницы
    documents = await list_documents_paginated(db, project_id, offset, page_size)
    
    return {
        "documents": documents,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@app.get("/api/projects/{project_id}/documents/{doc_id}")
async def get_document_detail(project_id: str, doc_id: str, db: DbDep, auth: AuthDep):
    doc = await get_document(db, doc_id)
    if not doc or doc["project_id"] != project_id:
        raise HTTPException(404, "Document not found")
    return doc


@app.delete("/api/projects/{project_id}/documents/{doc_id}")
async def remove_document(project_id: str, doc_id: str, db: DbDep, auth: AuthDep):
    doc = await get_document(db, doc_id)
    if not doc or doc["project_id"] != project_id:
        raise HTTPException(404, "Document not found")
    await delete_document(db, doc_id)
    for path_key in ("original_path", "anonymized_path"):
        p = doc.get(path_key)
        if p and Path(p).exists():
            Path(p).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/documents/{doc_id}/preview")
async def preview_document(doc_id: str, db: DbDep, auth: AuthDep):
    """Get document preview with content"""
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    
    content = ""
    anonymization_log = doc.get("anonymization_log", "")
    file_type = doc.get("file_type", "unknown").lower()
    
    # First, try to use anonymized_text if available
    if doc.get("anonymized_text"):
        content = doc["anonymized_text"]
    # For binary files (pdf, docx, etc.), don't try to read them as text
    elif file_type in ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]:
        content = f"[Binary file: {file_type.upper()}. Use anonymized_text field for content.]"
    elif doc.get("anonymized_path") and Path(doc["anonymized_path"]).exists():
        try:
            with open(doc["anonymized_path"], "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {str(e)}"
    elif doc.get("original_path") and Path(doc["original_path"]).exists():
        try:
            with open(doc["original_path"], "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {str(e)}"
    
    return {
        "id": doc["id"],
        "name": doc["name"],
        "file_type": doc.get("file_type", "unknown"),
        "size": doc.get("size", 0),
        "created_at": doc["created_at"],
        "status": doc.get("status", "ready"),
        "content": content[:5000],  # Limit preview size
        "anonymization_log": anonymization_log
    }


@app.get("/api/documents/{doc_id}/pii-stats")
async def get_pii_statistics(doc_id: str, db: DbDep, auth: AuthDep):
    """Get PII statistics for a document"""
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    
    # Try to parse anonymization log for statistics
    stats = {}
    anonymization_log = doc.get("anonymization_log", "")
    
    if anonymization_log:
        try:
            # Check if anonymization_log is already a dict
            if isinstance(anonymization_log, dict):
                stats = anonymization_log
            else:
                # Try to parse as JSON string
                stats = json.loads(anonymization_log)
        except (json.JSONDecodeError, TypeError):
            # If not JSON, create simple stats from log
            log_text = str(anonymization_log)
            lines = log_text.split('\n')
            pii_count = 0
            for line in lines:
                if "PII" in line or "anonymized" in line.lower():
                    pii_count += 1
            stats = {"total": pii_count, "log_lines": len(lines)}
    
    # Ensure stats is properly serialized
    stats_json = None
    if stats:
        if isinstance(stats, dict):
            stats_json = json.dumps(stats)
        else:
            stats_json = str(stats)
    
    return {
        "id": doc["id"],
        "name": doc["name"],
        "stats": stats_json
    }


@app.post("/api/documents/{doc_id}/deanonymize")
async def deanonymize_document(doc_id: str, db: DbDep, auth: AuthDep):
    """Restore original text from anonymized document"""
    from anonymizer import deanonymize
    
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    
    anonymized_text = doc.get("anonymized_text", "")
    if not anonymized_text:
        raise HTTPException(400, "Document has no anonymized text")
    
    anonymization_log = doc.get("anonymization_log", "")
    if not anonymization_log:
        raise HTTPException(400, "Document has no anonymization log")
    
    try:
        # Parse the anonymization log (handle both string and already parsed object)
        if isinstance(anonymization_log, dict):
            # If it's a dict, check if it's the log itself or contains the log
            if "log" in anonymization_log and isinstance(anonymization_log["log"], list):
                log = anonymization_log["log"]
            elif isinstance(anonymization_log.get("entries"), list):
                log = anonymization_log["entries"]
            else:
                # Assume it's the log itself if it has the right structure
                log = anonymization_log
        elif isinstance(anonymization_log, list):
            log = anonymization_log
        else:
            # Try to parse as JSON string
            parsed = json.loads(anonymization_log)
            if isinstance(parsed, dict) and "log" in parsed and isinstance(parsed["log"], list):
                log = parsed["log"]
            elif isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
                log = parsed["entries"]
            elif isinstance(parsed, list):
                log = parsed
            else:
                log = parsed
        
        # Ensure log is a list for deanonymize function
        if not isinstance(log, list):
            # Try to convert dict to list if it's a single entry
            if isinstance(log, dict):
                log = [log]
            else:
                raise HTTPException(400, f"Anonymization log must be a list, got {type(log).__name__}")
        
        # Type check: ensure all entries in log are dicts
        for i, entry in enumerate(log):
            if not isinstance(entry, dict):
                raise HTTPException(400, f"Log entry {i} must be a dict, got {type(entry).__name__}")
        
        # Restore original text
        original_text = deanonymize(anonymized_text, log)  # type: ignore
        
        return {
            "id": doc["id"],
            "name": doc["name"],
            "original_text": original_text,
            "anonymized_text": anonymized_text,
            "log_entries": len(log)
        }
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(400, f"Invalid anonymization log format: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Error during deanonymization: {str(e)}")


# ── Chats ─────────────────────────────────────────────────────────────────────

class ChatCreate(BaseModel):
    name: str = "Новый чат"


@app.post("/api/projects/{project_id}/chats", status_code=201)
async def create_new_chat(project_id: str, body: ChatCreate, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await create_chat(db, project_id, body.name)


@app.get("/api/projects/{project_id}/chats")
async def get_chats(project_id: str, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_chats(db, project_id)


@app.delete("/api/projects/{project_id}/chats/{chat_id}")
async def remove_chat(project_id: str, chat_id: str, db: DbDep, auth: AuthDep):
    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")
    await delete_chat(db, chat_id)
    return {"ok": True}


# ── Messages ──────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/chats/{chat_id}/messages")
async def get_chat_messages(project_id: str, chat_id: str, db: DbDep, auth: AuthDep):
    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")
    return await get_messages(db, chat_id)


@app.get("/api/projects/{project_id}/chats/{chat_id}/messages/paginated")
async def get_chat_messages_paginated(
    project_id: str, 
    chat_id: str, 
    db: DbDep, 
    auth: AuthDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")
    
    # Получаем общее количество сообщений
    total = await count_messages(db, chat_id)
    
    # Рассчитываем offset
    offset = (page - 1) * page_size
    
    # Получаем сообщения для страницы
    messages = await get_messages_paginated(db, chat_id, offset, page_size)
    
    return {
        "messages": messages,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


class MessageRequest(BaseModel):
    content: str
    selected_document_ids: list[str] | None = None


@app.post("/api/projects/{project_id}/chats/{chat_id}/messages")
async def send_message(
    project_id: str,
    chat_id: str,
    body: MessageRequest,
    request: Request,
    db: DbDep,
    auth: AuthDep,
):
    logger.info(f"Sending message to chat {chat_id} in project {project_id}")
    
    project = await get_project(db, project_id)
    if not project:
        logger.warning(f"Project {project_id} not found")
        raise HTTPException(404, "Project not found")

    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        logger.warning(f"Chat {chat_id} not found or doesn't belong to project {project_id}")
        raise HTTPException(404, "Chat not found")

    documents = await list_documents(db, project_id)
    history = await get_messages(db, chat_id)
    
    logger.info(f"Found {len(documents)} documents and {len(history)} previous messages for chat")

    # Фильтруем документы если указаны выбранные
    filtered_docs = documents
    if body.selected_document_ids:
        filtered_docs = [d for d in documents if d["id"] in body.selected_document_ids]
        logger.info(f"Using {len(filtered_docs)} selected documents out of {len(documents)} total")
    
    system_prompt = build_system_prompt(project, filtered_docs)
    logger.debug(f"System prompt length: {len(system_prompt)}")

    # Persist user message using the provided db connection
    await add_message(db, chat_id, "user", body.content)
    logger.info(f"Saved user message to chat {chat_id}")

    # Build messages for AI
    ai_messages = [{"role": m["role"], "content": m["content"]} for m in history]
    ai_messages.append({"role": "user", "content": body.content})
    
    logger.info(f"Sending {len(ai_messages)} messages to AI, user message length: {len(body.content)}")

    ai_client: AIClient = request.app.state.ai_client
    logger.info(f"Using AI provider: {ai_client.provider}, model: {ai_client.model}")

    async def event_generator():
        full_response = ""
        try:
            logger.info("Starting AI stream")
            async for chunk in ai_client.stream_chat(ai_messages, system_prompt, request):
                if await request.is_disconnected():
                    logger.info("Client disconnected, stopping stream")
                    break
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            
            logger.info(f"AI stream completed, total response length: {len(full_response)}")
            
        except Exception as e:
            error_msg = f"Ошибка AI: {str(e)}"
            logger.error(f"Error in AI stream: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            full_response = error_msg

        # Persist assistant reply using a new connection (since we're in a generator)
        try:
            async with aiosqlite.connect(DB_PATH) as raw_db:
                raw_db.row_factory = aiosqlite.Row
                await add_message(raw_db, chat_id, "assistant", full_response)
                logger.info(f"Saved assistant response to chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to save assistant response: {str(e)}")

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Artifacts ─────────────────────────────────────────────────────────────────

class ArtifactCreate(BaseModel):
    name: str
    content: str
    chat_id: str | None = None


@app.post("/api/projects/{project_id}/artifacts", status_code=201)
async def create_artifact(project_id: str, body: ArtifactCreate, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    artifacts_dir = _project_dir(project_id) / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifact = await save_artifact(db, project_id, body.chat_id, body.name, body.content)

    # Write artifact to file
    safe_filename = "".join(c if c.isalnum() or c in "-_ " else "_" for c in body.name)
    file_path = artifacts_dir / f"{artifact['id']}_{safe_filename}.txt"
    file_path.write_text(body.content, encoding="utf-8")

    async with aiosqlite.connect(DB_PATH) as raw_db:
        await raw_db.execute(
            "UPDATE artifacts SET file_path=? WHERE id=?",
            (str(file_path), artifact["id"]),
        )
        await raw_db.commit()

    artifact["file_path"] = str(file_path)
    return artifact


@app.get("/api/projects/{project_id}/artifacts")
async def get_artifacts(project_id: str, db: DbDep, auth: AuthDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_artifacts(db, project_id)


@app.delete("/api/projects/{project_id}/artifacts/{artifact_id}")
async def remove_artifact(project_id: str, artifact_id: str, db: DbDep, auth: AuthDep):
    async with aiosqlite.connect(DB_PATH) as raw_db:
        raw_db.row_factory = aiosqlite.Row
        await raw_db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
    await delete_artifact(db, artifact_id)
    return {"ok": True}


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    AI_PROVIDER: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_MODEL: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str | None = None


@app.get("/api/settings")
async def get_app_settings(auth: AuthDep):
    effective = await _get_effective_settings()
    return {
        "AI_PROVIDER": effective["AI_PROVIDER"],
        "OPENROUTER_API_KEY": _mask_key(effective["OPENROUTER_API_KEY"]),
        "OPENROUTER_MODEL": effective["OPENROUTER_MODEL"],
        "DEEPSEEK_API_KEY": _mask_key(effective["DEEPSEEK_API_KEY"]),
        "DEEPSEEK_MODEL": effective["DEEPSEEK_MODEL"],
        "AUTH_ENABLED": settings.AUTH_ENABLED,
    }


@app.post("/api/settings")
async def update_app_settings(body: SettingsUpdate, request: Request, auth: AuthDep):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No settings provided")
    
    # Validate API keys if provided
    if "OPENROUTER_API_KEY" in updates and updates["OPENROUTER_API_KEY"]:
        if not await validate_api_key("openrouter", updates["OPENROUTER_API_KEY"]):
            raise HTTPException(400, "Invalid OpenRouter API key")
    
    if "DEEPSEEK_API_KEY" in updates and updates["DEEPSEEK_API_KEY"]:
        if not await validate_api_key("deepseek", updates["DEEPSEEK_API_KEY"]):
            raise HTTPException(400, "Invalid DeepSeek API key")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for key, value in updates.items():
            await set_setting(db, key, value)

    await _rebuild_ai_client(request.app.state)
    return {"ok": True, "updated": list(updates.keys())}
