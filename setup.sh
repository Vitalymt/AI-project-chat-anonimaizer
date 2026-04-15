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
    echo "Docker не найден."
    read -rp "Установить Docker автоматически? [Y/n]: " install_docker
    install_docker="${install_docker:-Y}"
    if [[ "$install_docker" =~ ^[Yy]$ ]]; then
        echo "Устанавливаю Docker..."
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        echo ""
        echo "Docker установлен. Чтобы изменения вступили в силу,"
        echo "выйдите и войдите снова, затем перезапустите setup.sh"
        echo "  newgrp docker && bash setup.sh"
        exit 0
    else
        echo "Установите Docker вручную и перезапустите setup.sh"
        exit 1
    fi
fi

# Проверить что демон запущен
if ! docker ps &>/dev/null; then
    echo "Docker демон не запущен. Запускаю..."
    sudo systemctl start docker || { echo "Не удалось запустить Docker. Запустите вручную."; exit 1; }
fi

echo "✓ Docker доступен"

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
    else
        write_env=1
    fi
else
    write_env=1
fi

if [[ "${write_env:-0}" == "1" ]]; then
    cat > .env <<EOF
AI_PROVIDER=${AI_PROVIDER}

OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
OPENROUTER_MODEL=${OPENROUTER_MODEL}

DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
DEEPSEEK_MODEL=${DEEPSEEK_MODEL}

PORT=${PORT}
DATA_PATH=./data
EOF
    echo "✓ .env создан"
fi

# Читаем PORT из .env на случай если не перезаписывали
PORT=$(grep -E "^PORT=" .env | cut -d= -f2 | tr -d '[:space:]')
PORT="${PORT:-8000}"

# ── 5. Сборка образа ──────────────────────────────────────────────────────────

echo ""
echo "📦 Сборка Docker-образа (первый раз ~3-5 минут)..."
docker build -t project-chat . || {
    echo ""
    echo "❌ Ошибка сборки. Смотри логи выше."
    exit 1
}
echo "✓ Образ собран"

# ── 6. Остановка старого контейнера ──────────────────────────────────────────

docker stop project-chat 2>/dev/null || true
docker rm   project-chat 2>/dev/null || true

# ── 7. Запуск контейнера ──────────────────────────────────────────────────────

mkdir -p ./data

docker run -d \
    --name project-chat \
    --restart unless-stopped \
    -p "${PORT}:8000" \
    --env-file .env \
    -v "$(pwd)/data:/app/data" \
    project-chat

echo "✓ Контейнер запущен"

# ── 8. Health-check ───────────────────────────────────────────────────────────

echo ""
echo -n "Ожидаю запуска сервиса"
started=0
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
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
    echo "   Логи: docker logs project-chat"
    exit 1
fi

# ── 9. Финальное сообщение ────────────────────────────────────────────────────

VM_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

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
echo "║    Логи:     docker logs project-chat -f                 ║"
echo "║    Стоп:     docker stop project-chat                    ║"
echo "║    Рестарт:  docker restart project-chat                 ║"
echo "║    Обновить: git pull && bash setup.sh                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
