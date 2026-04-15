#!/bin/bash
set -e

echo "🔄 Обновление ProjectChat..."

if [[ ! -f ".env" ]]; then
    echo "❌ Файл .env не найден. Запустите setup.sh"
    exit 1
fi

PORT=$(grep -E "^PORT=" .env | cut -d= -f2 | tr -d '[:space:]')
PORT="${PORT:-8000}"

# Обновить код
git pull

# Пересобрать образ
echo "📦 Сборка нового образа..."
docker build -t project-chat . --quiet || {
    echo "❌ Ошибка сборки."
    exit 1
}

# Перезапустить контейнер (данные в volume сохраняются)
docker stop project-chat 2>/dev/null || true
docker rm   project-chat 2>/dev/null || true

mkdir -p ./data

docker run -d \
    --name project-chat \
    --restart unless-stopped \
    -p "${PORT}:8000" \
    --env-file .env \
    -v "$(pwd)/data:/app/data" \
    project-chat

echo ""
echo "✅ Обновлено. Данные сохранены."
echo "   Доступно на: http://localhost:${PORT}"
