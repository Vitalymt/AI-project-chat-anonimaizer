"""
ProjectChat — FastAPI application entry point.
"""
from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
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
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_client import AIClient
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
MAX_DOC_CHARS = 50_000
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

settings: Settings = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    app.state.ai_client = AIClient(settings)
    yield
    await app.state.ai_client.close()


app = FastAPI(title="ProjectChat", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


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
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health(request: Request):
    ai: AIClient = request.app.state.ai_client
    return {"status": "ok", "provider": ai.provider, "model": ai.model}


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    goal: str = ""


class ProjectUpdate(BaseModel):
    name: str
    goal: str = ""


@app.get("/api/projects")
async def get_projects(db: DbDep):
    return await list_projects(db)


@app.post("/api/projects", status_code=201)
async def create_new_project(body: ProjectCreate, db: DbDep):
    project = await create_project(db, body.name, body.goal)
    project_dir = _project_dir(project["id"])
    for sub in ("original", "anonymized", "artifacts"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    return project


@app.get("/api/projects/{project_id}")
async def get_project_detail(project_id: str, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    documents = await list_documents(db, project_id)
    chats = await list_chats(db, project_id)
    artifacts = await list_artifacts(db, project_id)
    return {**project, "documents": documents, "chats": chats, "artifacts": artifacts}


@app.put("/api/projects/{project_id}")
async def update_project_detail(project_id: str, body: ProjectUpdate, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await update_project(db, project_id, body.name, body.goal)


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    await delete_project(db, project_id)
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)
    return {"ok": True}


# ── Documents ─────────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/documents", status_code=202)
async def upload_document(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: DbDep,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
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
    doc_id_tmp = __import__("uuid").uuid4().hex[:8]
    safe_name = f"{doc_id_tmp}_{filename}"
    orig_path = orig_dir / safe_name
    orig_path.write_bytes(content)

    # Create DB record (status = processing)
    doc = await add_document(db, project_id, name, description, filename, ext, str(orig_path))

    # Rename file to use actual doc ID
    final_path = orig_dir / f"{doc['id']}_{filename}"
    orig_path.rename(final_path)

    # Update original_path in DB
    async with aiosqlite.connect(DB_PATH) as raw_db:
        await raw_db.execute(
            "UPDATE documents SET original_path=? WHERE id=?",
            (str(final_path), doc["id"]),
        )
        await raw_db.commit()

    doc["original_path"] = str(final_path)

    # Schedule background parsing + anonymization
    background_tasks.add_task(process_document, doc["id"], str(final_path), ext)

    return doc


@app.get("/api/projects/{project_id}/documents")
async def get_documents(project_id: str, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_documents(db, project_id)


@app.get("/api/projects/{project_id}/documents/{doc_id}")
async def get_document_detail(project_id: str, doc_id: str, db: DbDep):
    doc = await get_document(db, doc_id)
    if not doc or doc["project_id"] != project_id:
        raise HTTPException(404, "Document not found")
    return doc


@app.delete("/api/projects/{project_id}/documents/{doc_id}")
async def remove_document(project_id: str, doc_id: str, db: DbDep):
    doc = await get_document(db, doc_id)
    if not doc or doc["project_id"] != project_id:
        raise HTTPException(404, "Document not found")
    await delete_document(db, doc_id)
    for path_key in ("original_path", "anonymized_path"):
        p = doc.get(path_key)
        if p and Path(p).exists():
            Path(p).unlink(missing_ok=True)
    return {"ok": True}


# ── Chats ─────────────────────────────────────────────────────────────────────

class ChatCreate(BaseModel):
    name: str = "Новый чат"


@app.post("/api/projects/{project_id}/chats", status_code=201)
async def create_new_chat(project_id: str, body: ChatCreate, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await create_chat(db, project_id, body.name)


@app.get("/api/projects/{project_id}/chats")
async def get_chats(project_id: str, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_chats(db, project_id)


@app.delete("/api/projects/{project_id}/chats/{chat_id}")
async def remove_chat(project_id: str, chat_id: str, db: DbDep):
    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")
    await delete_chat(db, chat_id)
    return {"ok": True}


# ── Messages ──────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/chats/{chat_id}/messages")
async def get_chat_messages(project_id: str, chat_id: str, db: DbDep):
    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")
    return await get_messages(db, chat_id)


class MessageRequest(BaseModel):
    content: str


@app.post("/api/projects/{project_id}/chats/{chat_id}/messages")
async def send_message(
    project_id: str,
    chat_id: str,
    body: MessageRequest,
    request: Request,
    db: DbDep,
):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    chat = await get_chat(db, chat_id)
    if not chat or chat["project_id"] != project_id:
        raise HTTPException(404, "Chat not found")

    documents = await list_documents(db, project_id)
    history = await get_messages(db, chat_id)

    system_prompt = build_system_prompt(project, documents)

    # Persist user message
    async with aiosqlite.connect(DB_PATH) as raw_db:
        raw_db.row_factory = aiosqlite.Row
        await add_message(raw_db, chat_id, "user", body.content)

    # Build messages for AI
    ai_messages = [{"role": m["role"], "content": m["content"]} for m in history]
    ai_messages.append({"role": "user", "content": body.content})

    ai_client: AIClient = request.app.state.ai_client

    async def event_generator():
        full_response = ""
        try:
            async for chunk in ai_client.stream_chat(ai_messages, system_prompt):
                if await request.is_disconnected():
                    break
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except Exception as e:
            error_msg = f"Ошибка AI: {str(e)}"
            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            full_response = error_msg

        # Persist assistant reply
        async with aiosqlite.connect(DB_PATH) as raw_db:
            raw_db.row_factory = aiosqlite.Row
            await add_message(raw_db, chat_id, "assistant", full_response)

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
async def create_artifact(project_id: str, body: ArtifactCreate, db: DbDep):
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
async def get_artifacts(project_id: str, db: DbDep):
    project = await get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await list_artifacts(db, project_id)


@app.delete("/api/projects/{project_id}/artifacts/{artifact_id}")
async def remove_artifact(project_id: str, artifact_id: str, db: DbDep):
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
async def get_app_settings():
    effective = await _get_effective_settings()
    return {
        "AI_PROVIDER": effective["AI_PROVIDER"],
        "OPENROUTER_API_KEY": _mask_key(effective["OPENROUTER_API_KEY"]),
        "OPENROUTER_MODEL": effective["OPENROUTER_MODEL"],
        "DEEPSEEK_API_KEY": _mask_key(effective["DEEPSEEK_API_KEY"]),
        "DEEPSEEK_MODEL": effective["DEEPSEEK_MODEL"],
    }


@app.post("/api/settings")
async def update_app_settings(body: SettingsUpdate, request: Request):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No settings provided")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for key, value in updates.items():
            await set_setting(db, key, value)

    await _rebuild_ai_client(request.app.state)
    return {"ok": True, "updated": list(updates.keys())}
