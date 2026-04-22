# Cleanup decisions

## inventory-by-blocks

### hygiene/docs
- accept: `.env.example`, `.gitignore`, `README.md`, `LICENSE`, `docs/screenshots/README.md`, `scripts/smoke_check.sh`

### vault/ops
- accept: `docker-compose.yml`, `setup.sh`, `vault.py`
- defer: `archive/OPERATIONS.md` (внутренний runbook, не влияет на runtime)

### backend/core
- accept: `Dockerfile`, `requirements.txt`, `anonymizer.py`, `config/settings.py`, `database.py`, `ai_client.py`, `main.py`
- archive: `crypto.py` (не криптография, только base64)

### frontend
- accept: `static/app.js`, `static/style.css`, `static/anonymizer.js`, `static/index.html`
- action: убрать конфликт staged/unstaged у `static/index.html`, оставить рабочую (текущую в рабочем дереве) версию

## changelog
- inventory создан

## accept-hygiene-docs
- включено: `.env.example`, `.gitignore`, `README.md`, `LICENSE`, `docs/screenshots/README.md`, `scripts/smoke_check.sh`
- проверено: явных секретов в этих файлах не найдено
- риск: `README.md` объемный, часть runbook можно позже вынести в `archive/` или `docs/`

## review-vault-ops
- accept: `vault.py`, `docker-compose.yml`
- accept (hardened): `setup.sh` — удалена автоустановка Docker через `curl | sh`, оставлена только ручная инструкция
- defer: подробные ops-runbook файлы в `archive/` (не мешают runtime)

## review-backend-core
- accept: `Dockerfile`, `requirements.txt`, `anonymizer.py`, `config/settings.py`, `database.py`, `ai_client.py`, `main.py`
- defer: `crypto.py` как совместимый слой хранения (`pcenc:`), но не считать полноценным шифрованием
- compatibility: `database.py` зависит от `crypto.py`, поэтому файл оставлен в runtime

## review-frontend-conflicts
- конфликт `MM` у `static/index.html` снят: staged-версия сохранена в `archive/frontend-snapshots/index.staged.snapshot.html`
- рабочая версия оставлена в дереве как единый источник для дальнейшей проверки
- `static/anonymizer.js` оставлен как новый файл для клиентской анонимизации

## final-smoke-and-log
- smoke: `docker compose up -d --build project-chat` прошел успешно
- health: `GET /api/health` отвечает `status=ok`
- smoke script: `scripts/smoke_check.sh` выполнен успешно
- итог: конфликт staged/unstaged устранен, спорная staged-версия `static/index.html` архивирована в `archive/frontend-snapshots/index.staged.snapshot.html`
- отложено: полноценная замена `crypto.py` на настоящее шифрование
