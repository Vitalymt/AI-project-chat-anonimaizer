# ProjectChat — AI ассистент для проектов

Интеллектуальный инструмент для работы с проектами, документами и AI-ассистентом. Поддерживает загрузку документов, автоматическую анонимизацию PII данных, общение с AI моделями и создание артефактов.

## 🎯 Основные возможности

- **Управление проектами** — создание, редактирование, организация проектов
- **Работа с документами** — загрузка PDF, DOCX, TXT файлов с автоматической анонимизацией
- **AI-чат** — общение с DeepSeek/OpenRouter моделями на основе документов проекта
- **Артефакты** — сохранение результатов работы AI в структурированном виде
- **Безопасность** — шифрование API ключей, опциональная аутентификация
- **Кастомизация** — темы, настройки AI параметров, шаблоны промптов

## Архитектура

- **Бэкенд:** FastAPI (Python 3.11+), асинхронный SQLite через `aiosqlite`
- **Фронтенд:** один статический HTML-файл с Vanilla JavaScript (без фреймворков)
- **Парсинг документов:** на клиенте (PDF.js для PDF, FileReader для TXT)
- **Анонимизация:** на клиенте, использует регулярные выражения из Chrome-расширения
- **AI-клиент:** поддержка OpenAI-совместимых API с потоковой передачей

## Установка и запуск

### Способ 1: Использование Docker (рекомендуется)

1. Клонируйте репозиторий:
   ```bash
   git clone <repository-url>
   cd project-chat
   ```

2. Запустите скрипт установки:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. Следуйте инструкциям скрипта:
   - Выберите провайдера AI (OpenRouter или DeepSeek)
   - Введите API ключ
   - Укажите порт (по умолчанию 8000)

4. После завершения установки приложение будет доступно по адресу:
   ```
   http://localhost:8000
   ```

### Способ 2: Ручная установка

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

2. Создайте файл `.env` на основе `.env.example`:
   ```bash
   cp .env.example .env
   # Отредактируйте .env, указав свои API ключи
   ```

3. Запустите сервер:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Откройте в браузере:
   ```
   http://localhost:8000
   ```

## Использование

### 1. Создание проекта
- Нажмите "Новый проект" в левой панели
- Укажите название и цель проекта
- Проект создастся с папками для оригинальных файлов и артефактов

### 2. Загрузка документов
- Перейдите на вкладку "Документы"
- Нажмите "Загрузить документ"
- Выберите PDF или TXT файл
- Файл будет обработан на клиенте:
  - Текст извлекается (PDF.js для PDF)
  - PII данные анонимизируются
  - Анонимизированный текст отправляется на сервер
  - Оригинальный файл сохраняется локально

### 3. Работа с чатами
- На вкладке "Чаты" создайте новый чат
- Введите сообщение - ответ будет приходить потоково
- AI использует контекст загруженных документов
- История сообщений сохраняется

### 4. Сохранение артефактов
- В правой панели нажмите "Сохранить"
- Сохраните важные результаты как артефакты
- Артефакты сохраняются в БД и в файлы

### 5. Настройки AI
- Нажмите "Настройки" в верхней панели
- Выберите провайдера (OpenRouter/DeepSeek)
- Введите API ключ (валидируется при сохранении)
- Укажите модель

## Структура проекта

```
project-chat/
├── main.py                 # FastAPI приложение и все роуты
├── ai_client.py           # Клиент для DeepSeek / OpenRouter (SSE)
├── database.py            # Инициализация БД и CRUD-функции
├── config/
│   └── settings.py       # Чтение .env и глобальные константы
├── static/
│   ├── index.html        # Весь фронтенд (три панели)
│   ├── patterns.js       # Регулярные выражения PII
│   ├── anonymizer.js     # Логика анонимизации на клиенте
│   ├── app.js           # Основная логика фронтенда
│   └── style.css        # Стили в темной теме
├── data/                 # Директория данных
│   ├── database.db      # SQLite база
│   └── projects/        # Файлы проектов
├── Dockerfile
├── requirements.txt
├── setup.sh             # Интерактивный скрипт установки
└── README.md
```

## База данных

### Схема SQLite:
```sql
-- Проекты
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    goal TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Документы
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    original_path TEXT,
    anonymized_text TEXT,
    anonymization_log TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready'
);

-- Чаты
CREATE TABLE chats (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Сообщения
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Артефакты
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chat_id TEXT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    file_path TEXT,
    created_at TEXT NOT NULL
);

-- Настройки
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

## Анонимизация PII

Приложение использует клиентскую анонимизацию с регулярными выражениями для:
- Российских телефонов
- Email адресов
- ИНН, СНИЛС
- Паспортных данных
- Банковских карт
- Адресов
- И других персональных данных

**Процесс:**
1. Файл обрабатывается на клиенте
2. PII заменяются на маркеры `[PII_TYPE_N]`
3. Создается карта замен
4. На сервер отправляется анонимизированный текст + карта
5. Оригинальный файл хранится локально

## API эндпоинты

### Проекты
- `GET /api/projects` - список проектов
- `POST /api/projects` - создать проект
- `GET /api/projects/{id}` - детали проекта + документы + чаты
- `DELETE /api/projects/{id}` - удалить проект

### Документы
- `POST /api/projects/{id}/documents` - загрузить документ
- `GET /api/projects/{id}/documents` - список документов
- `DELETE /api/projects/{id}/documents/{doc_id}` - удалить документ

### Чаты
- `POST /api/projects/{id}/chats` - создать чат
- `GET /api/projects/{id}/chats` - список чатов
- `GET /api/projects/{id}/chats/{chat_id}/messages` - история сообщений
- `POST /api/projects/{id}/chats/{chat_id}/messages` - отправить сообщение (SSE)

### Артефакты
- `POST /api/projects/{id}/artifacts` - сохранить артефакт
- `GET /api/projects/{id}/artifacts` - список артефактов

### Настройки
- `GET /api/settings` - текущие настройки
- `POST /api/settings` - обновить настройки

## Безопасность

- Все ID - UUID v4
- Анонимизация PII на клиенте
- Валидация API ключей при сохранении
- Ограничение размера файлов (50 MB)
- Проверка существования ресурсов
- SQL инъекции предотвращаются параметризованными запросами

## Разработка

### Требования
- Python 3.11+
- Node.js (для разработки фронтенда)
- Docker (для контейнеризации)

### Установка для разработки
```bash
# Клонирование
git clone <repository-url>
cd project-chat

# Виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или venv\Scripts\activate  # Windows

# Зависимости
pip install -r requirements.txt

# Запуск
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Структура фронтенда
Фронтенд реализован на Vanilla JavaScript с использованием:
- **marked.js** - рендеринг Markdown
- **highlight.js** - подсветка кода
- **PDF.js** - обработка PDF файлов
- **CSS Grid/Flexbox** - трехпанельный интерфейс

## Лицензия

MIT

## Поддержка

Для сообщений об ошибках и предложений создавайте issue в репозитории проекта.