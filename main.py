"""
ProjectChat — FastAPI application entry point.
"""
from __future__ import annotations

import json
import logging
import os
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
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from ai_client import AIClient
from config.settings import BASE_DIR, Settings, get_settings

# Настройка логирования
_log_handlers = [logging.StreamHandler()]
try:
    _app_log_path = get_settings().app_log_path
    _app_log_path.parent.mkdir(parents=True, exist_ok=True)
    _log_handlers.insert(0, logging.FileHandler(_app_log_path))
except Exception as exc:
    # Не блокируем старт сервиса, если файловый лог недоступен
    logging.getLogger(__name__).warning(f"File logging disabled: {exc}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=_log_handlers,
)

logger = logging.getLogger(__name__)
from anonymizer import anonymize
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
    get_messages_paginated,
    get_project,
    get_setting,
    init_db,
    list_artifacts,
    list_chats,
    list_documents,
    list_documents_paginated,
    list_projects,
    count_documents,
    count_messages,
    save_artifact,
    set_setting,
    update_document_status,
    update_project,
)
from file_parser import extract_text
from vault import (
    VAULT_SYSTEM_PROMPT,
    VAULT_TOOLS,
    append_chat_log,
    build_tool_trace_entry,
    choose_artifact_path,
    count_markdown_notes,
    dispatch_vault_tool,
    get_vault_tree,
    read_note,
    slugify_text,
    search_notes,
    summarize_trace,
    upsert_artifact_entry,
    update_project_hub_links,
    vault_mtime_iso,
    write_note,
)

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
    if settings.OBSIDIAN_ENABLED:
        settings.obsidian_vault_path.mkdir(parents=True, exist_ok=True)
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

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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


def _is_masked_key(value: str) -> bool:
    v = (value or "").strip()
    return v.startswith("****")


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _project_dir(project_id: str) -> Path:
    return settings.data_path / "projects" / project_id


def _project_vault_key(project: dict) -> str:
    """
    Stable key for vault isolation. Prefer immutable project id.
    """
    return slugify_text(str(project.get("id") or project.get("name") or "project"), fallback="project")


def _is_path_in_scope(path_value: str, scope_prefix: str) -> bool:
    normalized = (path_value or "").strip().strip("/")
    prefix = scope_prefix.strip().strip("/")
    if not normalized:
        return False
    return normalized == prefix or normalized.startswith(prefix + "/")


async def _resolve_project_scope(project_id: str, db: aiosqlite.Connection) -> tuple[dict, str]:
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project, f"Projects/{_project_vault_key(project)}"


def _vault_diagnostics() -> dict:
    env_has_flag = "OBSIDIAN_ENABLED" in os.environ
    env_flag_value = os.getenv("OBSIDIAN_ENABLED", "").strip().lower()
    vault_enabled = bool(settings.OBSIDIAN_ENABLED)
    vault_path = settings.obsidian_vault_path
    vault_path_exists = vault_path.is_dir()
    webdav_expected = vault_enabled
    webdav_url = f"http://localhost:{settings.WEBDAV_PORT}"

    action_steps: list[str] = []
    if not env_has_flag:
        action_steps.append("Добавьте OBSIDIAN_ENABLED=true в .env и перезапустите сервис")
    elif env_flag_value not in {"true", "1", "yes", "on"}:
        action_steps.append("Установите OBSIDIAN_ENABLED=true в .env")
    if vault_enabled and not vault_path_exists:
        action_steps.append(f"Создайте папку vault: {vault_path}")
    if webdav_expected:
        action_steps.append("Запустите docker compose с профилем vault: docker compose --profile vault up -d")
        action_steps.append("В Obsidian Remotely Save укажите URL/логин/пароль WebDAV и нажмите Sync")

    if not action_steps:
        action_steps.append("Vault настроен. Откройте вкладку Vault и проверьте дерево заметок")

    return {
        "vault_config_present": env_has_flag,
        "vault_runtime_enabled": vault_enabled,
        "vault_path_exists": vault_path_exists,
        "webdav_expected": webdav_expected,
        "webdav_container_hint": "docker compose --profile vault up -d",
        "webdav_url_hint": webdav_url,
        "action_hint": "; ".join(action_steps),
        "action_steps": action_steps,
    }


def _detect_artifact_decision(user_text: str, assistant_text: str) -> dict:
    t = (assistant_text or "").lower()
    q = (user_text or "").lower()
    score = 0.0
    artifact_type = "analysis"
    reason_parts: list[str] = []
    title = "AI Artifact"

    def bump(cond: bool, delta: float, why: str) -> None:
        nonlocal score
        if cond:
            score += delta
            reason_parts.append(why)

    bump("## " in assistant_text, 0.15, "есть структура заголовков")
    bump(any(k in t for k in ("риск", "risk")), 0.22, "обнаружена тема рисков")
    bump(any(k in t for k in ("решени", "decision")), 0.20, "обнаружена тема решений")
    bump(any(k in t for k in ("саммари", "summary", "итог")), 0.20, "обнаружена тема summary")
    bump(any(k in q for k in ("проанализ", "анализ", "риск", "решени", "итог")), 0.15, "запрос похож на артефакт")
    bump(len(assistant_text or "") > 900, 0.10, "ответ достаточно содержательный")

    if any(k in t for k in ("риск", "risk")):
        artifact_type = "risks"
        title = "Риски проекта"
    elif any(k in t for k in ("решени", "decision")):
        artifact_type = "decisions"
        title = "Решения проекта"
    elif any(k in t for k in ("саммари", "summary", "итог")):
        artifact_type = "summary"
        title = "Сводка проекта"
    elif any(k in t for k in ("встреч", "meeting")):
        artifact_type = "meeting-notes"
        title = "Заметки встречи"
    else:
        artifact_type = "analysis"
        title = "Анализ"

    score = min(1.0, max(0.0, score))
    threshold = float(settings.VAULT_ARTIFACT_AUTOSAVE_THRESHOLD)
    decision = "write" if score >= threshold else "skip"
    return {
        "artifact_decision": decision,
        "artifact_type": artifact_type,
        "artifact_confidence": round(score, 3),
        "decision_reason": ", ".join(reason_parts) if reason_parts else "недостаточно сигналов",
        "threshold": threshold,
        "title": title,
    }


def _augment_vault_prompt(base_prompt: str, project_scope: str | None = None) -> str:
    budget = (
        "Бюджет навигации: "
        f"файлы<= {settings.VAULT_RETRIEVAL_MAX_FILES}, "
        f"секции<= {settings.VAULT_RETRIEVAL_MAX_SECTIONS}, "
        f"символы<= {settings.VAULT_RETRIEVAL_MAX_CHARS}.\n"
    )
    nav_order = (
        "Порядок навигации обязателен: "
        "get_vault_tree -> list_notes -> get_note_headers -> read_note(section) -> search_notes(только если нужно).\n"
        "Сначала читай _summary.md проекта и профильные заметки, не читай все транскрипты."
    )
    scope_line = ""
    if project_scope:
        scope_line = (
            f"\nОграничение проекта: работай ТОЛЬКО внутри '{project_scope}'. "
            "Не читай и не изменяй заметки других проектов."
        )
    return f"{base_prompt}\n\n{budget}{nav_order}{scope_line}"


def _bootstrap_vault_memory(
    vault_root: Path,
    project_name: str,
    project_key: str,
) -> tuple[str, list[dict], list[str]]:
    """
    Deterministic tree-first bootstrap for new answer generation:
    tree -> list project folder -> read _summary -> list risks -> read one risk.
    Returns memory hint, bootstrap trace calls, and tool result strings.
    """
    project_slug = slugify_text(project_key or project_name or "project", fallback="project")
    steps: list[tuple[str, dict]] = [
        ("get_vault_tree", {}),
        ("list_notes", {"folder": f"Projects/{project_slug}"}),
        ("read_note", {"path": f"Projects/{project_slug}/_summary.md"}),
        ("list_notes", {"folder": f"Projects/{project_slug}/risks"}),
    ]

    trace_calls: list[dict] = []
    results: list[str] = []
    risk_candidate: str | None = None

    for name, args in steps:
        started = _now()
        result = dispatch_vault_tool(vault_root, name, args)
        finished = _now()
        results.append(result)
        trace_calls.append(
            build_tool_trace_entry(
                name,
                args,
                result,
                started_at=started,
                finished_at=finished,
                duration_ms=0,
            )
        )
        if name == "list_notes" and args.get("folder", "").endswith("/risks"):
            try:
                parsed = json.loads(result)
                risk_files = [x.get("path") for x in parsed if isinstance(x, dict) and x.get("type") == "file"]
                if risk_files:
                    risk_candidate = str(risk_files[0])
            except Exception:
                pass

    if risk_candidate:
        started = _now()
        risk_result = dispatch_vault_tool(vault_root, "read_note", {"path": risk_candidate})
        finished = _now()
        results.append(risk_result)
        trace_calls.append(
            build_tool_trace_entry(
                "read_note",
                {"path": risk_candidate},
                risk_result,
                started_at=started,
                finished_at=finished,
                duration_ms=0,
            )
        )

    summary_text = ""
    risk_text = ""
    if len(results) >= 3:
        summary_text = results[2][:3000]
    if risk_candidate and len(results) >= 5:
        risk_text = results[4][:2200]
    memory_hint = (
        "BOOTSTRAP MEMORY (summary-first):\n"
        f"{summary_text}\n\n"
        "BOOTSTRAP RISK NOTE:\n"
        f"{risk_text}\n"
    ).strip()
    return memory_hint, trace_calls, results


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


def _limit_history(messages: list[dict], context_size: str, custom_context_size: int) -> list[dict]:
    """Limit message history to keep provider payload predictable."""
    if not messages:
        return []

    if context_size == "small":
        return messages[-8:]
    if context_size == "medium":
        return messages[-20:]
    if context_size == "large":
        return messages[-40:]
    if context_size == "custom":
        budget = max(500, custom_context_size)
        total = 0
        selected: list[dict] = []
        for msg in reversed(messages):
            content = msg.get("content") or ""
            msg_len = len(content)
            if selected and total + msg_len > budget:
                break
            selected.append(msg)
            total += msg_len
        return list(reversed(selected))
    return messages[-20:]


def _coerce_setting_value(key: str, value):
    if key in {"AI_TEMPERATURE"}:
        try:
            return float(value)
        except Exception:
            return settings.AI_TEMPERATURE
    if key in {"MAX_TOKENS", "CUSTOM_CONTEXT_SIZE"}:
        try:
            return int(value)
        except Exception:
            return getattr(settings, key)
    if key in {"ENABLE_STREAMING", "AUTO_SAVE_ARTIFACTS"}:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    return value


async def _get_effective_settings() -> dict:
    """Merge DB overrides on top of env-based settings."""
    result = {
        "AI_PROVIDER": settings.AI_PROVIDER,
        "OPENROUTER_MODEL": settings.OPENROUTER_MODEL,
        "DEEPSEEK_MODEL": settings.DEEPSEEK_MODEL,
        "OPENROUTER_API_KEY": settings.OPENROUTER_API_KEY,
        "DEEPSEEK_API_KEY": settings.DEEPSEEK_API_KEY,
        "AI_TEMPERATURE": settings.AI_TEMPERATURE,
        "MAX_TOKENS": settings.MAX_TOKENS,
        "CONTEXT_SIZE": settings.CONTEXT_SIZE,
        "CUSTOM_CONTEXT_SIZE": settings.CUSTOM_CONTEXT_SIZE,
        "ENABLE_STREAMING": settings.ENABLE_STREAMING,
        "AUTO_SAVE_ARTIFACTS": settings.AUTO_SAVE_ARTIFACTS,
        "VAULT_AUTOSAVE_MODE": settings.VAULT_AUTOSAVE_MODE,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key in result:
            val = await get_setting(db, key)
            if val is not None:
                result[key] = _coerce_setting_value(key, val)
    return result


async def _key_sources() -> dict[str, str]:
    """
    Return key source for provider credentials:
    - db: value exists in app_settings
    - env: only from environment/.env
    """
    result = {
        "OPENROUTER_API_KEY_SOURCE": "env",
        "DEEPSEEK_API_KEY_SOURCE": "env",
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"):
            async with db.execute("SELECT 1 FROM app_settings WHERE key=? LIMIT 1", (key,)) as cur:
                row = await cur.fetchone()
            if row is not None:
                result[f"{key}_SOURCE"] = "db"
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
    response = FileResponse(str(BASE_DIR / "static" / "index.html"))
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
    metadata: dict | None = None


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
    if settings.OBSIDIAN_ENABLED:
        project_scope = f"Projects/{_project_vault_key(project)}"
        ds = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system_prompt = system_prompt + "\n\n" + VAULT_SYSTEM_PROMPT.replace("{date}", ds)
        system_prompt = _augment_vault_prompt(system_prompt, project_scope=project_scope)
    logger.debug(f"System prompt length: {len(system_prompt)}")

    # Persist user message using the provided db connection
    await add_message(db, chat_id, "user", body.content)
    logger.info(f"Saved user message to chat {chat_id}")

    metadata = body.metadata or {}
    context_size = str(metadata.get("context_size") or settings.CONTEXT_SIZE)
    custom_context_size = int(metadata.get("custom_context_size") or settings.CUSTOM_CONTEXT_SIZE)
    use_streaming = bool(metadata.get("enable_streaming", settings.ENABLE_STREAMING))
    limited_history = _limit_history(history, context_size, custom_context_size)

    # Build messages for AI (только role/content для провайдера)
    ai_messages = [
        {"role": m["role"], "content": m.get("content") or ""}
        for m in limited_history
        if m.get("role") in ("user", "assistant")
    ]
    ai_messages.append({"role": "user", "content": body.content})
    
    logger.info(f"Sending {len(ai_messages)} messages to AI, user message length: {len(body.content)}")

    ai_client: AIClient = request.app.state.ai_client
    logger.info(f"Using AI provider: {ai_client.provider}, model: {ai_client.model}")

    async def event_generator():
        full_response = ""
        trace_json: str | None = None
        trace_payload: dict | None = None
        try:
            active_key = str(getattr(ai_client, "api_key", "") or "").strip()
            if not active_key:
                provider_name = getattr(ai_client, "provider", "ai")
                error_msg = (
                    f"Ошибка AI: не задан API ключ для провайдера '{provider_name}'. "
                    "Откройте Настройки и сохраните валидный ключ."
                )
                yield f"data: {json.dumps({'content': error_msg})}\n\n"
                full_response = error_msg
                trace_json = None
                trace_payload = None
                done_obj = {"done": True}
                yield f"data: {json.dumps(done_obj, ensure_ascii=False)}\n\n"
                return
            if settings.OBSIDIAN_ENABLED:
                logger.info("Starting AI with vault tools (non-stream provider loop + simulated stream)")
                vault_root = settings.obsidian_vault_path
                vault_root.mkdir(parents=True, exist_ok=True)
                project_key = _project_vault_key(project)
                project_scope = f"Projects/{project_key}"
                budget = {
                    "files": 0,
                    "sections": 0,
                    "chars": 0,
                }
                bootstrap_memory, bootstrap_calls, bootstrap_results = _bootstrap_vault_memory(
                    vault_root,
                    project.get("name") or "project",
                    project_key,
                )
                system_prompt_effective = (
                    system_prompt + "\n\n" + bootstrap_memory if bootstrap_memory else system_prompt
                )

                def exec_tool(name: str, args: dict) -> str:
                    scoped_args = dict(args or {})
                    if name == "write_note":
                        return json.dumps(
                            {
                                "error": (
                                    "Прямая запись write_note отключена в auto-режиме. "
                                    "Используется структурная автозапись артефактов (auto)."
                                )
                            },
                            ensure_ascii=False,
                        )
                    if name in {"list_notes", "search_notes"}:
                        folder = str(scoped_args.get("folder") or "").strip()
                        if not folder:
                            scoped_args["folder"] = project_scope
                        elif not _is_path_in_scope(folder, project_scope):
                            return json.dumps(
                                {"error": f"Доступ запрещен: folder вне проекта ({project_scope})"},
                                ensure_ascii=False,
                            )
                    if name in {"read_note", "write_note", "get_note_headers"}:
                        path = str(scoped_args.get("path") or "").strip()
                        if not path:
                            return json.dumps({"error": "path обязателен"}, ensure_ascii=False)
                        if not _is_path_in_scope(path, project_scope):
                            return json.dumps(
                                {"error": f"Доступ запрещен: path вне проекта ({project_scope})"},
                                ensure_ascii=False,
                            )
                    if name == "read_note":
                        if budget["files"] >= int(settings.VAULT_RETRIEVAL_MAX_FILES):
                            return json.dumps({"error": "Превышен лимит read_note по числу файлов"}, ensure_ascii=False)
                        if scoped_args.get("section"):
                            budget["sections"] += 1
                            if budget["sections"] > int(settings.VAULT_RETRIEVAL_MAX_SECTIONS):
                                return json.dumps({"error": "Превышен лимит read_note(section)"}, ensure_ascii=False)
                    tool_result = dispatch_vault_tool(vault_root, name, scoped_args)
                    budget["chars"] += len(tool_result)
                    if budget["chars"] > int(settings.VAULT_RETRIEVAL_MAX_CHARS):
                        return json.dumps({"error": "Превышен лимит символов навигации по vault"}, ensure_ascii=False)
                    if name == "read_note":
                        budget["files"] += 1
                    return tool_result

                full_response, trace_calls, result_strings = await ai_client.run_chat_with_tools(
                    ai_messages,
                    system_prompt_effective,
                    VAULT_TOOLS,
                    exec_tool,
                    temperature=float(metadata.get("temperature") or settings.AI_TEMPERATURE),
                    max_tokens=int(metadata.get("max_tokens") or settings.MAX_TOKENS),
                )
                all_trace_calls = bootstrap_calls + trace_calls
                all_result_strings = bootstrap_results + result_strings
                stats = summarize_trace(vault_root, all_trace_calls, all_result_strings)
                stats["budget"] = budget
                logger.info(
                    "Vault tool run summary chat_id=%s tools=%s files=%s sections=%s chars=%s",
                    chat_id,
                    len(all_trace_calls),
                    budget["files"],
                    budget["sections"],
                    budget["chars"],
                )

                decision = _detect_artifact_decision(body.content, full_response)
                decision["write_mode"] = "auto"
                autosave_mode = str(settings.VAULT_AUTOSAVE_MODE or "structured").strip().lower()
                if autosave_mode == "off":
                    decision["artifact_decision"] = "skip"
                    decision["decision_reason"] = (
                        decision.get("decision_reason", "") + ", автозапись отключена (mode=off)"
                    ).strip(", ")
                elif autosave_mode == "summary" and decision.get("artifact_type") != "summary":
                    decision["artifact_decision"] = "skip"
                    decision["decision_reason"] = (
                        decision.get("decision_reason", "") + ", mode=summary (записывается только _summary.md)"
                    ).strip(", ")
                links_created: list[str] = []
                written_meta: dict | None = None
                if decision["artifact_decision"] == "write":
                    try:
                        artifact_path = choose_artifact_path(
                            project_name=project.get("name") or "project",
                            artifact_type=decision["artifact_type"],
                            vault_ai_folder=settings.VAULT_AI_FOLDER,
                            project_key=project_key,
                        )
                        written_meta = upsert_artifact_entry(
                            vault_root,
                            artifact_path,
                            artifact_type=decision["artifact_type"],
                            title=decision["title"],
                            project_name=project.get("name") or "project",
                            chat_id=chat_id,
                            content=full_response,
                        )
                        links_created = update_project_hub_links(
                            vault_root,
                            project.get("name") or "project",
                            artifact_path,
                            decision["artifact_type"],
                            project_key=project_key,
                        )
                        decision["decision_reason"] = decision["decision_reason"] + ", автозапись выполнена"
                    except Exception as w_err:
                        decision["artifact_decision"] = "skip"
                        decision["decision_reason"] = f"ошибка автозаписи: {w_err}"
                        logger.warning("Auto artifact write failed: %s", w_err)
                decision["links_created"] = links_created
                decision["artifact_written"] = written_meta
                logger.info(
                    "Artifact decision chat_id=%s decision=%s type=%s confidence=%.3f reason=%s",
                    chat_id,
                    decision["artifact_decision"],
                    decision["artifact_type"],
                    float(decision["artifact_confidence"]),
                    decision["decision_reason"],
                )

                trace_payload = {"calls": all_trace_calls, "stats": stats, "artifact": decision}
                trace_json = json.dumps(trace_payload, ensure_ascii=False)

                if use_streaming:
                    step = 120
                    for i in range(0, len(full_response), step):
                        if await request.is_disconnected():
                            logger.info("Client disconnected during simulated stream")
                            break
                        chunk = full_response[i : i + step]
                        yield f"data: {json.dumps({'content': chunk})}\n\n"
                elif full_response:
                    yield f"data: {json.dumps({'content': full_response}, ensure_ascii=False)}\n\n"
                logger.info(f"AI vault flow completed, total response length: {len(full_response)}")
            else:
                logger.info("Starting AI stream")
                if use_streaming:
                    async for chunk in ai_client.stream_chat(
                        ai_messages,
                        system_prompt,
                        request=request,
                        temperature=float(metadata.get("temperature") or settings.AI_TEMPERATURE),
                        max_tokens=int(metadata.get("max_tokens") or settings.MAX_TOKENS),
                    ):
                        if await request.is_disconnected():
                            logger.info("Client disconnected, stopping stream")
                            break
                        full_response += chunk
                        yield f"data: {json.dumps({'content': chunk})}\n\n"
                else:
                    chunks: list[str] = []
                    async for chunk in ai_client.stream_chat(
                        ai_messages,
                        system_prompt,
                        request=request,
                        temperature=float(metadata.get("temperature") or settings.AI_TEMPERATURE),
                        max_tokens=int(metadata.get("max_tokens") or settings.MAX_TOKENS),
                    ):
                        if await request.is_disconnected():
                            logger.info("Client disconnected, stopping non-stream response")
                            break
                        chunks.append(chunk)
                    full_response = "".join(chunks)
                    if full_response:
                        yield f"data: {json.dumps({'content': full_response}, ensure_ascii=False)}\n\n"

                logger.info(f"AI stream completed, total response length: {len(full_response)}")

        except Exception as e:
            msg = str(e)
            if "401" in msg or "Unauthorized" in msg:
                provider_name = getattr(ai_client, "provider", "ai")
                error_msg = (
                    f"Ошибка AI: авторизация у провайдера '{provider_name}' не прошла (401). "
                    "Проверьте API ключ в настройках и сохраните его заново."
                )
            else:
                error_msg = f"Ошибка AI: {msg}"
            logger.error(f"Error in AI stream: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            full_response = error_msg
            trace_json = None
            trace_payload = None

        # Persist assistant reply using a new connection (since we're in a generator)
        try:
            async with aiosqlite.connect(DB_PATH) as raw_db:
                raw_db.row_factory = aiosqlite.Row
                await add_message(
                    raw_db,
                    chat_id,
                    "assistant",
                    full_response,
                    tool_calls_trace=trace_json,
                )
                logger.info(f"Saved assistant response to chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to save assistant response: {str(e)}")

        if (
            settings.OBSIDIAN_ENABLED
            and settings.VAULT_AUTO_LOG_CHATS
            and full_response
            and not full_response.startswith("Ошибка AI:")
        ):
            try:
                line = (
                    f"\n\n---\n**Чат:** {chat.get('name', '')} | **Проект:** {project.get('name', '')}\n"
                    f"**Запрос:** {body.content[:1200]}\n\n**Ответ:**\n{full_response[:6000]}\n"
                )
                append_chat_log(settings.obsidian_vault_path, settings.VAULT_CHATS_FOLDER, line)
            except Exception as log_e:
                logger.warning("Vault chat log failed: %s", log_e)

        done_obj: dict = {"done": True}
        if trace_payload is not None:
            done_obj["tool_calls_trace"] = trace_payload
        yield f"data: {json.dumps(done_obj, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Obsidian Vault (API для UI) ───────────────────────────────────────────────


class VaultNoteWrite(BaseModel):
    path: str
    content: str
    mode: str = "overwrite"


@app.get("/api/vault/tree")
async def api_vault_tree(
    project_id: str = Query(..., min_length=1),
    db: DbDep = None,
    auth: AuthDep = None,
):
    if not settings.OBSIDIAN_ENABLED:
        raise HTTPException(404, "Obsidian vault отключён (OBSIDIAN_ENABLED=false)")
    root = settings.obsidian_vault_path
    root.mkdir(parents=True, exist_ok=True)
    _, project_scope = await _resolve_project_scope(project_id, db)
    return {
        "path": str(root / project_scope),
        "tree": get_vault_tree(root, project_scope),
        "total_notes": count_markdown_notes(root, project_scope),
        "last_change": vault_mtime_iso(root),
    }


@app.get("/api/vault/status")
async def api_vault_status(auth: AuthDep):
    root = settings.obsidian_vault_path
    exists = root.is_dir()
    diagnostics = _vault_diagnostics()
    if not diagnostics["vault_runtime_enabled"]:
        logger.info(
            "Vault disabled: vault_config_present=%s env_OBSIDIAN_ENABLED=%s",
            diagnostics["vault_config_present"],
            os.getenv("OBSIDIAN_ENABLED", ""),
        )
    elif not diagnostics["vault_path_exists"]:
        logger.warning("Vault path does not exist: %s", root)

    status_obj = {
        "enabled": settings.OBSIDIAN_ENABLED,
        "path": str(root),
        "exists": exists,
        "total_notes": count_markdown_notes(root) if exists else 0,
        "last_change": vault_mtime_iso(root) if exists else None,
    }
    status_obj.update(diagnostics)
    return status_obj


@app.get("/api/vault/search")
async def api_vault_search(
    project_id: str = Query(..., min_length=1),
    db: DbDep = None,
    auth: AuthDep = None,
    q: str = Query(..., min_length=1),
    folder: str | None = None,
):
    if not settings.OBSIDIAN_ENABLED:
        raise HTTPException(404, "Obsidian vault отключён")
    root = settings.obsidian_vault_path
    _, project_scope = await _resolve_project_scope(project_id, db)
    scoped_folder = folder or project_scope
    if not _is_path_in_scope(scoped_folder, project_scope):
        logger.warning("Vault policy violation: search folder out of scope project_id=%s folder=%s", project_id, scoped_folder)
        raise HTTPException(403, f"Доступ запрещен: folder вне проекта ({project_scope})")
    return {"results": search_notes(root, q, scoped_folder)}


@app.get("/api/vault/note")
async def api_vault_note_get(
    project_id: str = Query(..., min_length=1),
    db: DbDep = None,
    auth: AuthDep = None,
    path: str = Query(..., min_length=1),
    section: str | None = None,
):
    if not settings.OBSIDIAN_ENABLED:
        raise HTTPException(404, "Obsidian vault отключён")
    root = settings.obsidian_vault_path
    _, project_scope = await _resolve_project_scope(project_id, db)
    if not _is_path_in_scope(path, project_scope):
        logger.warning("Vault policy violation: read path out of scope project_id=%s path=%s", project_id, path)
        raise HTTPException(403, f"Доступ запрещен: path вне проекта ({project_scope})")
    try:
        text = read_note(root, path, section)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"path": path, "section": section, "content": text}


@app.post("/api/vault/note")
async def api_vault_note_post(
    body: VaultNoteWrite,
    project_id: str = Query(..., min_length=1),
    db: DbDep = None,
    auth: AuthDep = None,
):
    if not settings.OBSIDIAN_ENABLED:
        raise HTTPException(404, "Obsidian vault отключён")
    root = settings.obsidian_vault_path
    _, project_scope = await _resolve_project_scope(project_id, db)
    if not _is_path_in_scope(body.path, project_scope):
        logger.warning("Vault policy violation: write path out of scope project_id=%s path=%s", project_id, body.path)
        raise HTTPException(403, f"Доступ запрещен: path вне проекта ({project_scope})")
    try:
        info = write_note(root, body.path, body.content, body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return info


@app.post("/api/vault/reindex")
async def api_vault_reindex(
    project_id: str = Query(..., min_length=1),
    db: DbDep = None,
    auth: AuthDep = None,
):
    if not settings.OBSIDIAN_ENABLED:
        raise HTTPException(404, "Obsidian vault отключён")
    root = settings.obsidian_vault_path
    root.mkdir(parents=True, exist_ok=True)
    _, project_scope = await _resolve_project_scope(project_id, db)
    return {
        "ok": True,
        "total_notes": count_markdown_notes(root, project_scope),
        "scanned_at": _now(),
    }


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
        async with raw_db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)) as cursor:
            row = await cursor.fetchone()
    artifact = dict(row) if row else None
    if not artifact or artifact.get("project_id") != project_id:
        raise HTTPException(404, "Artifact not found")
    file_path = artifact.get("file_path")
    if file_path:
        Path(file_path).unlink(missing_ok=True)
    await delete_artifact(db, artifact_id)
    return {"ok": True}


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    AI_PROVIDER: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_MODEL: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str | None = None
    AI_TEMPERATURE: float | None = None
    MAX_TOKENS: int | None = None
    CONTEXT_SIZE: str | None = None
    CUSTOM_CONTEXT_SIZE: int | None = None
    ENABLE_STREAMING: bool | None = None
    AUTO_SAVE_ARTIFACTS: bool | None = None
    VAULT_AUTOSAVE_MODE: str | None = None
    CLEAR_OPENROUTER_API_KEY: bool | None = None
    CLEAR_DEEPSEEK_API_KEY: bool | None = None


class ApiKeyValidationRequest(BaseModel):
    provider: str
    api_key: str


class ProviderDiagnostic(BaseModel):
    provider: str
    model: str
    has_key: bool
    key_source: str


@app.get("/api/settings")
async def get_app_settings(auth: AuthDep):
    effective = await _get_effective_settings()
    key_sources = await _key_sources()
    diagnostics = _vault_diagnostics()
    settings_obj = {
        "AI_PROVIDER": effective["AI_PROVIDER"],
        "OPENROUTER_API_KEY": _mask_key(effective["OPENROUTER_API_KEY"]),
        "OPENROUTER_MODEL": effective["OPENROUTER_MODEL"],
        "DEEPSEEK_API_KEY": _mask_key(effective["DEEPSEEK_API_KEY"]),
        "DEEPSEEK_MODEL": effective["DEEPSEEK_MODEL"],
        "AI_TEMPERATURE": effective["AI_TEMPERATURE"],
        "MAX_TOKENS": effective["MAX_TOKENS"],
        "CONTEXT_SIZE": effective["CONTEXT_SIZE"],
        "CUSTOM_CONTEXT_SIZE": effective["CUSTOM_CONTEXT_SIZE"],
        "ENABLE_STREAMING": effective["ENABLE_STREAMING"],
        "AUTO_SAVE_ARTIFACTS": effective["AUTO_SAVE_ARTIFACTS"],
        "VAULT_AUTOSAVE_MODE": effective["VAULT_AUTOSAVE_MODE"],
        "AUTH_ENABLED": settings.AUTH_ENABLED,
        "OBSIDIAN_ENABLED": settings.OBSIDIAN_ENABLED,
        "OBSIDIAN_VAULT_PATH": str(settings.obsidian_vault_path),
        "VAULT_AI_FOLDER": settings.VAULT_AI_FOLDER,
        "VAULT_AUTO_LOG_CHATS": settings.VAULT_AUTO_LOG_CHATS,
        "VAULT_ARTIFACT_AUTOSAVE_THRESHOLD": settings.VAULT_ARTIFACT_AUTOSAVE_THRESHOLD,
        "VAULT_RETRIEVAL_MAX_FILES": settings.VAULT_RETRIEVAL_MAX_FILES,
        "VAULT_RETRIEVAL_MAX_SECTIONS": settings.VAULT_RETRIEVAL_MAX_SECTIONS,
        "VAULT_RETRIEVAL_MAX_CHARS": settings.VAULT_RETRIEVAL_MAX_CHARS,
        "WEBDAV_PORT": settings.WEBDAV_PORT,
        "WEBDAV_USER": settings.WEBDAV_USER,
        "OPENROUTER_API_KEY_CONFIGURED": bool((effective["OPENROUTER_API_KEY"] or "").strip()),
        "DEEPSEEK_API_KEY_CONFIGURED": bool((effective["DEEPSEEK_API_KEY"] or "").strip()),
        "OPENROUTER_API_KEY_SOURCE": key_sources["OPENROUTER_API_KEY_SOURCE"],
        "DEEPSEEK_API_KEY_SOURCE": key_sources["DEEPSEEK_API_KEY_SOURCE"],
    }
    settings_obj.update(diagnostics)
    return settings_obj


@app.get("/api/settings/provider-health")
async def get_provider_health(auth: AuthDep):
    effective = await _get_effective_settings()
    key_sources = await _key_sources()
    providers = [
        ProviderDiagnostic(
            provider="openrouter",
            model=str(effective["OPENROUTER_MODEL"]),
            has_key=bool(str(effective["OPENROUTER_API_KEY"] or "").strip()),
            key_source=key_sources["OPENROUTER_API_KEY_SOURCE"],
        ).model_dump(),
        ProviderDiagnostic(
            provider="deepseek",
            model=str(effective["DEEPSEEK_MODEL"]),
            has_key=bool(str(effective["DEEPSEEK_API_KEY"] or "").strip()),
            key_source=key_sources["DEEPSEEK_API_KEY_SOURCE"],
        ).model_dump(),
    ]
    return {"active_provider": effective["AI_PROVIDER"], "providers": providers}


@app.post("/api/settings/validate-key")
async def validate_provider_key(body: ApiKeyValidationRequest, auth: AuthDep):
    provider = (body.provider or "").strip().lower()
    if provider not in {"openrouter", "deepseek"}:
        raise HTTPException(400, "provider must be openrouter or deepseek")
    api_key = (body.api_key or "").strip()
    if not api_key:
        raise HTTPException(400, "API ключ пустой")
    ok = await validate_api_key(provider, api_key)
    if not ok:
        raise HTTPException(400, "Невалидный API ключ для выбранного провайдера")
    return {"ok": True}


@app.post("/api/settings")
async def update_app_settings(body: SettingsUpdate, request: Request, auth: AuthDep):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No settings provided")

    clear_openrouter_key = bool(updates.pop("CLEAR_OPENROUTER_API_KEY", False))
    clear_deepseek_key = bool(updates.pop("CLEAR_DEEPSEEK_API_KEY", False))

    for key in ("AI_PROVIDER", "OPENROUTER_MODEL", "DEEPSEEK_MODEL", "CONTEXT_SIZE", "VAULT_AUTOSAVE_MODE"):
        if key in updates and isinstance(updates[key], str):
            updates[key] = _trim_optional(updates[key])
    for key in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"):
        if key in updates and isinstance(updates[key], str):
            updates[key] = _trim_optional(updates[key])

    # API key update policy:
    # - masked values are rejected
    # - empty value is ignored unless explicit clear flag is provided
    for key, clear_flag in (
        ("OPENROUTER_API_KEY", clear_openrouter_key),
        ("DEEPSEEK_API_KEY", clear_deepseek_key),
    ):
        if key not in updates:
            continue
        value = str(updates.get(key) or "")
        if _is_masked_key(value):
            raise HTTPException(400, f"Нельзя сохранять маскированное значение для {key}")
        if not value:
            if clear_flag:
                updates[key] = ""
            else:
                updates.pop(key, None)
    if clear_openrouter_key and "OPENROUTER_API_KEY" not in updates:
        updates["OPENROUTER_API_KEY"] = ""
    if clear_deepseek_key and "DEEPSEEK_API_KEY" not in updates:
        updates["DEEPSEEK_API_KEY"] = ""

    if "AI_TEMPERATURE" in updates:
        temp = float(updates["AI_TEMPERATURE"])
        if temp < 0 or temp > 2:
            raise HTTPException(400, "AI_TEMPERATURE must be between 0 and 2")
    if "MAX_TOKENS" in updates:
        max_tokens = int(updates["MAX_TOKENS"])
        if max_tokens < 100 or max_tokens > 16000:
            raise HTTPException(400, "MAX_TOKENS must be between 100 and 16000")
    if "CONTEXT_SIZE" in updates:
        if updates["CONTEXT_SIZE"] not in {"small", "medium", "large", "custom"}:
            raise HTTPException(400, "CONTEXT_SIZE must be one of: small, medium, large, custom")
    if "VAULT_AUTOSAVE_MODE" in updates:
        mode = str(updates["VAULT_AUTOSAVE_MODE"] or "").strip().lower()
        if mode not in {"off", "summary", "structured"}:
            raise HTTPException(400, "VAULT_AUTOSAVE_MODE must be one of: off, summary, structured")
        updates["VAULT_AUTOSAVE_MODE"] = mode
    if "CUSTOM_CONTEXT_SIZE" in updates:
        custom_size = int(updates["CUSTOM_CONTEXT_SIZE"])
        if custom_size < 500 or custom_size > 200000:
            raise HTTPException(400, "CUSTOM_CONTEXT_SIZE must be between 500 and 200000")
    
    # Validate API keys if provided
    if "OPENROUTER_API_KEY" in updates and updates["OPENROUTER_API_KEY"]:
        if not await validate_api_key("openrouter", updates["OPENROUTER_API_KEY"]):
            raise HTTPException(400, "Invalid OpenRouter API key")
    
    if "DEEPSEEK_API_KEY" in updates and updates["DEEPSEEK_API_KEY"]:
        if not await validate_api_key("deepseek", updates["DEEPSEEK_API_KEY"]):
            raise HTTPException(400, "Invalid DeepSeek API key")

    if not updates and not clear_openrouter_key and not clear_deepseek_key:
        raise HTTPException(400, "Нет изменений для сохранения")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for key, value in updates.items():
            await set_setting(db, key, value)

    if "VAULT_AUTOSAVE_MODE" in updates:
        settings.VAULT_AUTOSAVE_MODE = str(updates["VAULT_AUTOSAVE_MODE"])

    await _rebuild_ai_client(request.app.state)
    return {"ok": True, "updated": list(updates.keys())}
