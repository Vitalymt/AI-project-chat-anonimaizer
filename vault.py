"""
Obsidian vault navigation tools for AI (no embeddings).

All paths are relative to the vault root; path traversal is blocked.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# OpenAI-style tool definitions for the chat completions API
VAULT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_vault_tree",
            "description": (
                "Показывает структуру Obsidian vault — папки и файлы с метаданными. "
                "Используй первым чтобы сориентироваться."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "Список файлов в конкретной папке vault с датами изменения и заголовками.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Путь к папке относительно vault, например 'Projects/ProjectA'",
                    }
                },
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_note_headers",
            "description": (
                "Возвращает только заголовки (##) файла без содержимого. "
                "Используй чтобы решить нужно ли читать файл целиком."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь к файлу .md относительно vault",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Читает содержимое заметки целиком или только конкретный раздел.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу .md"},
                    "section": {
                        "type": "string",
                        "description": "Заголовок раздела для чтения (опционально). Например: 'Технические риски'",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": (
                "Полнотекстовый поиск по vault. Используй когда не знаешь в каком файле искать информацию."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"},
                    "folder": {
                        "type": "string",
                        "description": "Ограничить поиск папкой (опционально)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "Создать новую заметку или обновить существующую в vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу .md относительно vault"},
                    "content": {"type": "string", "description": "Содержимое заметки в Markdown"},
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append", "prepend"],
                        "description": "Режим записи: перезаписать / добавить в конец / добавить в начало",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
]

VAULT_SYSTEM_PROMPT = """
У тебя есть доступ к Obsidian vault пользователя через инструменты.

ПРАВИЛА НАВИГАЦИИ:
1. Начинай с get_vault_tree() чтобы понять структуру
2. Используй get_note_headers() перед read_note() — читай файл только если заголовки релевантны
3. Не читай все файлы подряд — только те, что нужны для ответа
4. При поиске по неизвестной теме — используй search_notes()
5. Когда пишешь заметки — используй Obsidian Markdown: [[ссылки]], #теги, ## заголовки

ФОРМАТ ЗАМЕТОК:
- Всегда добавляй дату создания в начало: > Создано AI: {date}
- Используй [[wikilinks]] для ссылок на другие заметки
- Добавляй теги: #ai-generated #project-name

КОГДА ПИСАТЬ В VAULT:
- Явная просьба пользователя ("сохрани", "запиши в vault")
- Создание саммари / итогов встречи / решений
- Сохранение артефактов работы
- Ведение лога чата (если включено)
""".strip()

MAX_READ_BYTES = 100 * 1024
HEADER_SCAN_BYTES = 128 * 1024
SEARCH_MAX_RESULTS = 50
_SEARCH_LINE_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
logger = logging.getLogger(__name__)


def _vault_root(vault_path: Path) -> Path:
    return vault_path.expanduser().resolve()


def safe_path(vault_root: Path, rel_path: str) -> Path:
    """Resolve rel_path under vault_root; raise ValueError if escape attempted."""
    root = _vault_root(vault_root)
    rp = (rel_path or ".").strip() or "."
    candidate = (root / rp).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Выход за пределы vault запрещён: {rel_path}")
    return candidate


def count_markdown_notes(vault_root: Path, folder: str | None = None) -> int:
    root = _vault_root(vault_root)
    if folder:
        try:
            root = safe_path(root, folder.strip().strip("/"))
        except ValueError:
            return 0
    if not root.is_dir():
        return 0
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".md"):
                n += 1
    return n


def vault_mtime_iso(vault_root: Path) -> str | None:
    """Latest mtime among files in vault (rough 'last change' for UI)."""
    root = _vault_root(vault_root)
    if not root.is_dir():
        return None
    latest: float | None = None
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if latest is None or m > latest:
                latest = m
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_size_kb(size_bytes: int) -> float:
    return round(size_bytes / 1024.0, 1)


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _extract_h2_headers(text: str) -> list[str]:
    headers: list[str] = []
    for m in _SEARCH_LINE_RE.finditer(text):
        title = m.group(1).strip()
        if title:
            headers.append(f"## {title}")
    return headers


def _read_text_limited(path: Path, limit: int) -> tuple[str, bool]:
    """Read up to `limit` bytes; returns (text, truncated)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ValueError(f"Не удалось прочитать файл: {e}") from e
    truncated = len(raw) > limit
    data = raw[:limit]
    return data.decode("utf-8", errors="replace"), truncated


def get_vault_tree(vault_root: Path, folder: str | None = None) -> str:
    root = _vault_root(vault_root)
    if folder:
        try:
            root = safe_path(root, folder.strip().strip("/"))
        except ValueError:
            return f"(папка вне vault: {folder})"
    if not root.is_dir():
        return f"(vault не найден или не папка: {root})"

    lines: list[str] = []

    def walk(rel: str, directory: Path, indent: str) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for p in entries:
            name = p.name
            if name.startswith("."):
                continue
            rel_child = f"{rel}/{name}" if rel else name
            if p.is_dir():
                try:
                    n_md = sum(1 for _ in p.rglob("*.md"))
                except OSError:
                    n_md = 0
                lines.append(f"{indent}{name}/ ({n_md} .md)")
                walk(rel_child, p, indent + "  ")
            elif p.suffix.lower() == ".md":
                try:
                    st = p.stat()
                    sz = _fmt_size_kb(st.st_size)
                    mod = _fmt_date(st.st_mtime)
                except OSError:
                    sz, mod = 0, "?"
                lines.append(f"{indent}{name} ({sz}kb, изменён {mod})")

    walk("", root, "")
    return "\n".join(lines) if lines else "(пустой vault)"


def list_notes(vault_root: Path, folder: str) -> list[dict[str, Any]]:
    root = _vault_root(vault_root)
    folder_path = safe_path(root, folder.strip().strip("/"))
    if not folder_path.is_dir():
        raise ValueError(f"Папка не найдена: {folder}")

    out: list[dict[str, Any]] = []
    try:
        entries = sorted(folder_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        raise ValueError(f"Не удалось прочитать папку: {e}") from e

    for p in entries:
        if p.name.startswith("."):
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if p.is_dir():
            try:
                n_files = sum(1 for f in p.iterdir() if f.is_file() and not f.name.startswith("."))
            except OSError:
                n_files = 0
            out.append(
                {
                    "path": rel + "/",
                    "type": "folder",
                    "files_in_folder": n_files,
                }
            )
        elif p.suffix.lower() == ".md":
            try:
                st = p.stat()
            except OSError:
                continue
            head_text, _ = _read_text_limited(p, HEADER_SCAN_BYTES)
            out.append(
                {
                    "path": rel,
                    "type": "file",
                    "size_kb": _fmt_size_kb(st.st_size),
                    "modified": _fmt_date(st.st_mtime),
                    "headers": _extract_h2_headers(head_text),
                }
            )
    return out


def get_note_headers(vault_root: Path, path: str) -> list[str]:
    root = _vault_root(vault_root)
    file_path = safe_path(root, path.strip())
    if not file_path.is_file():
        raise ValueError(f"Файл не найден: {path}")
    if file_path.suffix.lower() != ".md":
        raise ValueError("Поддерживаются только .md файлы")
    head_text, _ = _read_text_limited(file_path, HEADER_SCAN_BYTES)
    return _extract_h2_headers(head_text)


def read_note(vault_root: Path, path: str, section: str | None = None) -> str:
    root = _vault_root(vault_root)
    file_path = safe_path(root, path.strip())
    if not file_path.is_file():
        raise ValueError(f"Файл не найден: {path}")
    if file_path.suffix.lower() != ".md":
        raise ValueError("Поддерживаются только .md файлы")

    text, truncated = _read_text_limited(file_path, MAX_READ_BYTES)
    warn = ""
    if truncated:
        warn = f"\n\n[Предупреждение: файл больше {MAX_READ_BYTES // 1024}KB, показаны первые {MAX_READ_BYTES // 1024}KB]"

    if not section:
        return text + warn

    sec = section.strip()
    # Match ## SectionTitle ... until next ## or EOF
    pattern = re.compile(
        rf"(^|\n)##\s+{re.escape(sec)}\s*(\n|$)(.*?)(?=\n##\s+|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        return f"[Раздел '## {sec}' не найден в доступной части файла]{warn}"
    body = m.group(3).strip()
    return f"## {sec}\n\n{body}" + warn


def search_notes(vault_root: Path, query: str, folder: str | None = None) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError("Пустой запрос поиска")
    root = _vault_root(vault_root)
    base = root
    if folder and folder.strip():
        base = safe_path(root, folder.strip().strip("/"))
        if not base.is_dir():
            raise ValueError(f"Папка для поиска не найдена: {folder}")

    results: list[dict[str, Any]] = []
    q = query.strip()

    for dirpath, _dirnames, filenames in os.walk(base):
        if len(results) >= SEARCH_MAX_RESULTS:
            break
        for fn in filenames:
            if len(results) >= SEARCH_MAX_RESULTS:
                break
            if not fn.lower().endswith(".md"):
                continue
            fp = Path(dirpath) / fn
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if q in line:
                    rel = str(fp.relative_to(root)).replace("\\", "/")
                    lo = max(0, i - 2)
                    hi = min(len(lines), i + 3)
                    context = [{"line_no": j + 1, "text": lines[j]} for j in range(lo, hi)]
                    results.append(
                        {
                            "path": rel,
                            "match_line": i + 1,
                            "match_text": line,
                            "context": context,
                        }
                    )
                    if len(results) >= SEARCH_MAX_RESULTS:
                        break
    return results


def write_note(
    vault_root: Path,
    path: str,
    content: str,
    mode: str = "overwrite",
) -> dict[str, Any]:
    if mode not in {"overwrite", "append", "prepend"}:
        raise ValueError("mode должен быть overwrite, append или prepend")
    root = _vault_root(vault_root)
    file_path = safe_path(root, path.strip())
    if file_path.suffix.lower() != ".md":
        raise ValueError("Можно записывать только .md файлы")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    created = not file_path.exists()
    if mode == "overwrite":
        file_path.write_text(content, encoding="utf-8")
    elif mode == "append":
        prev = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        file_path.write_text(prev + content, encoding="utf-8")
    else:
        prev = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        file_path.write_text(content + prev, encoding="utf-8")
    st = file_path.stat()
    result = {
        "path": str(file_path.relative_to(root)).replace("\\", "/"),
        "created": created,
        "size_kb": _fmt_size_kb(st.st_size),
        "mode": mode,
    }
    if content.strip() and st.st_size == 0:
        # Defensive diagnostic for rare write anomalies reported in Obsidian sync tests
        warn_msg = "Файл после записи оказался пустым при непустом контенте"
        logger.warning("write_note anomaly path=%s mode=%s", result["path"], mode)
        result["warning"] = warn_msg
    return result


def dispatch_vault_tool(vault_root: Path, name: str, arguments: dict[str, Any]) -> str:
    """Execute tool by name; return string for OpenAI tool message content."""
    try:
        if name == "get_vault_tree":
            return get_vault_tree(vault_root)
        if name == "list_notes":
            folder = arguments.get("folder") or ""
            return json.dumps(list_notes(vault_root, str(folder)), ensure_ascii=False)
        if name == "get_note_headers":
            return json.dumps(
                get_note_headers(vault_root, str(arguments.get("path", ""))),
                ensure_ascii=False,
            )
        if name == "read_note":
            return read_note(
                vault_root,
                str(arguments.get("path", "")),
                arguments.get("section"),
            )
        if name == "search_notes":
            return json.dumps(
                search_notes(
                    vault_root,
                    str(arguments.get("query", "")),
                    arguments.get("folder"),
                ),
                ensure_ascii=False,
            )
        if name == "write_note":
            return json.dumps(
                write_note(
                    vault_root,
                    str(arguments.get("path", "")),
                    str(arguments.get("content", "")),
                    str(arguments.get("mode") or "overwrite"),
                ),
                ensure_ascii=False,
            )
        return json.dumps({"error": f"Неизвестный инструмент: {name}"}, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def build_tool_trace_entry(
    name: str,
    arguments: dict[str, Any],
    result_text: str,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    preview = result_text if len(result_text) <= 2000 else result_text[:2000] + "…"
    err = None
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict) and "error" in parsed:
            err = parsed.get("error")
    except json.JSONDecodeError:
        pass
    return {
        "name": name,
        "arguments": arguments,
        "result_preview": preview,
        "error": err,
        "status": "error" if err else "ok",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
    }


def summarize_trace(
    vault_root: Path,
    calls: list[dict[str, Any]],
    result_strings: list[str],
) -> dict[str, Any]:
    files_read = sum(1 for c in calls if c.get("name") == "read_note")
    total_notes = count_markdown_notes(vault_root)
    nav_chars = sum(len(s) for s in result_strings)
    estimated_nav_tokens = max(1, nav_chars // 4)
    return {
        "files_read": files_read,
        "total_notes": total_notes,
        "estimated_nav_tokens": estimated_nav_tokens,
    }


def append_chat_log(vault_root: Path, chats_folder: str, line: str) -> None:
    """Append a line to Chats/YYYY-MM-DD.md under vault_root."""
    root = _vault_root(vault_root)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rel = f"{chats_folder.strip().strip('/')}/{day}.md"
    write_note(
        root,
        rel,
        line + "\n",
        mode="append",
    )


def slugify_text(value: str, fallback: str = "note") -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^\w\u0400-\u04FF\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    if not s:
        s = fallback
    return s[:80]


def choose_artifact_path(
    project_name: str,
    artifact_type: str,
    vault_ai_folder: str,
    project_key: str | None = None,
    now_utc: datetime | None = None,
) -> str:
    now = now_utc or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    slug = slugify_text(project_key or project_name, fallback="project")
    base = f"Projects/{slug}"
    if artifact_type == "summary":
        return f"{base}/_summary.md"
    if artifact_type == "analysis":
        return f"{base}/analysis/{day}-analysis.md"
    if artifact_type == "risks":
        return f"{base}/risks/{day}-risks.md"
    if artifact_type == "decisions":
        return f"{base}/decisions/{day}-decisions.md"
    if artifact_type == "meeting-notes":
        return f"{base}/meetings/{day}.md"
    # fallback bucket for autonomous artifacts
    folder = slugify_text(vault_ai_folder, fallback="ai-generated")
    return f"{folder}/{slug}/{day}-artifact.md"


def build_artifact_markdown(
    *,
    title: str,
    artifact_type: str,
    project_name: str,
    chat_id: str,
    content: str,
    created_at: datetime | None = None,
) -> str:
    ts = (created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"---\n"
        f"created_at: {ts}\n"
        f"artifact_type: {artifact_type}\n"
        f"project: {project_name}\n"
        f"chat_id: {chat_id}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"{content.strip()}\n"
    )


def update_project_hub_links(
    vault_root: Path,
    project_name: str,
    artifact_path: str,
    artifact_type: str,
    project_key: str | None = None,
) -> list[str]:
    project_slug = slugify_text(project_key or project_name, fallback="project")
    hub_path = f"Projects/{project_slug}/_summary.md"
    link_target = Path(artifact_path).with_suffix("").as_posix()
    wiki = f"[[{link_target}]]"
    section_title = {
        "analysis": "## Анализ",
        "risks": "## Риски",
        "decisions": "## Решения",
        "meeting-notes": "## Встречи",
        "summary": "## Саммари",
    }.get(artifact_type, "## Артефакты")

    root = _vault_root(vault_root)
    hub_file = safe_path(root, hub_path)
    hub_file.parent.mkdir(parents=True, exist_ok=True)
    if hub_file.exists():
        text = hub_file.read_text(encoding="utf-8")
    else:
        text = f"# Сводка проекта {project_name}\n\n"
    if section_title not in text:
        text += f"\n{section_title}\n"
    if wiki not in text:
        text += f"- {wiki}\n"
    hub_file.write_text(text, encoding="utf-8")
    return [hub_path, artifact_path]


def upsert_markdown_section(text: str, section_title: str, section_body: str) -> str:
    """
    Upsert '## section_title' with new body.
    If section exists, it is replaced in-place; otherwise appended.
    """
    normalized = text or ""
    header = f"## {section_title}"
    pattern = re.compile(
        rf"(^|\n){re.escape(header)}\s*(\n|$)(.*?)(?=\n##\s+|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    replacement = f"\n{header}\n\n{section_body.strip()}\n"
    if pattern.search(normalized):
        return pattern.sub(lambda _m: replacement, normalized, count=1).strip() + "\n"
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return (normalized + replacement).strip() + "\n"


def upsert_artifact_entry(
    vault_root: Path,
    artifact_path: str,
    *,
    artifact_type: str,
    title: str,
    project_name: str,
    chat_id: str,
    content: str,
) -> dict[str, Any]:
    """
    Idempotent artifact write:
    - summary note uses per-chat section upsert
    - other artifact notes are overwritten (one canonical artifact per file)
    """
    root = _vault_root(vault_root)
    if artifact_type == "summary":
        p = safe_path(root, artifact_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existing = p.read_text(encoding="utf-8") if p.exists() else f"# Сводка проекта {project_name}\n\n"
        section = f"Entry {chat_id}"
        body = (
            f"> Обновлено AI: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
            f"{content.strip()}\n"
        )
        updated = upsert_markdown_section(existing, section, body)
        p.write_text(updated, encoding="utf-8")
        st = p.stat()
        warning = None
        if st.st_size == 0:
            warning = "Summary записан как пустой файл"
        elif section not in updated:
            warning = "Summary записан без ожидаемой секции Entry <chat_id>"
        return {
            "path": str(p.relative_to(root)).replace("\\", "/"),
            "created": False,
            "size_kb": _fmt_size_kb(st.st_size),
            "mode": "upsert-section",
            "warning": warning,
        }

    md = build_artifact_markdown(
        title=title,
        artifact_type=artifact_type,
        project_name=project_name,
        chat_id=chat_id,
        content=content,
    )
    info = write_note(root, artifact_path, md, mode="overwrite")
    info["mode"] = "overwrite"
    return info
