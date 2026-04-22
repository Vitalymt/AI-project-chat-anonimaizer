#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       🚀 ProjectChat — установка         ║"
echo "║  ~3-5 минут (скачивается spaCy ~500MB)   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Проверка Docker ────────────────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "Docker не найден. Установите Docker и Docker Compose вручную, затем перезапустите setup.sh"
    exit 1
fi

# Проверить что демон запущен
if ! docker ps &>/dev/null; then
    echo "Docker демон не запущен. Запускаю..."
    sudo systemctl start docker || { echo "Не удалось запустить Docker. Запустите вручную."; exit 1; }
fi

echo "✓ Docker доступен"

if ! docker compose version &>/dev/null; then
    echo "Нужен Docker Compose v2 (команда «docker compose»). Установи plugin и перезапусти setup.sh."
    exit 1
fi

ensure_env_key() {
    local key="$1"
    local value="$2"
    if ! grep -qE "^${key}=" .env 2>/dev/null; then
        echo "${key}=${value}" >> .env
    fi
}

set_env_key() {
    local key="$1"
    local value="$2"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        sed -i "s#^${key}=.*#${key}=${value}#g" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

# ── 2. Выбор провайдера ───────────────────────────────────────────────────────

echo ""
echo "Выберите AI провайдер:"
echo "  1) OpenRouter  (рекомендуется — много моделей)"
echo "  2) DeepSeek    (дешевле, только DeepSeek-модели)"
read -rp "Введите 1 или 2 [1]: " provider_choice
provider_choice="${provider_choice:-1}"

if [[ "$provider_choice" == "2" ]]; then
    AI_PROVIDER="deepseek"
    read -rp "Введите DeepSeek API ключ (sk-...): " DEEPSEEK_API_KEY
    while [[ -z "$DEEPSEEK_API_KEY" ]]; do
        echo "API ключ не может быть пустым."
        read -rp "Введите DeepSeek API ключ: " DEEPSEEK_API_KEY
    done
    read -rp "Модель [deepseek-chat]: " DEEPSEEK_MODEL
    DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-chat}"
    OPENROUTER_API_KEY=""
    OPENROUTER_MODEL="openai/gpt-4o-mini"
else
    AI_PROVIDER="openrouter"
    read -rp "Введите OpenRouter API ключ (sk-or-... или sk-...): " OPENROUTER_API_KEY
    while [[ -z "$OPENROUTER_API_KEY" ]]; do
        echo "API ключ не может быть пустым."
        read -rp "Введите OpenRouter API ключ: " OPENROUTER_API_KEY
    done
    read -rp "Модель [openai/gpt-4o-mini]: " OPENROUTER_MODEL
    OPENROUTER_MODEL="${OPENROUTER_MODEL:-openai/gpt-4o-mini}"
    DEEPSEEK_API_KEY=""
    DEEPSEEK_MODEL="deepseek-chat"
fi

# ── 3. Порт ───────────────────────────────────────────────────────────────────

while true; do
    read -rp "Порт для веб-интерфейса [8000]: " PORT
    PORT="${PORT:-8000}"
    if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        echo "Некорректный порт. Введите число от 1 до 65535."
        continue
    fi
    if ss -tlnp 2>/dev/null | grep -q ":${PORT} " || \
       netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        echo "⚠ Порт $PORT занят. Выберите другой."
        continue
    fi
    break
done

# ── 4. Генерация .env ─────────────────────────────────────────────────────────

if [[ -f ".env" ]]; then
    read -rp "Файл .env уже существует. Перезаписать? [y/N]: " overwrite
    overwrite="${overwrite:-N}"
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "Используется существующий .env"
        read -rp "Проверить/починить Vault-конфигурацию в существующем .env? [Y/n]: " repair_vault
        repair_vault="${repair_vault:-Y}"
        if [[ "$repair_vault" =~ ^[Yy]$ ]]; then
            ensure_env_key OBSIDIAN_ENABLED false
            ensure_env_key OBSIDIAN_VAULT_PATH ./obsidian-vault
            ensure_env_key VAULT_AUTO_LOG_CHATS false
            ensure_env_key VAULT_AI_FOLDER AI-Generated
            ensure_env_key WEBDAV_PORT 8081
            ensure_env_key WEBDAV_USER obsidian
            ensure_env_key WEBDAV_PASSWORD ""

            vault_enabled_now=$(grep -E "^OBSIDIAN_ENABLED=" .env | cut -d= -f2 | tr -d '[:space:]')
            if [[ "$vault_enabled_now" =~ ^(true|1|yes|on)$ ]]; then
                mkdir -p ./obsidian-vault
                webdav_pwd=$(grep -E "^WEBDAV_PASSWORD=" .env | cut -d= -f2-)
                if [[ -z "$webdav_pwd" || "$webdav_pwd" == "\"\"" ]]; then
                    read -rp "WEBDAV_PASSWORD пуст. Введите пароль: " fixed_pwd
                    while [[ -z "$fixed_pwd" ]]; do
                        read -rp "Пароль не может быть пустым. Введите WEBDAV_PASSWORD: " fixed_pwd
                    done
                    set_env_key WEBDAV_PASSWORD "$fixed_pwd"
                fi
            fi
            echo "✓ Проверка/починка vault-конфига завершена"
        fi
    else
        write_env=1
    fi
else
    write_env=1
fi

if [[ "${write_env:-0}" == "1" ]]; then
    OBSIDIAN_ENABLED=false
    OBSIDIAN_VAULT_PATH=./obsidian-vault
    WEBDAV_PORT=8081
    WEBDAV_USER=obsidian
    WEBDAV_PASSWORD=""
    VAULT_AUTO_LOG_CHATS=false
    VAULT_AI_FOLDER=AI-Generated

    echo ""
    echo "─────────────────────────────────────────────────────────"
    echo "  Интеграция с Obsidian Vault (опционально)"
    echo "─────────────────────────────────────────────────────────"
    read -rp "Подключить Obsidian vault + WebDAV на этой VM? [y/N]: " vault_enable
    vault_enable="${vault_enable:-N}"
    if [[ "$vault_enable" =~ ^[Yy]$ ]]; then
        OBSIDIAN_ENABLED=true
        mkdir -p ./obsidian-vault
        read -rp "Пароль WebDAV для плагина Remotely Save в Obsidian: " WEBDAV_PASSWORD
        while [[ -z "$WEBDAV_PASSWORD" ]]; do
            read -rp "Пароль не может быть пустым, введите снова: " WEBDAV_PASSWORD
        done
        while true; do
            read -rp "Порт WebDAV [8081]: " WEBDAV_PORT
            WEBDAV_PORT="${WEBDAV_PORT:-8081}"
            if ! [[ "$WEBDAV_PORT" =~ ^[0-9]+$ ]] || [ "$WEBDAV_PORT" -lt 1 ] || [ "$WEBDAV_PORT" -gt 65535 ]; then
                echo "Некорректный порт."
                continue
            fi
            if ss -tlnp 2>/dev/null | grep -q ":${WEBDAV_PORT} " || \
               netstat -tlnp 2>/dev/null | grep -q ":${WEBDAV_PORT} "; then
                echo "⚠ Порт $WEBDAV_PORT занят. Выберите другой."
                continue
            fi
            break
        done
        read -rp "Автоматически дописывать чаты в vault (Chats/дата.md)? [y/N]: " auto_log
        auto_log="${auto_log:-N}"
        if [[ "$auto_log" =~ ^[Yy]$ ]]; then
            VAULT_AUTO_LOG_CHATS=true
        fi
    fi

    cat > .env <<EOF
AI_PROVIDER=${AI_PROVIDER}

OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
OPENROUTER_MODEL=${OPENROUTER_MODEL}

DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
DEEPSEEK_MODEL=${DEEPSEEK_MODEL}

PORT=${PORT}
DATA_PATH=./data

# Obsidian vault + WebDAV
OBSIDIAN_ENABLED=${OBSIDIAN_ENABLED}
OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}
VAULT_AUTO_LOG_CHATS=${VAULT_AUTO_LOG_CHATS}
VAULT_AI_FOLDER=${VAULT_AI_FOLDER}
WEBDAV_PORT=${WEBDAV_PORT}
WEBDAV_USER=${WEBDAV_USER}
WEBDAV_PASSWORD=${WEBDAV_PASSWORD}
EOF
    echo "✓ .env создан"
fi

# Читаем PORT из .env на случай если не перезаписывали
PORT=$(grep -E "^PORT=" .env | cut -d= -f2 | tr -d '[:space:]')
PORT="${PORT:-8000}"
AUTH_ENABLED=$(grep -E "^AUTH_ENABLED=" .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
AUTH_ENABLED="${AUTH_ENABLED:-false}"
AUTH_USERNAME=$(grep -E "^AUTH_USERNAME=" .env 2>/dev/null | cut -d= -f2-)
AUTH_PASSWORD=$(grep -E "^AUTH_PASSWORD=" .env 2>/dev/null | cut -d= -f2-)

# ── 5. Остановка старых контейнеров ───────────────────────────────────────────

docker compose down 2>/dev/null || true
docker stop project-chat obsidian-webdav 2>/dev/null || true
docker rm project-chat obsidian-webdav 2>/dev/null || true

# ── 6. Запуск docker compose (сборка при необходимости) ───────────────────────

mkdir -p ./data ./obsidian-vault

echo ""
echo "📦 Сборка и запуск контейнеров (первый раз ~3-5 минут)…"

if grep -qE '^OBSIDIAN_ENABLED[[:space:]]*=[[:space:]]*true' .env 2>/dev/null; then
    echo "Запуск: project-chat + webdav (профиль vault)…"
    docker compose --profile vault up -d --build || {
        echo ""
        echo "❌ docker compose не смог поднять сервисы. Смотри логи: docker compose logs"
        exit 1
    }
else
    echo "Запуск: только project-chat (WebDAV отключён в .env)…"
    docker compose up -d --build || {
        echo ""
        echo "❌ docker compose не смог поднять сервисы. Смотри логи: docker compose logs"
        exit 1
    }
fi

echo "✓ Контейнеры запущены"

# ── 7. Health-check ───────────────────────────────────────────────────────────

echo ""
echo -n "Ожидаю запуска сервиса"
started=0
for i in $(seq 1 30); do
    if [[ "$AUTH_ENABLED" =~ ^(true|1|yes|on)$ ]]; then
        if [[ -n "$AUTH_USERNAME" && -n "$AUTH_PASSWORD" ]] && curl -sf -u "${AUTH_USERNAME}:${AUTH_PASSWORD}" "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
            started=1
            break
        fi
    elif curl -sf "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
        started=1
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

if [[ "$started" == "0" ]]; then
    echo ""
    echo "❌ Сервис не поднялся за 60 секунд."
    if [[ "$AUTH_ENABLED" =~ ^(true|1|yes|on)$ ]]; then
        echo "   Подсказка: AUTH включен. Добавь AUTH_USERNAME/AUTH_PASSWORD в .env для health-check."
    fi
    echo "   Логи: docker compose logs project-chat"
    exit 1
fi

# Health-check WebDAV при включенном vault
if grep -qE '^OBSIDIAN_ENABLED[[:space:]]*=[[:space:]]*true' .env 2>/dev/null; then
    WEBDAV_PORT_MSG=$(grep -E "^WEBDAV_PORT=" .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo "8081")
    WEBDAV_PORT_MSG="${WEBDAV_PORT_MSG:-8081}"
    webdav_started=0
    for i in $(seq 1 20); do
        if curl -sf "http://localhost:${WEBDAV_PORT_MSG}" >/dev/null 2>&1; then
            webdav_started=1
            break
        fi
        sleep 1
    done
    if [[ "$webdav_started" == "1" ]]; then
        echo "✓ WebDAV доступен на порту ${WEBDAV_PORT_MSG}"
    else
        echo "⚠ WebDAV пока недоступен на порту ${WEBDAV_PORT_MSG} (проверь docker compose logs webdav)"
    fi
fi

# ── 8. Финальное сообщение ────────────────────────────────────────────────────

VM_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
WEBDAV_PORT_MSG=$(grep -E "^WEBDAV_PORT=" .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo "8081")
WEBDAV_PORT_MSG="${WEBDAV_PORT_MSG:-8081}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              ✅ ProjectChat запущен!                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Открывай в браузере:                                    ║"
echo "║    → http://localhost:${PORT}                               ║"
if [[ -n "$VM_IP" ]]; then
echo "║    → http://${VM_IP}:${PORT}                          ║"
fi
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  SSH-туннель (с локальной машины):                       ║"
echo "║    ssh -L ${PORT}:localhost:${PORT} user@VM_IP              ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Полезные команды:                                       ║"
echo "║    Логи:     docker compose logs -f project-chat         ║"
echo "║    Стоп:     docker compose down                         ║"
echo "║    Обновить: git pull && bash setup.sh                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if grep -qE '^OBSIDIAN_ENABLED[[:space:]]*=[[:space:]]*true' .env 2>/dev/null; then
    echo "📚 Obsidian WebDAV: http://${VM_IP:-localhost}:${WEBDAV_PORT_MSG}"
    echo "   В Obsidian: плагин Remotely Save → WebDAV"
    echo "   Server URL: http://<VM_IP>:${WEBDAV_PORT_MSG}"
    echo "   Username:   ${WEBDAV_USER:-obsidian}"
    echo "   Password:   (как в .env WEBDAV_PASSWORD)"
    echo ""
    echo "Как наблюдать наполнение vault:"
    echo "  1) Открой Obsidian на Windows и целевую заметку"
    echo "  2) В Remotely Save установи короткий интервал sync (10-30 сек)"
    echo "  3) В ProjectChat нажми «Наблюдать в Obsidian» под ответом AI"
    echo "  4) Для мгновенного обновления нажимай Sync в плагине"
    echo ""
fi
