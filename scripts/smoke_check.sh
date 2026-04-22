#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
AUTH_ENABLED="${AUTH_ENABLED:-false}"
AUTH_USERNAME="${AUTH_USERNAME:-}"
AUTH_PASSWORD="${AUTH_PASSWORD:-}"

health_cmd=(curl -sS -f)
if [[ "$AUTH_ENABLED" =~ ^(true|1|yes|on)$ ]]; then
  if [[ -z "$AUTH_USERNAME" || -z "$AUTH_PASSWORD" ]]; then
    echo "AUTH включен, но AUTH_USERNAME/AUTH_PASSWORD не заданы" >&2
    exit 1
  fi
  health_cmd+=( -u "${AUTH_USERNAME}:${AUTH_PASSWORD}" )
fi

"${health_cmd[@]}" "${BASE_URL}/api/health" >/dev/null

echo "health: ok"
echo "Проверка API без ключа (ожидается контролируемая ошибка)"
echo "1) Создай проект через POST /api/projects"
echo "2) Создай чат через POST /api/projects/{id}/chats"
echo "3) Отправь сообщение в /messages и убедись, что возвращается понятная ошибка о ключе"
