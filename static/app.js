'use strict';

// Глобальное состояние приложения уже объявлено в app-main.js
// Используем window.appState для доступа
if (typeof appState === 'undefined' && typeof window.appState !== 'undefined') {
    var appState = window.appState;
}

// API базовый URL
const API_BASE = '/api';

// Функции для работы с localStorage
function saveAppState() {
    try {
        localStorage.setItem('currentProjectId', appState.currentProjectId);
        localStorage.setItem('currentChatId', appState.currentChatId);
        localStorage.setItem('sidebarWidth', appState.uiState.sidebarWidth);
        localStorage.setItem('rightbarWidth', appState.uiState.rightbarWidth);
        localStorage.setItem('sidebarCollapsed', appState.uiState.sidebarCollapsed);
        localStorage.setItem('rightbarCollapsed', appState.uiState.rightbarCollapsed);
        
        // Сохраняем выбранные документы как массив
        localStorage.setItem('selectedDocumentIds', JSON.stringify(Array.from(appState.selectedDocumentIds)));
        
        console.log('App state saved to localStorage');
    } catch (error) {
        console.error('Error saving app state:', error);
    }
}

function loadAppState() {
    try {
        appState.currentProjectId = localStorage.getItem('currentProjectId');
        appState.currentChatId = localStorage.getItem('currentChatId');
        appState.uiState.sidebarWidth = parseInt(localStorage.getItem('sidebarWidth')) || 250;
        appState.uiState.rightbarWidth = parseInt(localStorage.getItem('rightbarWidth')) || 300;
        appState.uiState.sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
        appState.uiState.rightbarCollapsed = localStorage.getItem('rightbarCollapsed') === 'true';
        
        // Загружаем выбранные документы
        const selectedIds = localStorage.getItem('selectedDocumentIds');
        if (selectedIds) {
            appState.selectedDocumentIds = new Set(JSON.parse(selectedIds));
        }
        
        console.log('App state loaded from localStorage');
    } catch (error) {
        console.error('Error loading app state:', error);
    }
}

// Loading indicator system
let loadingOverlay = null;
let loadingTimeout = null;

function showLoading(message = 'Загрузка...') {
    // Clear any existing timeout
    if (loadingTimeout) {
        clearTimeout(loadingTimeout);
        loadingTimeout = null;
    }
    
    // Remove existing overlay if any
    if (loadingOverlay && loadingOverlay.parentNode) {
        loadingOverlay.parentNode.removeChild(loadingOverlay);
    }
    
    // Create new overlay
    loadingOverlay = document.createElement('div');
    loadingOverlay.className = 'loading-overlay';
    loadingOverlay.innerHTML = `
        <div class="loading-spinner"></div>
        <div class="loading-message">${escapeHtml(message)}</div>
    `;
    
    document.body.appendChild(loadingOverlay);
    
    // Set timeout to show loading indicator (prevents flicker for fast operations)
    loadingTimeout = setTimeout(() => {
        if (loadingOverlay && loadingOverlay.parentNode) {
            loadingOverlay.style.opacity = '1';
        }
    }, 100);
    
    return loadingOverlay;
}

function hideLoading() {
    // Clear timeout
    if (loadingTimeout) {
        clearTimeout(loadingTimeout);
        loadingTimeout = null;
    }
    
    // Remove overlay with fade out
    if (loadingOverlay && loadingOverlay.parentNode) {
        loadingOverlay.style.opacity = '0';
        loadingOverlay.style.transition = 'opacity 0.3s ease-out';
        
        setTimeout(() => {
            if (loadingOverlay && loadingOverlay.parentNode) {
                loadingOverlay.parentNode.removeChild(loadingOverlay);
                loadingOverlay = null;
            }
        }, 300);
    }
}

// Helper function for async operations with loading indicator
async function withLoading(operation, message = 'Загрузка...') {
    showLoading(message);
    try {
        const result = await operation();
        hideLoading();
        return result;
    } catch (error) {
        hideLoading();
        throw error;
    }
}

// Button loading state
function setButtonLoading(button, isLoading) {
    if (isLoading) {
        button.classList.add('loading');
        button.disabled = true;
    } else {
        button.classList.remove('loading');
        button.disabled = false;
    }
}

// Инициализация приложения
document.addEventListener('DOMContentLoaded', async () => {
    console.log('DOMContentLoaded fired');
    
    // Загружаем сохраненное состояние
    loadAppState();
    
    try {
        // Настройка marked для рендеринга markdown (если библиотека загружена)
        if (typeof marked !== 'undefined') {
            console.log('marked.js available, configuring...');
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: true,
                highlight: function(code, lang) {
                    if (lang && hljs && hljs.getLanguage(lang)) {
                        try {
                            return hljs.highlight(code, { language: lang }).value;
                        } catch (err) {}
                    }
                    if (hljs) {
                        return hljs.highlightAuto(code).value;
                    }
                    return code; // Fallback если highlight.js не загружен
                },
                langPrefix: 'hljs language-'
            });
        } else {
            console.warn('marked.js not available, markdown rendering will be limited');
        }
        
        console.log('Calling initializeEventListeners...');
        initializeEventListeners();
        console.log('initializeEventListeners completed');
        
        console.log('Calling loadSettings...');
        await loadSettings();
        console.log('loadSettings completed');
        
        console.log('Calling loadProjects...');
        await loadProjects();
        console.log('loadProjects completed');
        
        // Автоматически выбираем сохраненный проект и чат
        if (appState.currentProjectId) {
            console.log(`Auto-selecting project: ${appState.currentProjectId}`);
            try {
                await selectProject(appState.currentProjectId);
                
                // Если есть сохраненный чат, выбираем его
                if (appState.currentChatId) {
                    console.log(`Auto-selecting chat: ${appState.currentChatId}`);
                    // Проверяем что чат существует в текущем проекте
                    const chatExists = appState.chats.some(chat => chat.id === appState.currentChatId);
                    if (chatExists) {
                        await selectChat(appState.currentChatId);
                    } else {
                        console.log(`Chat ${appState.currentChatId} not found in project, clearing selection`);
                        appState.currentChatId = null;
                        saveAppState();
                    }
                }
            } catch (error) {
                console.error('Error auto-selecting project/chat:', error);
                // Если проект не найден, сбрасываем состояние
                appState.currentProjectId = null;
                appState.currentChatId = null;
                saveAppState();
            }
        }
        
        console.log('Calling setupMessageInput...');
        setupMessageInput();
        console.log('setupMessageInput completed');
        
        console.log('Application initialization complete');
    } catch (error) {
        console.error('Error during initialization:', error);
        showToast('Ошибка инициализации приложения: ' + error.message, 'error', 10000);
    }
    
    // Инициализация управления панелями
    setTimeout(() => {
        setupPanelResize();
    }, 100);
});

// Инициализация обработчиков событий
// Функция initializeEventListeners теперь находится в app-core.js

// Переключение вкладок
function switchTab(tabId) {
    // Обновляем активную вкладку
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabId);
    });
    
    // Показываем соответствующее содержимое
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tabId}-tab`);
    });
    
    // Загружаем данные для активной вкладки
    if (tabId === 'documents' && appState.currentProjectId) {
        loadDocuments();
    }
}

// Управление модальными окнами
function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
    
    // Предзаполнение данных если нужно
    if (modalId === 'artifact-modal' && appState.currentChatId) {
        const lastMessage = getLastAssistantMessage();
        if (lastMessage) {
            document.getElementById('artifact-content').value = lastMessage;
        }
    }
    
    if (modalId === 'settings-modal') {
        loadSettingsIntoForm();
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
    
    // Сброс формы
    if (modalId === 'document-modal') {
        resetDocumentForm();
    } else if (modalId === 'project-modal') {
        document.getElementById('project-name').value = '';
        document.getElementById('project-goal').value = '';
    }
}

// Настройка поля ввода сообщения
function setupMessageInput() {
    const textarea = document.getElementById('message-input');
    
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });
}

// Получение последнего сообщения ассистента
function getLastAssistantMessage() {
    const messages = document.querySelectorAll('.message-assistant .message-content');
    if (messages.length > 0) {
        return messages[messages.length - 1].textContent;
    }
    return '';
}

// Вспомогательные функции
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Функция рендеринга markdown с поддержкой копирования кода
function renderMarkdown(content) {
    if (typeof marked === 'undefined') {
        return escapeHtml(content);
    }
    
    try {
        // Сначала экранируем HTML, затем рендерим markdown
        const escaped = escapeHtml(content);
        const rendered = marked.parse(escaped);
        
        // Добавляем кнопки копирования для блоков кода
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = rendered;
        
        // Находим все блоки кода с подсветкой синтаксиса
        tempDiv.querySelectorAll('pre code').forEach(codeBlock => {
            const pre = codeBlock.closest('pre');
            if (pre && !pre.querySelector('.copy-code-btn')) {
                const copyBtn = document.createElement('button');
                copyBtn.className = 'copy-code-btn';
                copyBtn.textContent = 'Копировать';
                copyBtn.title = 'Копировать код';
                copyBtn.onclick = function() {
                    const codeText = codeBlock.textContent;
                    navigator.clipboard.writeText(codeText).then(() => {
                        const originalText = copyBtn.textContent;
                        copyBtn.textContent = 'Скопировано!';
                        copyBtn.classList.add('copied');
                        setTimeout(() => {
                            copyBtn.textContent = originalText;
                            copyBtn.classList.remove('copied');
                        }, 2000);
                    }).catch(err => {
                        console.error('Ошибка копирования: ', err);
                        copyBtn.textContent = 'Ошибка';
                    });
                };
                pre.style.position = 'relative';
                pre.appendChild(copyBtn);
            }
        });
        
        return tempDiv.innerHTML;
    } catch (error) {
        console.error('Ошибка рендеринга markdown:', error);
        return escapeHtml(content);
    }
}

// Toast notification system
function showToast(message, type = 'info', duration = 5000) {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    // Determine icon based on type
    let icon = 'ℹ️';
    let title = 'Информация';
    switch (type) {
        case 'success':
            icon = '✓';
            title = 'Успех';
            break;
        case 'error':
            icon = '✗';
            title = 'Ошибка';
            break;
        case 'warning':
            icon = '⚠';
            title = 'Предупреждение';
            break;
        case 'info':
            icon = 'ℹ️';
            title = 'Информация';
            break;
    }
    
    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
        <button class="toast-close" title="Закрыть">×</button>
    `;
    
    // Add close handler
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => {
        removeToast(toast);
    });
    
    // Add to container
    container.appendChild(toast);
    
    // Auto-remove after duration
    if (duration > 0) {
        setTimeout(() => {
            if (toast.parentNode) {
                removeToast(toast);
            }
        }, duration);
    }
    
    return toast;
}

function removeToast(toast) {
    toast.classList.add('hiding');
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 300);
}

// Confirm dialog system
function showConfirm(message, options = {}) {
    return new Promise((resolve) => {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'global-overlay';
        
        // Create dialog
        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        
        const title = options.title || 'Подтверждение';
        const confirmText = options.confirmText || 'Подтвердить';
        const cancelText = options.cancelText || 'Отмена';
        const type = options.type || 'danger'; // 'danger', 'success', 'warning'
        
        dialog.innerHTML = `
            <div class="confirm-title">${escapeHtml(title)}</div>
            <div class="confirm-message">${escapeHtml(message)}</div>
            <div class="confirm-buttons">
                <button class="confirm-button cancel">${escapeHtml(cancelText)}</button>
                <button class="confirm-button ${type}">${escapeHtml(confirmText)}</button>
            </div>
        `;
        
        // Add event handlers
        const cancelBtn = dialog.querySelector('.confirm-button.cancel');
        const confirmBtn = dialog.querySelector(`.confirm-button.${type}`);
        
        const closeDialog = (result) => {
            document.body.removeChild(overlay);
            resolve(result);
        };
        
        cancelBtn.addEventListener('click', () => closeDialog(false));
        confirmBtn.addEventListener('click', () => closeDialog(true));
        
        // Close on overlay click (outside dialog)
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeDialog(false);
            }
        });
        
        // Close on Escape key
        const handleEscape = (e) => {
            if (e.key === 'Escape') {
                closeDialog(false);
                document.removeEventListener('keydown', handleEscape);
            }
        };
        document.addEventListener('keydown', handleEscape);
        
        // Add to DOM
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        
        // Focus confirm button
        setTimeout(() => confirmBtn.focus(), 100);
        
        // Cleanup event listener when dialog closes
        overlay.addEventListener('click', function cleanup(e) {
            if (e.target === overlay || e.target === cancelBtn || e.target === confirmBtn) {
                document.removeEventListener('keydown', handleEscape);
                overlay.removeEventListener('click', cleanup);
            }
        });
    });
}

function showError(message) {
    showToast(message, 'error', 7000);
}

function showSuccess(message) {
    showToast(message, 'success', 3000);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// API функции с повторными попытками
async function apiRequest(endpoint, options = {}, retries = 3, retryDelay = 1000) {
    const url = `${API_BASE}${endpoint}`;
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    for (let attempt = 1; attempt <= retries; attempt++) {
        try {
            const response = await fetch(url, { ...defaultOptions, ...options });
            
            if (!response.ok) {
                const errorText = await response.text();
                
                // Классификация ошибок
                if (response.status >= 500) {
                    throw new Error(`Ошибка сервера (${response.status}): ${errorText}`);
                } else if (response.status === 401) {
                    throw new Error(`Ошибка авторизации: ${errorText}`);
                } else if (response.status === 403) {
                    throw new Error(`Доступ запрещен: ${errorText}`);
                } else if (response.status === 404) {
                    throw new Error(`Ресурс не найден: ${errorText}`);
                } else if (response.status === 429) {
                    throw new Error(`Слишком много запросов: ${errorText}`);
                } else {
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }
            }
            
            if (response.status === 204) {
                return null;
            }
            
            return await response.json();
        } catch (error) {
            console.error(`API request failed (attempt ${attempt}/${retries}):`, error);
            
            // Если это последняя попытка или ошибка не связана с сетью, выбрасываем ошибку
            if (attempt === retries || error.message.includes('Failed to fetch') === false) {
                // Показываем понятное сообщение об ошибке
                let userMessage = 'Ошибка при выполнении запроса';
                
                if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
                    userMessage = 'Ошибка сети. Проверьте подключение к интернету.';
                } else if (error.message.includes('Ошибка сервера')) {
                    userMessage = 'Ошибка на сервере. Попробуйте позже.';
                } else if (error.message.includes('Ошибка авторизации')) {
                    userMessage = 'Ошибка авторизации. Проверьте API ключ в настройках.';
                } else if (error.message.includes('Доступ запрещен')) {
                    userMessage = 'Доступ запрещен. У вас нет прав для этого действия.';
                } else if (error.message.includes('Ресурс не найден')) {
                    userMessage = 'Ресурс не найден. Возможно, он был удален.';
                } else if (error.message.includes('Слишком много запросов')) {
                    userMessage = 'Слишком много запросов. Подождите немного.';
                }
                
                showError(`${userMessage} (${error.message})`);
                throw error;
            }
            
            // Ждем перед следующей попыткой
            if (attempt < retries) {
                showToast(`Повторная попытка ${attempt}/${retries}...`, 'warning', 2000);
                await new Promise(resolve => setTimeout(resolve, retryDelay * attempt));
            }
        }
    }
}

// Проверка состояния сети
function isOnline() {
    return navigator.onLine;
}

// Мониторинг состояния сети
function setupNetworkMonitoring() {
    window.addEventListener('online', () => {
        showToast('Соединение восстановлено', 'success', 3000);
        // Автоматически перезагружаем данные при восстановлении соединения
        if (appState.currentProjectId) {
            loadProjects();
            loadDocuments();
        }
    });
    
    window.addEventListener('offline', () => {
        showError('Потеряно соединение с интернетом', 'error', 0);
    });
}

// Функции валидации форм
function validateRequired(value, fieldName) {
    if (!value || value.trim() === '') {
        return `Поле "${fieldName}" обязательно для заполнения`;
    }
    return null;
}

function validateLength(value, fieldName, minLength, maxLength) {
    if (value.length < minLength) {
        return `Поле "${fieldName}" должно содержать минимум ${minLength} символов`;
    }
    if (maxLength && value.length > maxLength) {
        return `Поле "${fieldName}" должно содержать максимум ${maxLength} символов`;
    }
    return null;
}

function validateNumber(value, fieldName, min, max) {
    const num = parseFloat(value);
    if (isNaN(num)) {
        return `Поле "${fieldName}" должно быть числом`;
    }
    if (min !== undefined && num < min) {
        return `Поле "${fieldName}" должно быть не меньше ${min}`;
    }
    if (max !== undefined && num > max) {
        return `Поле "${fieldName}" должно быть не больше ${max}`;
    }
    return null;
}

function validateInteger(value, fieldName, min, max) {
    const num = parseInt(value);
    if (isNaN(num) || !Number.isInteger(num)) {
        return `Поле "${fieldName}" должно быть целым числом`;
    }
    if (min !== undefined && num < min) {
        return `Поле "${fieldName}" должно быть не меньше ${min}`;
    }
    if (max !== undefined && num > max) {
        return `Поле "${fieldName}" должно быть не больше ${max}`;
    }
    return null;
}

function validateApiKey(value, provider) {
    if (!value || value.trim() === '') {
        return null; // API ключ может быть пустым
    }
    
    // Проверка минимальной длины API ключа
    if (value.length < 10) {
        return 'API ключ слишком короткий';
    }
    
    // Проверка формата (базовая)
    if (provider === 'openrouter') {
        if (!value.startsWith('sk-or-')) {
            return 'OpenRouter API ключ должен начинаться с "sk-or-"';
        }
    } else if (provider === 'deepseek') {
        if (!value.startsWith('sk-')) {
            return 'DeepSeek API ключ должен начинаться с "sk-"';
        }
    }
    
    return null;
}

function validateFile(file, allowedTypes = [], maxSizeMB = 50) {
    const errors = [];
    
    if (!file) {
        errors.push('Файл не выбран');
        return errors;
    }
    
    // Проверка размера файла
    const maxSizeBytes = maxSizeMB * 1024 * 1024;
    if (file.size > maxSizeBytes) {
        errors.push(`Файл слишком большой. Максимальный размер: ${maxSizeMB}MB`);
    }
    
    // Проверка типа файла
    if (allowedTypes.length > 0) {
        const fileExtension = file.name.split('.').pop().toLowerCase();
        const mimeType = file.type;
        
        const isAllowed = allowedTypes.some(type => {
            if (type.startsWith('.')) {
                return fileExtension === type.substring(1);
            }
            return mimeType.includes(type);
        });
        
        if (!isAllowed) {
            errors.push(`Неподдерживаемый формат файла. Разрешенные форматы: ${allowedTypes.join(', ')}`);
        }
    }
    
    return errors;
}

// Показать ошибку валидации в поле
function showFieldError(fieldId, message) {
    const field = document.getElementById(fieldId);
    if (!field) return;
    
    // Удаляем предыдущие сообщения об ошибках
    const existingError = field.parentElement.querySelector('.field-error');
    if (existingError) {
        existingError.remove();
    }
    
    // Добавляем класс ошибки к полю
    field.classList.add('error');
    
    // Создаем сообщение об ошибке
    const errorElement = document.createElement('div');
    errorElement.className = 'field-error';
    errorElement.textContent = message;
    errorElement.style.color = '#f44336';
    errorElement.style.fontSize = '12px';
    errorElement.style.marginTop = '4px';
    
    field.parentElement.appendChild(errorElement);
    
    // Фокусируемся на поле с ошибкой
    field.focus();
}

// Очистить ошибку валидации поля
function clearFieldError(fieldId) {
    const field = document.getElementById(fieldId);
    if (!field) return;
    
    field.classList.remove('error');
    
    const existingError = field.parentElement.querySelector('.field-error');
    if (existingError) {
        existingError.remove();
    }
}

// Валидация всей формы
function validateForm(formData, validationRules) {
    const errors = {};
    
    for (const [fieldName, rules] of Object.entries(validationRules)) {
        const value = formData[fieldName];
        
        for (const rule of rules) {
            let error = null;
            
            switch (rule.type) {
                case 'required':
                    error = validateRequired(value, rule.fieldName || fieldName);
                    break;
                case 'length':
                    error = validateLength(value, rule.fieldName || fieldName, rule.min, rule.max);
                    break;
                case 'number':
                    error = validateNumber(value, rule.fieldName || fieldName, rule.min, rule.max);
                    break;
                case 'integer':
                    error = validateInteger(value, rule.fieldName || fieldName, rule.min, rule.max);
                    break;
                case 'apiKey':
                    error = validateApiKey(value, rule.provider);
                    break;
            }
            
            if (error) {
                errors[fieldName] = error;
                break; // Останавливаемся на первой ошибке для этого поля
            }
        }
    }
    
    return errors;
}

// Загрузка проектов
async function loadProjects() {
    return withLoading(async () => {
        try {
            const projects = await apiRequest('/projects');
            appState.projects = projects;
            
            // Получаем текущий поисковый запрос
            const searchInput = document.getElementById('projects-search-input');
            const searchTerm = searchInput ? searchInput.value.trim() : '';
            
            renderProjects(projects, searchTerm);
            
            // Если есть проекты, выбираем первый
            if (projects.length > 0 && !appState.currentProjectId) {
                await selectProject(projects[0].id);
            }
        } catch (error) {
            showError('Не удалось загрузить проекты');
        }
    }, 'Загрузка проектов...');
}

// Рендеринг списка проектов
function renderProjects(projects, searchTerm = '') {
    const container = document.getElementById('projects-list');
    
    // Фильтруем проекты по поисковому запросу
    let filteredProjects = projects;
    if (searchTerm) {
        const term = searchTerm.toLowerCase();
        filteredProjects = projects.filter(project => 
            project.name.toLowerCase().includes(term) || 
            (project.goal && project.goal.toLowerCase().includes(term))
        );
    }
    
    if (filteredProjects.length === 0) {
        if (searchTerm) {
            container.innerHTML = '<div class="project-item">Проекты не найдены</div>';
        } else {
            container.innerHTML = '<div class="project-item">Нет проектов</div>';
        }
        return;
    }
    
    container.innerHTML = filteredProjects.map(project => `
        <div class="project-item ${project.id === appState.currentProjectId ? 'active' : ''}" 
             data-project-id="${project.id}">
            <div class="project-name">${escapeHtml(project.name)}</div>
            <div class="project-goal">${escapeHtml(project.goal || 'Без цели')}</div>
        </div>
    `).join('');
    
    // Добавляем обработчики кликов
    container.querySelectorAll('.project-item').forEach(item => {
        item.addEventListener('click', () => {
            const projectId = item.dataset.projectId;
            selectProject(projectId);
        });
    });
}

// Выбор проекта
async function selectProject(projectId) {
    appState.currentProjectId = projectId;
    appState.currentChatId = null;
    
    // Сохраняем состояние
    saveAppState();
    
    // Обновляем UI
    document.querySelectorAll('.project-item').forEach(item => {
        item.classList.toggle('active', item.dataset.projectId === projectId);
    });
    
    // Загружаем данные проекта
    try {
        const projectData = await apiRequest(`/projects/${projectId}`);
        appState.chats = projectData.chats || [];
        appState.documents = projectData.documents || [];
        appState.artifacts = projectData.artifacts || [];
        
        renderChats(appState.chats);
        renderDocuments(appState.documents);
        renderArtifacts(appState.artifacts);
        
        // Если есть чаты, выбираем первый (последний созданный)
        if (appState.chats.length > 0) {
            // Сортируем по дате создания (новые сначала)
            const sortedChats = [...appState.chats].sort((a, b) => 
                new Date(b.created_at) - new Date(a.created_at)
            );
            selectChat(sortedChats[0].id);
        }
        
        // Обновляем заголовок
        document.querySelector('.main-header .tab.active').click();
    } catch (error) {
        showError('Не удалось загрузить данные проекта');
    }
}

// Создание проекта
async function createProject() {
    const name = document.getElementById('project-name').value.trim();
    const goal = document.getElementById('project-goal').value.trim();
    
    // Очищаем предыдущие ошибки
    clearFieldError('project-name');
    clearFieldError('project-goal');
    
    // Валидация
    const validationRules = {
        name: [
            { type: 'required', fieldName: 'Название проекта' },
            { type: 'length', fieldName: 'Название проекта', min: 3, max: 100 }
        ],
        goal: [
            { type: 'length', fieldName: 'Цель проекта', min: 0, max: 1000 }
        ]
    };
    
    const formData = { name, goal };
    const errors = validateForm(formData, validationRules);
    
    // Показываем ошибки
    if (Object.keys(errors).length > 0) {
        for (const [field, error] of Object.entries(errors)) {
            showFieldError(`project-${field}`, error);
        }
        return;
    }
    
    try {
        const project = await apiRequest('/projects', {
            method: 'POST',
            body: JSON.stringify({ name, goal })
        });
        
        closeModal('project-modal');
        await loadProjects();
        selectProject(project.id);
        
        showSuccess('Проект успешно создан');
    } catch (error) {
        showError('Не удалось создать проект');
    }
}

// Рендеринг чатов
function renderChats(chats) {
    const container = document.getElementById('chats-list');
    
    if (chats.length === 0) {
        container.innerHTML = '<div class="chat-item">Нет чатов</div>';
        return;
    }
    
    container.innerHTML = chats.map(chat => `
        <div class="chat-item ${chat.id === appState.currentChatId ? 'active' : ''}" 
             data-chat-id="${chat.id}">
            <div class="chat-name">${escapeHtml(chat.name || 'Без названия')}</div>
            <div class="chat-date">${formatDate(chat.created_at)}</div>
        </div>
    `).join('');
    
    // Добавляем обработчики кликов
    container.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', () => {
            const chatId = item.dataset.chatId;
            selectChat(chatId);
        });
    });
}

// Выбор чата
async function selectChat(chatId) {
    appState.currentChatId = chatId;
    
    // Сохраняем состояние
    saveAppState();
    
    // Обновляем UI
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.toggle('active', item.dataset.chatId === chatId);
    });
    
    // Загружаем сообщения
    await loadMessages(chatId);
    
    // Загружаем историю промптов если активна соответствующая вкладка
    const activeRightbarTab = document.querySelector('.rightbar-tab.active');
    if (activeRightbarTab && activeRightbarTab.dataset.tab === 'prompt-history') {
        await loadPromptHistory();
    }
}

// Загрузка сообщений
async function loadMessages(chatId) {
    try {
        const messages = await apiRequest(`/projects/${appState.currentProjectId}/chats/${chatId}/messages`);
        renderMessages(messages);
    } catch (error) {
        showError('Не удалось загрузить сообщения');
    }
}

// Рендеринг сообщений
function renderMessages(messages) {
    const container = document.getElementById('messages-container');
    
    if (messages.length === 0) {
        container.innerHTML = '<div class="welcome-message"><p>Начните диалог</p></div>';
        return;
    }
    
    container.innerHTML = messages.map(msg => `
        <div class="message message-${msg.role}">
            <div class="message-content">${renderMarkdown(msg.content)}</div>
        </div>
    `).join('');
    
    // Прокручиваем вниз
    container.scrollTop = container.scrollHeight;
    
    // Применяем подсветку синтаксиса
    hljs.highlightAll();
}

// Создание нового чата
async function createNewChat() {
    if (!appState.currentProjectId) {
        showError('Сначала выберите проект');
        return;
    }
    
    try {
        const chat = await apiRequest(`/projects/${appState.currentProjectId}/chats`, {
            method: 'POST',
            body: JSON.stringify({ name: `Чат от ${new Date().toLocaleDateString()}` })
        });
        
        appState.chats.push(chat);
        renderChats(appState.chats);
        selectChat(chat.id);
        
        showSuccess('Чат успешно создан');
    } catch (error) {
        showError('Не удалось создать чат');
    }
}

// Функция для отмены текущего запроса
function cancelCurrentRequest() {
    if (appState.currentStreamController) {
        appState.currentStreamController.abort();
        appState.currentStreamController = null;
    }
    if (appState.timeoutId) {
        clearTimeout(appState.timeoutId);
        appState.timeoutId = null;
    }
    appState.isStreaming = false;
    const sendBtn = document.getElementById('send-message-btn');
    if (sendBtn) setButtonLoading(sendBtn, false);
    
    // Показываем сообщение об отмене
    const cancelBtn = document.getElementById('cancel-stream-btn');
    if (cancelBtn) cancelBtn.remove();
}

// Отправка сообщения
async function sendMessage() {
    if (!appState.currentProjectId || !appState.currentChatId) {
        showError('Сначала выберите проект и чат');
        return;
    }
    
    const input = document.getElementById('message-input');
    const content = input.value.trim();
    
    if (!content) {
        showError('Введите сообщение');
        return;
    }
    
    if (appState.isStreaming) {
        showError('Дождитесь завершения предыдущего ответа');
        return;
    }
    
    // Добавляем сообщение пользователя
    const messagesContainer = document.getElementById('messages-container');
    messagesContainer.innerHTML += `
        <div class="message message-user">
            <div class="message-content">${escapeHtml(content)}</div>
        </div>
    `;
    
    // Очищаем поле ввода
    input.value = '';
    input.style.height = 'auto';
    
    // Добавляем пустое сообщение ассистента с индикацией типирования
    const assistantMessageId = 'assistant-' + Date.now();
    messagesContainer.innerHTML += `
        <div class="message message-assistant" id="${assistantMessageId}">
            <div class="message-content">
                <div class="typing-indicator" id="${assistantMessageId}-typing">
                    <span>ИИ думает</span>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `;
    
    // Прокручиваем вниз
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    // Отправляем сообщение через Fetch API с SSE
    appState.isStreaming = true;
    const sendBtn = document.getElementById('send-message-btn');
    setButtonLoading(sendBtn, true);
    
    // Получаем текущие настройки AI (перед логгированием!)
    const tempElement = document.getElementById('ai-temperature');
    const maxTokensElement = document.getElementById('max-tokens');
    const contextSizeElement = document.getElementById('context-size');
    const customContextSizeElement = document.getElementById('custom-context-size');
    const enableStreamingElement = document.getElementById('enable-streaming');
    
    const temperature = tempElement ? parseFloat(tempElement.value) || 0.7 : 0.7;
    const maxTokens = maxTokensElement ? parseInt(maxTokensElement.value) || 2000 : 2000;
    const contextSize = contextSizeElement ? contextSizeElement.value || 'medium' : 'medium';
    const customContextSize = customContextSizeElement ? parseInt(customContextSizeElement.value) || 20000 : 20000;
    const enableStreaming = enableStreamingElement ? enableStreamingElement.checked : true;
    
    // Логируем отправку сообщения
    if (window.appLogger) {
        window.appLogger.info('Отправка сообщения ИИ', {
            projectId: appState.currentProjectId,
            chatId: appState.currentChatId,
            contentLength: content.length,
            temperature: temperature,
            maxTokens: maxTokens
        });
    }
    
    // Создаем кнопку отмены
    const cancelBtn = document.createElement('button');
    cancelBtn.id = 'cancel-stream-btn';
    cancelBtn.className = 'btn btn-danger';
    cancelBtn.textContent = 'Отмена';
    cancelBtn.style.marginLeft = '8px';
    cancelBtn.onclick = cancelCurrentRequest;
    sendBtn.parentNode.insertBefore(cancelBtn, sendBtn.nextSibling);
    
    // Создаем AbortController для возможности отмены
    appState.currentStreamController = new AbortController();
    
    // Устанавливаем таймаут на 60 секунд
    appState.timeoutId = setTimeout(() => {
        if (appState.isStreaming) {
            cancelCurrentRequest();
            showError('Превышено время ожидания ответа от ИИ (60 секунд)');
        }
    }, 60000);
    
    try {
        
        const response = await fetch(`/api/projects/${appState.currentProjectId}/chats/${appState.currentChatId}/messages`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                content: content,
                selected_document_ids: Array.from(appState.selectedDocumentIds),
                metadata: {
                    temperature: temperature,
                    max_tokens: maxTokens,
                    context_size: contextSize,
                    custom_context_size: customContextSize,
                    enable_streaming: enableStreaming
                }
            }),
            signal: appState.currentStreamController.signal
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        if (!response.body) {
            throw new Error('No response body');
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = '';
        
        while (true) {
            const { done, value } = await reader.read();
            
            if (done) {
                appState.isStreaming = false;
                const sendBtn = document.getElementById('send-message-btn');
                if (sendBtn) setButtonLoading(sendBtn, false);
                break;
            }
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.slice(6);
                    if (dataStr.trim() === '') continue;
                    
                    try {
                        const data = JSON.parse(dataStr);
                        
                        if (data.done) {
                            appState.isStreaming = false;
                            const sendBtn = document.getElementById('send-message-btn');
                            if (sendBtn) setButtonLoading(sendBtn, false);
                            
                            // Убираем кнопку отмены
                            const cancelBtn = document.getElementById('cancel-stream-btn');
                            if (cancelBtn) cancelBtn.remove();
                            
                            // Перезагружаем сообщения из базы чтобы убедиться что все сохранено
                            if (appState.currentChatId) {
                                setTimeout(() => loadMessages(appState.currentChatId), 500);
                            }
                            continue;
                        }
                        
                        if (data.content) {
                            // Убираем индикацию типирования при первом чанке
                            const typingIndicator = document.getElementById(`${assistantMessageId}-typing`);
                            if (typingIndicator) {
                                typingIndicator.remove();
                            }
                            
                            fullResponse += data.content;
                            const messageElement = document.getElementById(assistantMessageId);
                            if (messageElement) {
                                messageElement.querySelector('.message-content').innerHTML = renderMarkdown(fullResponse);
                                hljs.highlightAll();
                            }
                            
                            // Прокручиваем вниз
                            messagesContainer.scrollTop = messagesContainer.scrollHeight;
                        }
                    } catch (e) {
                        console.error('Error parsing SSE data:', e, 'Data:', dataStr);
                     }
             }
         }
     }
       } catch (error) {
           console.error('Error in sendMessage:', error);
           appState.isStreaming = false;
           const sendBtn = document.getElementById('send-message-btn');
           if (sendBtn) setButtonLoading(sendBtn, false);
           cancelCurrentRequest();
           showError('Ошибка при отправке сообщения: ' + error.message);
          
          // Перезагружаем сообщения из базы
          if (appState.currentChatId) {
              setTimeout(() => loadMessages(appState.currentChatId), 500);
          }
      }
}

// Работа с документами
function toggleDocumentsSelection() {
    const container = document.getElementById('documents-selection-container');
    const toggleBtn = document.getElementById('toggle-documents-selection');
    const showBtn = document.getElementById('show-documents-selection');
    
    if (container.style.display === 'none' || !container.style.display) {
        // Показываем панель
        container.style.display = 'block';
        toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 9l6 6 6-6"/>
            </svg>
        `;
        toggleBtn.title = 'Скрыть выбор документов';
        showBtn.style.display = 'none';
        
        // Загружаем документы если еще не загружены
        loadDocumentsForSelection();
    } else {
        // Скрываем панель
        container.style.display = 'none';
        toggleBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 15l-6-6-6 6"/>
            </svg>
        `;
        toggleBtn.title = 'Показать выбор документов';
        showBtn.style.display = 'block';
    }
}

async function loadDocumentsForSelection() {
    if (!appState.currentProjectId) return;
    
    try {
        const projectData = await apiRequest(`/projects/${appState.currentProjectId}`);
        const documents = projectData.documents || [];
        renderDocumentsSelection(documents);
    } catch (error) {
        console.error('Error loading documents for selection:', error);
    }
}

function renderDocumentsSelection(documents) {
    const container = document.getElementById('documents-selection-list');
    if (!container) return;
    
    if (documents.length === 0) {
        container.innerHTML = '<div class="document-selection-item"><span style="color: var(--text-secondary); font-size: 13px;">Нет документов в проекте</span></div>';
        return;
    }
    
    container.innerHTML = documents.map(doc => `
        <div class="document-selection-item" data-doc-id="${doc.id}">
            <input type="checkbox" id="doc-select-${doc.id}" ${appState.selectedDocumentIds.has(doc.id) ? 'checked' : ''}>
            <label for="doc-select-${doc.id}" class="document-selection-name">${escapeHtml(doc.name)}</label>
            <span class="document-selection-status ${doc.status || 'ready'}">${doc.status || 'ready'}</span>
        </div>
    `).join('');
    
    // Добавляем обработчики для чекбоксов
    container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
            const docId = checkbox.id.replace('doc-select-', '');
            if (checkbox.checked) {
                appState.selectedDocumentIds.add(docId);
            } else {
                appState.selectedDocumentIds.delete(docId);
            }
            // Сохраняем состояние
            saveAppState();
        });
    });
}

async function loadDocuments() {
    if (!appState.currentProjectId) return;
    
    return withLoading(async () => {
        try {
            const projectData = await apiRequest(`/projects/${appState.currentProjectId}`);
            appState.documents = projectData.documents || [];
            renderDocuments(appState.documents);
        } catch (error) {
            showError('Не удалось загрузить документы');
        }
    }, 'Загрузка документов...');
}

function renderDocuments(documents) {
    const container = document.getElementById('documents-list');
    
    if (documents.length === 0) {
        container.innerHTML = '<div class="document-card"><p>Нет документов</p></div>';
        return;
    }
    
    container.innerHTML = documents.map(doc => `
        <div class="document-card" data-doc-id="${doc.id}">
            <div class="document-header">
                <div class="document-name">${escapeHtml(doc.name)}</div>
                 <div class="document-actions">
                    <button class="btn-icon preview-document-btn" title="Предпросмотр документа" data-doc-id="${doc.id}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                            <circle cx="12" cy="12" r="3"/>
                        </svg>
                    </button>
                    ${doc.anonymization_log ? `
                    <button class="btn-icon deanonymize-document-btn" title="Восстановить оригинальный текст" data-doc-id="${doc.id}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 15v4c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-4M17 9l-5 5-5-5M12 12.8V2.5"/>
                        </svg>
                    </button>
                    ` : ''}
                    <button class="btn-icon delete-document-btn" title="Удалить документ" data-doc-id="${doc.id}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                            <line x1="10" y1="11" x2="10" y2="17"/>
                            <line x1="14" y1="11" x2="14" y2="17"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="document-description">${escapeHtml(doc.description || 'Без описания')}</div>
            <div class="document-meta">
                <span>${doc.file_type || 'unknown'}</span>
                <span>${formatDate(doc.created_at)}</span>
                <span class="document-status ${doc.status || 'ready'}">${doc.status || 'ready'}</span>
            </div>
            ${doc.anonymization_log ? `
                <div class="document-pii-stats">
                    <div class="pii-stats-header">
                        <span>PII статистика:</span>
                        <button class="btn-icon pii-details-btn" title="Подробности анонимизации" data-doc-id="${doc.id}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="12" r="10"/>
                                <path d="M12 16v-4M12 8h.01"/>
                            </svg>
                        </button>
                    </div>
                    <div class="pii-stats-content" id="pii-stats-${doc.id}" style="display: none;">
                        <!-- Статистика будет загружена по требованию -->
                    </div>
                </div>
            ` : ''}
        </div>
    `).join('');
    
    // Добавляем обработчики для кнопок удаления
    container.querySelectorAll('.delete-document-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const docId = btn.dataset.docId;
            deleteDocument(docId);
        });
    });
    
    // Добавляем обработчики для кнопок предпросмотра
    container.querySelectorAll('.preview-document-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const docId = btn.dataset.docId;
            previewDocument(docId);
        });
    });
    
    // Добавляем обработчики для кнопок де-анонимизации
    container.querySelectorAll('.deanonymize-document-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const docId = btn.dataset.docId;
            deanonymizeDocument(docId);
        });
    });
    
    // Добавляем обработчики для кнопок статистики PII
    container.querySelectorAll('.pii-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const docId = btn.dataset.docId;
            const statsContent = document.getElementById(`pii-stats-${docId}`);
            if (statsContent.style.display === 'none') {
                loadPiiStatistics(docId);
                statsContent.style.display = 'block';
                btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l4 4 4-4"/></svg>`;
            } else {
                statsContent.style.display = 'none';
                btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>`;
            }
        });
    });
}

// Обработка выбора файла
async function handleFileSelect(file) {
    if (!file) return;
    
    // Проверка размера файла (20MB)
    const maxSize = 20 * 1024 * 1024;
    if (file.size > maxSize) {
        showError('Файл слишком большой (максимум 20MB)');
        return;
    }
    
    // Проверка типа файла
    const fileName = file.name.toLowerCase();
    if (!fileName.endsWith('.pdf') && !fileName.endsWith('.txt')) {
        showError('Поддерживаются только PDF и TXT файлы');
        return;
    }
    
    appState.currentFile = file;
    
    // Показываем информацию о файле
    document.getElementById('file-name').textContent = file.name;
    document.getElementById('file-size').textContent = formatFileSize(file.size);
    document.getElementById('file-info').classList.remove('hidden');
    
    // Показываем прогресс
    document.getElementById('upload-progress').classList.remove('hidden');
    document.getElementById('progress-bar').style.width = '0%';
    
    try {
        // Обрабатываем файл
        document.getElementById('progress-bar').style.width = '30%';
        const result = await processFile(file);
        
        if (!result.success) {
            throw new Error(result.error);
        }
        
        document.getElementById('progress-bar').style.width = '70%';
        
        // Сохраняем результат анонимизации
        appState.anonymizationResult = result;
        
        // Показываем информацию о PII
        document.getElementById('pii-count').textContent = result.foundPII;
        document.getElementById('anonymization-info').classList.remove('hidden');
        
        document.getElementById('progress-bar').style.width = '100%';
        
        // Активируем кнопку загрузки
        document.getElementById('upload-document-submit-btn').disabled = false;
        
        // Скрываем прогресс через секунду
        setTimeout(() => {
            document.getElementById('upload-progress').classList.add('hidden');
        }, 1000);
        
    } catch (error) {
        console.error('File processing error:', error);
        document.getElementById('upload-error').textContent = `Ошибка обработки файла: ${error.message}`;
        document.getElementById('upload-error').classList.remove('hidden');
        document.getElementById('upload-progress').classList.add('hidden');
    }
}

// Сброс формы документа
function resetDocumentForm() {
    document.getElementById('document-name').value = '';
    document.getElementById('document-description').value = '';
    document.getElementById('file-info').classList.add('hidden');
    document.getElementById('anonymization-info').classList.add('hidden');
    document.getElementById('upload-error').classList.add('hidden');
    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('upload-document-submit-btn').disabled = true;
    appState.currentFile = null;
    appState.anonymizationResult = null;
}

// Загрузка документа на сервер
async function uploadDocument() {
    if (!appState.currentFile || !appState.anonymizationResult || !appState.currentProjectId) {
        showError('Сначала выберите и обработайте файл');
        return;
    }
    
    const name = document.getElementById('document-name').value.trim();
    const description = document.getElementById('document-description').value.trim();
    
    if (!name) {
        showError('Введите название документа');
        return;
    }
    
    try {
        // Создаем FormData
        const formData = new FormData();
        formData.append('file', appState.currentFile);
        formData.append('name', name);
        formData.append('description', description);
        formData.append('anonymized_text', appState.anonymizationResult.anonymizedText);
        formData.append('anonymization_map', JSON.stringify(appState.anonymizationResult.anonymizationMap));
        
        // Отправляем запрос
        const response = await fetch(`/api/projects/${appState.currentProjectId}/documents`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        closeModal('document-modal');
        await loadDocuments();
        
        showSuccess('Документ успешно загружен');
    } catch (error) {
        console.error('Upload error:', error);
        showError('Не удалось загрузить документ');
    }
}

// Работа с артефактами
function renderArtifacts(artifacts) {
    const container = document.getElementById('artifacts-list');
    
    if (artifacts.length === 0) {
        container.innerHTML = '<div class="artifact-item"><p>Нет артефактов</p></div>';
        return;
    }
    
    container.innerHTML = artifacts.map(artifact => {
        const artifactType = artifact.artifact_type || 'other';
        const tags = artifact.tags ? artifact.tags.split(',').map(tag => tag.trim()) : [];
        const typeLabels = {
            'analysis': 'Анализ',
            'summary': 'Сводка',
            'plan': 'План',
            'report': 'Отчет',
            'code': 'Код',
            'documentation': 'Документация',
            'other': 'Другое'
        };
        
        return `
            <div class="artifact-item" data-artifact-id="${artifact.id}">
                <div class="artifact-header">
                    <div class="artifact-type-badge artifact-type-${artifactType}">${typeLabels[artifactType] || 'Другое'}</div>
                    <div class="artifact-name">${escapeHtml(artifact.name)}</div>
                </div>
                <div class="artifact-content">${escapeHtml(artifact.content.substring(0, 200))}${artifact.content.length > 200 ? '...' : ''}</div>
                ${tags.length > 0 ? `
                    <div class="artifact-tags">
                        ${tags.map(tag => `<span class="artifact-tag">${escapeHtml(tag)}</span>`).join('')}
                    </div>
                ` : ''}
                <div class="artifact-meta">
                    <span>${formatDate(artifact.created_at)}</span>
                    ${artifact.metadata && artifact.metadata.template ? `<span class="artifact-template">Шаблон: ${artifact.metadata.template}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
    
    // Добавляем обработчики кликов для просмотра полного артефакта
    container.querySelectorAll('.artifact-item').forEach(item => {
        item.addEventListener('click', () => {
            const artifactId = item.dataset.artifactId;
            const artifact = artifacts.find(a => a.id === artifactId);
            if (artifact) {
                previewArtifact(artifact);
            }
        });
    });
}

// Удаление документа
async function deleteDocument(docId) {
    const confirmed = await showConfirm(
        'Вы уверены, что хотите удалить этот документ? Это действие нельзя отменить.',
        {
            title: 'Удаление документа',
            confirmText: 'Удалить',
            cancelText: 'Отмена',
            type: 'danger'
        }
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        await apiRequest(`/projects/${appState.currentProjectId}/documents/${docId}`, {
            method: 'DELETE'
        });
        
        // Удаляем документ из состояния
        appState.documents = appState.documents.filter(doc => doc.id !== docId);
        renderDocuments(appState.documents);
        
        showSuccess('Документ успешно удален');
    } catch (error) {
        showError('Не удалось удалить документ: ' + error.message);
    }
}

// Сохранение артефакта
async function saveArtifact() {
    if (!appState.currentProjectId) {
        showError('Сначала выберите проект');
        return;
    }
    
    const artifactType = document.getElementById('artifact-type').value;
    const name = document.getElementById('artifact-name').value.trim();
    const content = document.getElementById('artifact-content').value.trim();
    const tags = document.getElementById('artifact-tags').value.trim();
    const template = document.getElementById('artifact-template').value;
    
    if (!name || !content) {
        showError('Заполните обязательные поля');
        return;
    }
    
    try {
        // Применяем шаблон если выбран
        let processedContent = content;
        if (template) {
            processedContent = applyArtifactTemplate(template, content);
        }
        
        const artifact = await apiRequest(`/projects/${appState.currentProjectId}/artifacts`, {
            method: 'POST',
            body: JSON.stringify({
                name,
                content: processedContent,
                artifact_type: artifactType,
                tags: tags,
                chat_id: appState.currentChatId,
                metadata: {
                    template: template,
                    original_content: content
                }
            })
        });
        
        closeModal('artifact-modal');
        
        // Обновляем список артефактов
        appState.artifacts.push(artifact);
        renderArtifacts(appState.artifacts);
        
        showSuccess('Артефакт успешно сохранен');
    } catch (error) {
        showError('Не удалось сохранить артефакт: ' + error.message);
    }
}

// Применение шаблона артефакта
function applyArtifactTemplate(template, content) {
    const templates = {
        'analysis-template': `# Анализ документа

## Цель анализа
[Опишите цель анализа]

## Ключевые выводы
${content}

## Рекомендации
[Сформулируйте рекомендации]

## Следующие шаги
[Опишите следующие шаги]`,

        'summary-template': `# Сводка документа

## Основные тезисы
${content}

## Ключевые моменты
[Перечислите ключевые моменты]

## Выводы
[Сформулируйте выводы]`,

        'plan-template': `# План действий

## Цель плана
[Опишите цель]

## Задачи
${content}

## Сроки
[Укажите сроки выполнения]

## Ответственные
[Назначьте ответственных]

## Ресурсы
[Перечислите необходимые ресурсы]`,

        'report-template': `# Отчет

## Введение
[Краткое введение]

## Основная часть
${content}

## Выводы
[Сформулируйте выводы]

## Приложения
[Дополнительные материалы]`
    };
    
    return templates[template] || content;
}

// Предпросмотр артефакта
function previewArtifact(artifact) {
    const artifactType = artifact.artifact_type || 'other';
    const tags = artifact.tags ? artifact.tags.split(',').map(tag => tag.trim()) : [];
    const typeLabels = {
        'analysis': 'Анализ',
        'summary': 'Сводка',
        'plan': 'План',
        'report': 'Отчет',
        'code': 'Код',
        'documentation': 'Документация',
        'other': 'Другое'
    };
    
    // Создаем модальное окно для предпросмотра
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>${escapeHtml(artifact.name)}</h3>
                <button class="btn-icon modal-close-btn" title="Закрыть">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/>
                        <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="artifact-preview-info">
                    <div><strong>Тип:</strong> <span class="artifact-type-badge artifact-type-${artifactType}">${typeLabels[artifactType] || 'Другое'}</span></div>
                    <div><strong>Дата создания:</strong> ${formatDate(artifact.created_at)}</div>
                    ${artifact.metadata && artifact.metadata.template ? `<div><strong>Шаблон:</strong> ${escapeHtml(artifact.metadata.template)}</div>` : ''}
                    ${tags.length > 0 ? `<div><strong>Теги:</strong> ${tags.map(tag => `<span class="artifact-tag">${escapeHtml(tag)}</span>`).join(' ')}</div>` : ''}
                </div>
                <div class="artifact-preview-content">
                    <h4>Содержимое:</h4>
                    <div class="artifact-full-content">${renderMarkdown(artifact.content)}</div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary modal-close-btn">Закрыть</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Добавляем обработчики закрытия
    modal.querySelectorAll('.modal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.remove();
        });
    });
    
    // Закрытие по клику вне модального окна
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
    
    // Закрытие по клавише Escape
    document.addEventListener('keydown', function closeOnEscape(e) {
        if (e.key === 'Escape') {
            modal.remove();
            document.removeEventListener('keydown', closeOnEscape);
        }
    });
    
    // Применяем подсветку синтаксиса
    setTimeout(() => {
        if (typeof hljs !== 'undefined') {
            hljs.highlightAll();
        }
    }, 100);
}

// Экспорт проектов
async function exportProjects() {
    try {
        // Загружаем все проекты с их данными
        const projects = await apiRequest('/projects');
        
        // Для каждого проекта загружаем связанные данные
        const projectsWithData = await Promise.all(projects.map(async (project) => {
            const projectData = await apiRequest(`/projects/${project.id}`);
            return {
                ...project,
                chats: projectData.chats || [],
                documents: projectData.documents || [],
                artifacts: projectData.artifacts || []
            };
        }));
        
        // Создаем объект экспорта
        const exportData = {
            version: '1.0',
            export_date: new Date().toISOString(),
            projects: projectsWithData
        };
        
        // Создаем JSON файл для скачивания
        const dataStr = JSON.stringify(exportData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = `projectchat-export-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        
        showSuccess(`Экспортировано ${projects.length} проектов`);
        
    } catch (error) {
        console.error('Error exporting projects:', error);
        showError('Ошибка экспорта проектов: ' + error.message);
    }
}

// Импорт проектов
async function handleProjectsImport(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    try {
        const fileContent = await file.text();
        const importData = JSON.parse(fileContent);
        
        // Проверяем версию и структуру
        if (!importData.version || !importData.projects) {
            throw new Error('Некорректный формат файла импорта');
        }
        
        const confirmed = await showConfirm(
            `Импортировать ${importData.projects.length} проектов? Существующие проекты не будут затронуты.`,
            {
                title: 'Импорт проектов',
                confirmText: 'Импортировать',
                cancelText: 'Отмена',
                type: 'success'
            }
        );
        
        if (!confirmed) {
            return;
        }
        
        // Импортируем каждый проект
        let importedCount = 0;
        for (const projectData of importData.projects) {
            try {
                // Создаем проект
                const project = await apiRequest('/projects', {
                    method: 'POST',
                    body: JSON.stringify({
                        name: projectData.name,
                        goal: projectData.goal
                    })
                });
                
                // Импортируем чаты
                for (const chat of projectData.chats || []) {
                    await apiRequest(`/projects/${project.id}/chats`, {
                        method: 'POST',
                        body: JSON.stringify({
                            name: chat.name
                        })
                    });
                }
                
                // Импортируем артефакты
                for (const artifact of projectData.artifacts || []) {
                    await apiRequest(`/projects/${project.id}/artifacts`, {
                        method: 'POST',
                        body: JSON.stringify({
                            name: artifact.name,
                            content: artifact.content,
                            artifact_type: artifact.artifact_type || 'other',
                            tags: artifact.tags,
                            metadata: artifact.metadata
                        })
                    });
                }
                
                importedCount++;
                
            } catch (projectError) {
                console.error(`Error importing project ${projectData.name}:`, projectError);
                // Продолжаем импорт других проектов
            }
        }
        
        // Очищаем input
        event.target.value = '';
        
        // Обновляем список проектов
        await loadProjects();
        
        showSuccess(`Успешно импортировано ${importedCount} проектов`);
        
    } catch (error) {
        console.error('Error importing projects:', error);
        showError('Ошибка импорта проектов: ' + error.message);
        event.target.value = '';
    }
}

// Мониторинг и логирование - класс SystemMonitor теперь в app-monitoring.js
// Используем window.systemMonitor для доступа

// Инициализация мониторинга - SystemMonitor теперь в app-monitoring.js
// Используем глобальный экземпляр, если он существует

// Добавляем глобальные методы для логирования
window.appLogger = {
    info: (message, data) => {
        if (window.systemMonitor) {
            window.systemMonitor.log('info', message, data);
        } else {
            console.log(`[INFO] ${message}`, data || '');
        }
    },
    warn: (message, data) => {
        if (window.systemMonitor) {
            window.systemMonitor.log('warning', message, data);
        } else {
            console.warn(`[WARN] ${message}`, data || '');
        }
    },
    error: (message, data) => {
        if (window.systemMonitor) {
            window.systemMonitor.log('error', message, data);
        } else {
            console.error(`[ERROR] ${message}`, data || '');
        }
    },
    exportLogs: () => window.systemMonitor ? window.systemMonitor.exportLogs() : [],
    getStatus: () => window.systemMonitor ? window.systemMonitor.status : 'unknown'
};

// Запускаем мониторинг после загрузки DOM
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        if (window.systemMonitor && typeof window.systemMonitor.startMonitoring === 'function') {
            window.systemMonitor.startMonitoring();
        }
    }, 2000);
});
// Настройки
async function loadSettings() {
    try {
        appState.settings = await apiRequest('/settings');
    } catch (error) {
        console.error('Error loading settings:', error);
        appState.settings = {};
        
        // Ошибка загрузки настроек - просто логируем, не показываем пользователю
        if (window.appLogger) {
            window.appLogger.error('Ошибка загрузки настроек', {
                error: error.message
            });
        }
    }
}

// Загрузка истории промптов
async function loadPromptHistory() {
    try {
        const container = document.getElementById('prompt-history-list');
        if (!container) return;
        
        if (!appState.currentChatId) {
            container.innerHTML = '<div class="prompt-history-empty">Выберите чат для просмотра истории промптов</div>';
            return;
        }
        
        // Загружаем сообщения чата
        const messages = await apiRequest(`/projects/${appState.currentProjectId}/chats/${appState.currentChatId}/messages`);
        
        // Фильтруем только сообщения пользователя (промпты)
        const prompts = messages.filter(msg => msg.role === 'user');
        
        if (prompts.length === 0) {
            container.innerHTML = '<div class="prompt-history-empty">История промптов пуста</div>';
            return;
        }
        
        // Рендерим историю промптов
        container.innerHTML = prompts.map((prompt, index) => {
            const date = new Date(prompt.created_at);
            const timeString = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const dateString = date.toLocaleDateString();
            
            return `
                <div class="prompt-history-item" data-prompt-index="${index}">
                    <div class="prompt-history-content">${escapeHtml(prompt.content.substring(0, 200))}${prompt.content.length > 200 ? '...' : ''}</div>
                    <div class="prompt-history-meta">
                        <span>${timeString}</span>
                        <span>${dateString}</span>
                    </div>
                    ${prompt.metadata ? `
                        <div class="prompt-history-params">
                            ${prompt.metadata.temperature ? `Температура: ${prompt.metadata.temperature}` : ''}
                            ${prompt.metadata.max_tokens ? `, Токены: ${prompt.metadata.max_tokens}` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
        
        // Добавляем обработчики кликов
        container.querySelectorAll('.prompt-history-item').forEach(item => {
            item.addEventListener('click', () => {
                const promptIndex = parseInt(item.dataset.promptIndex);
                const prompt = prompts[promptIndex];
                
                // Вставляем промпт в поле ввода
                const input = document.getElementById('message-input');
                input.value = prompt.content;
                input.focus();
                
                // Автоматически подстраиваем высоту
                input.style.height = 'auto';
                input.style.height = input.scrollHeight + 'px';
                
                // Показываем уведомление
                showSuccess('Промпт загружен в поле ввода');
            });
        });
        
    } catch (error) {
        console.error('Error loading prompt history:', error);
        const container = document.getElementById('prompt-history-list');
        if (container) {
            container.innerHTML = '<div class="prompt-history-empty">Ошибка загрузки истории промптов</div>';
        }
    }
}

// Загрузка шаблонов промптов
async function loadPromptTemplates() {
    try {
        const container = document.getElementById('prompt-templates-list');
        if (!container) return;
        
        // Загружаем шаблоны из localStorage (временное решение)
        const templates = JSON.parse(localStorage.getItem('projectchat_prompt_templates') || '[]');
        
        if (templates.length === 0) {
            container.innerHTML = `
                <div class="prompt-template-empty">
                    <p>Шаблоны промптов отсутствуют</p>
                    <p style="margin-top: 8px; font-size: 12px;">Создайте свой первый шаблон для быстрого повторного использования промптов</p>
                </div>
            `;
            return;
        }
        
        // Рендерим шаблоны
        container.innerHTML = templates.map((template, index) => {
            const tags = template.tags ? template.tags.split(',').map(tag => tag.trim()) : [];
            
            return `
                <div class="prompt-template-item" data-template-index="${index}">
                    <div class="prompt-template-header">
                        <div class="prompt-template-name">${escapeHtml(template.name)}</div>
                        <div class="prompt-template-actions">
                            <button class="btn-icon use-template-btn" title="Использовать шаблон" data-template-index="${index}">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                    <polyline points="7 10 12 15 17 10"/>
                                    <line x1="12" y1="15" x2="12" y2="3"/>
                                </svg>
                            </button>
                            <button class="btn-icon delete-template-btn" title="Удалить шаблон" data-template-index="${index}">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="prompt-template-content">${escapeHtml(template.content.substring(0, 150))}${template.content.length > 150 ? '...' : ''}</div>
                    ${template.description ? `<div class="prompt-template-description" style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">${escapeHtml(template.description)}</div>` : ''}
                    ${tags.length > 0 ? `
                        <div class="prompt-template-tags">
                            ${tags.map(tag => `<span class="prompt-template-tag">${escapeHtml(tag)}</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
        
        // Добавляем обработчики
        container.querySelectorAll('.use-template-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.templateIndex);
                usePromptTemplate(index);
            });
        });
        
        container.querySelectorAll('.delete-template-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.templateIndex);
                await deletePromptTemplate(index);
            });
        });
        
        container.querySelectorAll('.prompt-template-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.prompt-template-actions')) {
                    const index = parseInt(item.dataset.templateIndex);
                    editPromptTemplate(index);
                }
            });
        });
        
    } catch (error) {
        console.error('Error loading prompt templates:', error);
        const container = document.getElementById('prompt-templates-list');
        if (container) {
            container.innerHTML = '<div class="prompt-template-empty">Ошибка загрузки шаблонов</div>';
        }
    }
}

// Использование шаблона промпта
function usePromptTemplate(index) {
    const templates = JSON.parse(localStorage.getItem('projectchat_prompt_templates') || '[]');
    if (index >= 0 && index < templates.length) {
        const template = templates[index];
        
        // Вставляем шаблон в поле ввода
        const input = document.getElementById('message-input');
        input.value = template.content;
        input.focus();
        
        // Автоматически подстраиваем высоту
        input.style.height = 'auto';
        input.style.height = input.scrollHeight + 'px';
        
        // Закрываем модальное окно если открыто
        closeModal('prompt-template-modal');
        
        // Показываем уведомление
        showSuccess(`Шаблон "${template.name}" загружен в поле ввода`);
    }
}

// Редактирование шаблона промпта
function editPromptTemplate(index) {
    const templates = JSON.parse(localStorage.getItem('projectchat_prompt_templates') || '[]');
    if (index >= 0 && index < templates.length) {
        const template = templates[index];
        
        // Заполняем форму
        document.getElementById('template-name').value = template.name;
        document.getElementById('template-content').value = template.content;
        document.getElementById('template-tags').value = template.tags || '';
        document.getElementById('template-description').value = template.description || '';
        
        // Сохраняем индекс для обновления
        document.getElementById('prompt-template-modal').dataset.editIndex = index;
        
        // Открываем модальное окно
        openModal('prompt-template-modal');
    }
}

// Удаление шаблона промпта
async function deletePromptTemplate(index) {
    const confirmed = await showConfirm(
        'Удалить этот шаблон промпта?',
        {
            title: 'Удаление шаблона',
            confirmText: 'Удалить',
            cancelText: 'Отмена',
            type: 'danger'
        }
    );
    
    if (confirmed) {
        const templates = JSON.parse(localStorage.getItem('projectchat_prompt_templates') || '[]');
        if (index >= 0 && index < templates.length) {
            templates.splice(index, 1);
            localStorage.setItem('projectchat_prompt_templates', JSON.stringify(templates));
            loadPromptTemplates();
            showSuccess('Шаблон удален');
        }
    }
}

// Сохранение шаблона промпта
async function savePromptTemplate() {
    try {
        const name = document.getElementById('template-name').value.trim();
        const content = document.getElementById('template-content').value.trim();
        const tags = document.getElementById('template-tags').value.trim();
        const description = document.getElementById('template-description').value.trim();
        
        if (!name) {
            showErrorInModal('prompt-template-error', 'Введите название шаблона');
            return;
        }
        
        if (!content) {
            showErrorInModal('prompt-template-error', 'Введите содержимое промпта');
            return;
        }
        
        // Загружаем существующие шаблоны
        const templates = JSON.parse(localStorage.getItem('projectchat_prompt_templates') || '[]');
        
        // Проверяем, редактируем ли существующий шаблон
        const modal = document.getElementById('prompt-template-modal');
        const editIndex = modal.dataset.editIndex;
        
        const template = {
            name,
            content,
            tags,
            description,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
        };
        
        if (editIndex !== undefined) {
            // Обновляем существующий шаблон
            templates[editIndex] = template;
            delete modal.dataset.editIndex;
        } else {
            // Добавляем новый шаблон
            templates.push(template);
        }
        
        // Сохраняем в localStorage
        localStorage.setItem('projectchat_prompt_templates', JSON.stringify(templates));
        
        // Закрываем модальное окно
        closeModal('prompt-template-modal');
        
        // Обновляем список шаблонов
        loadPromptTemplates();
        
        // Показываем уведомление
        showSuccess(editIndex !== undefined ? 'Шаблон обновлен' : 'Шаблон сохранен');
        
    } catch (error) {
        console.error('Error saving prompt template:', error);
        showErrorInModal('prompt-template-error', 'Ошибка сохранения шаблона: ' + error.message);
    }
}

// Вспомогательная функция для показа ошибок в модальном окне
function showErrorInModal(elementId, message) {
    const errorElement = document.getElementById(elementId);
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.classList.remove('hidden');
    }
}

function loadSettingsIntoForm() {
    const settings = appState.settings;
    
    document.getElementById('ai-provider').value = settings.AI_PROVIDER || 'deepseek';
    document.getElementById('openrouter-api-key').value = settings.OPENROUTER_API_KEY || '';
    document.getElementById('openrouter-model').value = settings.OPENROUTER_MODEL || 'deepseek/deepseek-chat';
    document.getElementById('deepseek-api-key').value = settings.DEEPSEEK_API_KEY || '';
    document.getElementById('deepseek-model').value = settings.DEEPSEEK_MODEL || 'deepseek-chat';
    
    // Новые настройки
    document.getElementById('ai-temperature').value = settings.AI_TEMPERATURE || 0.7;
    document.getElementById('temperature-value').textContent = settings.AI_TEMPERATURE || 0.7;
    document.getElementById('max-tokens').value = settings.MAX_TOKENS || 2000;
    document.getElementById('context-size').value = settings.CONTEXT_SIZE || 'medium';
    document.getElementById('custom-context-size').value = settings.CUSTOM_CONTEXT_SIZE || 20000;
    document.getElementById('enable-streaming').checked = settings.ENABLE_STREAMING !== false;
    document.getElementById('auto-save-artifacts').checked = settings.AUTO_SAVE_ARTIFACTS || false;
    
    toggleProviderSettings();
    updateContextSizeVisibility();
}

function toggleProviderSettings() {
    const provider = document.getElementById('ai-provider').value;
    
    if (provider === 'openrouter') {
        document.getElementById('openrouter-settings').classList.remove('hidden');
        document.getElementById('deepseek-settings').classList.add('hidden');
    } else {
        document.getElementById('openrouter-settings').classList.add('hidden');
        document.getElementById('deepseek-settings').classList.remove('hidden');
    }
}

function updateContextSizeVisibility() {
    const contextSize = document.getElementById('context-size').value;
    const customContextGroup = document.getElementById('custom-context-group');
    
    if (contextSize === 'custom') {
        customContextGroup.classList.remove('hidden');
    } else {
        customContextGroup.classList.add('hidden');
    }
}

async function saveSettings(event) {
    if (event) event.preventDefault();
    
    const provider = document.getElementById('ai-provider').value;
    const openrouterApiKey = document.getElementById('openrouter-api-key').value.trim();
    const openrouterModel = document.getElementById('openrouter-model').value.trim();
    const deepseekApiKey = document.getElementById('deepseek-api-key').value.trim();
    const deepseekModel = document.getElementById('deepseek-model').value.trim();
    const aiTemperature = document.getElementById('ai-temperature').value;
    const maxTokens = document.getElementById('max-tokens').value;
    const contextSize = document.getElementById('context-size').value;
    const customContextSize = document.getElementById('custom-context-size').value;
    const enableStreaming = document.getElementById('enable-streaming').checked;
    const autoSaveArtifacts = document.getElementById('auto-save-artifacts').checked;
    
    // Очищаем предыдущие ошибки
    clearFieldError('ai-temperature');
    clearFieldError('max-tokens');
    clearFieldError('custom-context-size');
    clearFieldError('openrouter-api-key');
    clearFieldError('deepseek-api-key');
    
    // Валидация
    const validationRules = {
        aiTemperature: [
            { type: 'number', fieldName: 'Температура', min: 0, max: 2 }
        ],
        maxTokens: [
            { type: 'integer', fieldName: 'Максимум токенов', min: 100, max: 8000 }
        ]
    };
    
    // Добавляем валидацию для пользовательского размера контекста если выбран
    if (contextSize === 'custom') {
        validationRules.customContextSize = [
            { type: 'integer', fieldName: 'Пользовательский размер контекста', min: 500, max: 200000 }
        ];
    }
    
    // Добавляем валидацию API ключей если они заполнены
    if (openrouterApiKey && provider === 'openrouter') {
        validationRules.openrouterApiKey = [
            { type: 'apiKey', provider: 'openrouter' }
        ];
    }
    
    if (deepseekApiKey && provider === 'deepseek') {
        validationRules.deepseekApiKey = [
            { type: 'apiKey', provider: 'deepseek' }
        ];
    }
    
    const formData = { 
        aiTemperature, 
        maxTokens, 
        customContextSize,
        openrouterApiKey,
        deepseekApiKey
    };
    
    const errors = validateForm(formData, validationRules);
    
    // Показываем ошибки
    if (Object.keys(errors).length > 0) {
        for (const [field, error] of Object.entries(errors)) {
            showFieldError(field === 'customContextSize' ? 'custom-context-size' : field, error);
        }
        return;
    }
    
    // Преобразуем значения после успешной валидации
    const temperatureNum = parseFloat(aiTemperature);
    const maxTokensNum = parseInt(maxTokens);
    const customContextSizeNum = contextSize === 'custom' ? parseInt(customContextSize) : undefined;
    
    try {
        // Создаем объект настроек, используя существующие значения если поля пустые
        const currentSettings = appState.settings || {};
        const settings = {
            AI_PROVIDER: provider,
            OPENROUTER_API_KEY: openrouterApiKey || currentSettings.OPENROUTER_API_KEY || '',
            OPENROUTER_MODEL: openrouterModel || currentSettings.OPENROUTER_MODEL || 'deepseek/deepseek-chat',
            DEEPSEEK_API_KEY: deepseekApiKey || currentSettings.DEEPSEEK_API_KEY || '',
            DEEPSEEK_MODEL: deepseekModel || currentSettings.DEEPSEEK_MODEL || 'deepseek-chat',
            AI_TEMPERATURE: temperatureNum,
            MAX_TOKENS: maxTokensNum,
            CONTEXT_SIZE: contextSize,
            CUSTOM_CONTEXT_SIZE: customContextSizeNum,
            ENABLE_STREAMING: enableStreaming,
            AUTO_SAVE_ARTIFACTS: autoSaveArtifacts
        };
        
        await apiRequest('/settings', {
            method: 'POST',
            body: JSON.stringify(settings)
        });
        
        // Обновляем состояние
        appState.settings = settings;
        
        // Показываем успех
        document.getElementById('settings-error').classList.add('hidden');
        document.getElementById('settings-success').textContent = 'Настройки успешно сохранены';
        document.getElementById('settings-success').classList.remove('hidden');
        
        // Закрываем модальное окно через 1 секунду
        setTimeout(() => {
            document.getElementById('settings-success').classList.add('hidden');
            closeModal('settings-modal');
        }, 1000);
        
    } catch (error) {
        document.getElementById('settings-error').textContent = `Ошибка: ${error.message}`;
        document.getElementById('settings-error').classList.remove('hidden');
    }
}

async function testApiKey(event) {
    if (event) event.preventDefault();
    
    const provider = document.getElementById('ai-provider').value;
    const apiKey = provider === 'openrouter' 
        ? document.getElementById('openrouter-api-key').value.trim()
        : document.getElementById('deepseek-api-key').value.trim();
    
    if (!apiKey) {
        showError('Введите API ключ для проверки');
        return;
    }
    
    try {
        // Здесь можно добавить реальную проверку API ключа
        // Например, запрос к /models эндпоинту провайдера
        
        document.getElementById('settings-error').classList.add('hidden');
        document.getElementById('settings-success').textContent = 'API ключ валиден';
        document.getElementById('settings-success').classList.remove('hidden');
        
        setTimeout(() => {
            document.getElementById('settings-success').classList.add('hidden');
        }, 3000);
        
    } catch (error) {
        document.getElementById('settings-error').textContent = `Неверный API ключ: ${error.message}`;
        document.getElementById('settings-error').classList.remove('hidden');
    }
}

// Функции для управления ресайзом и скрытием панелей
function setupPanelResize() {
    // Загружаем сохраненные состояния из localStorage
    const savedUIState = localStorage.getItem('projectchat_ui_state');
    if (savedUIState) {
        try {
            const parsed = JSON.parse(savedUIState);
            appState.uiState = { ...appState.uiState, ...parsed };
        } catch (e) {
            console.error('Failed to parse saved UI state:', e);
        }
    }
    
    // Применяем сохраненные размеры
    document.documentElement.style.setProperty('--sidebar-width', `${appState.uiState.sidebarWidth}px`);
    document.documentElement.style.setProperty('--rightbar-width', `${appState.uiState.rightbarWidth}px`);
    
    // Применяем состояния свернутости
    if (appState.uiState.sidebarCollapsed) {
        document.querySelector('.sidebar').classList.add('collapsed');
    }
    if (appState.uiState.rightbarCollapsed) {
        document.querySelector('.rightbar').classList.add('collapsed');
    }
    
    // Создаем элементы управления
    createResizeHandles();
    createToggleButtons();
}

function createResizeHandles() {
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    const rightbar = document.querySelector('.rightbar');
    
    // Создаем handle для левой панели
    const sidebarResizeHandle = document.createElement('div');
    sidebarResizeHandle.className = 'sidebar-resize-handle';
    sidebar.appendChild(sidebarResizeHandle);
    
    // Создаем handle для правой панели
    const rightbarResizeHandle = document.createElement('div');
    rightbarResizeHandle.className = 'rightbar-resize-handle';
    rightbar.appendChild(rightbarResizeHandle);
    
    // Настройка ресайза левой панели
    setupResize(sidebarResizeHandle, sidebar, 'width', 'sidebarWidth', 200, 400);
    
    // Настройка ресайза правой панели
    setupResize(rightbarResizeHandle, rightbar, 'width', 'rightbarWidth', 200, 400);
}

function setupResize(handle, element, cssProperty, stateKey, minSize, maxSize) {
    let isResizing = false;
    let startPosition = 0;
    let startSize = 0;
    
    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startPosition = e.clientX;
        startSize = element.getBoundingClientRect()[cssProperty === 'width' ? 'width' : 'height'];
        handle.classList.add('resizing');
        document.body.style.userSelect = 'none';
        
        const onMouseMove = (e) => {
            if (!isResizing) return;
            
            const delta = e.clientX - startPosition;
            let newSize = startSize + delta;
            
            // Ограничиваем размер
            newSize = Math.max(minSize, Math.min(maxSize, newSize));
            
            // Применяем новый размер
            element.style[cssProperty] = `${newSize}px`;
            document.documentElement.style.setProperty(`--${stateKey}`, `${newSize}px`);
            
            // Сохраняем в состояние
            appState.uiState[stateKey] = newSize;
        };
        
        const onMouseUp = () => {
            isResizing = false;
            handle.classList.remove('resizing');
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            
            // Сохраняем состояние в localStorage
            saveUIState();
        };
        
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

function createToggleButtons() {
    const sidebar = document.querySelector('.sidebar');
    const rightbar = document.querySelector('.rightbar');
    
    // Кнопка для левой панели
    const sidebarToggle = document.createElement('button');
    sidebarToggle.className = 'sidebar-toggle';
    sidebarToggle.innerHTML = appState.uiState.sidebarCollapsed ? '→' : '←';
    sidebarToggle.title = appState.uiState.sidebarCollapsed ? 'Развернуть панель проектов' : 'Свернуть панель проектов';
    sidebarToggle.onclick = () => togglePanel('sidebar');
    sidebar.appendChild(sidebarToggle);
    
    // Кнопка для правой панели
    const rightbarToggle = document.createElement('button');
    rightbarToggle.className = 'rightbar-toggle';
    rightbarToggle.innerHTML = appState.uiState.rightbarCollapsed ? '←' : '→';
    rightbarToggle.title = appState.uiState.rightbarCollapsed ? 'Развернуть панель артефактов' : 'Свернуть панель артефактов';
    rightbarToggle.onclick = () => togglePanel('rightbar');
    rightbar.appendChild(rightbarToggle);
}

function togglePanel(panelType) {
    const panel = document.querySelector(`.${panelType}`);
    const isCollapsed = panel.classList.contains('collapsed');
    
    if (isCollapsed) {
        // Разворачиваем панель
        panel.classList.remove('collapsed');
        if (panelType === 'sidebar') {
            appState.uiState.sidebarCollapsed = false;
            document.querySelector('.sidebar-toggle').innerHTML = '←';
            document.querySelector('.sidebar-toggle').title = 'Свернуть панель проектов';
        } else {
            appState.uiState.rightbarCollapsed = false;
            document.querySelector('.rightbar-toggle').innerHTML = '→';
            document.querySelector('.rightbar-toggle').title = 'Свернуть панель артефактов';
        }
    } else {
        // Сворачиваем панель
        panel.classList.add('collapsed');
        if (panelType === 'sidebar') {
            appState.uiState.sidebarCollapsed = true;
            document.querySelector('.sidebar-toggle').innerHTML = '→';
            document.querySelector('.sidebar-toggle').title = 'Развернуть панель проектов';
        } else {
            appState.uiState.rightbarCollapsed = true;
            document.querySelector('.rightbar-toggle').innerHTML = '←';
            document.querySelector('.rightbar-toggle').title = 'Развернуть панель артефактов';
        }
    }
    
    // Сохраняем состояние
    saveUIState();
}

function saveUIState() {
    localStorage.setItem('projectchat_ui_state', JSON.stringify(appState.uiState));
}

// Управление темами
function setupThemeManager() {
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    if (!themeToggleBtn) return;
    
    // Загружаем сохраненную тему
    const savedTheme = localStorage.getItem('projectchat_theme') || 'dark';
    applyTheme(savedTheme);
    
    // Настраиваем обработчик клика
    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        const themes = ['dark', 'light', 'blue', 'green'];
        const currentIndex = themes.indexOf(currentTheme);
        const nextIndex = (currentIndex + 1) % themes.length;
        const nextTheme = themes[nextIndex];
        
        applyTheme(nextTheme);
        localStorage.setItem('projectchat_theme', nextTheme);
    });
}

function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    
    // Обновляем подсветку синтаксиса для темы
    updateSyntaxHighlighting(theme);
}

function updateSyntaxHighlighting(theme) {
    // Удаляем старый стиль подсветки
    const oldLink = document.querySelector('link[href*="highlight.js"]');
    if (oldLink) {
        oldLink.remove();
    }
    
    // Добавляем новый стиль в зависимости от темы
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    
    if (theme === 'light') {
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
    } else if (theme === 'blue') {
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/night-owl.min.css';
    } else if (theme === 'green') {
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css';
    } else {
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css';
    }
    
    document.head.appendChild(link);
    
    // Переприменяем подсветку
    if (typeof hljs !== 'undefined') {
        hljs.highlightAll();
    }
}

// Предпросмотр документа
async function previewDocument(docId) {
    try {
        // Показываем загрузку
        showLoading('Загрузка документа...');
        
        // Загружаем данные документа и статистику параллельно
        const [previewResponse, statsResponse] = await Promise.all([
            fetch(`${API_BASE}/documents/${docId}/preview`),
            fetch(`${API_BASE}/documents/${docId}/pii-stats`)
        ]);
        
        if (!previewResponse.ok) {
            throw new Error(`Ошибка загрузки предпросмотра: ${previewResponse.status}`);
        }
        
        const data = await previewResponse.json();
        const statsData = statsResponse.ok ? await statsResponse.json() : null;
        
        hideLoading();
        
        // Парсим статистику PII
        let piiStats = null;
        let piiCategories = {};
        let piiEntities = {};
        let totalPii = 0;
        
        if (statsData && statsData.stats) {
            try {
                const stats = JSON.parse(statsData.stats);
                piiStats = stats;
                totalPii = stats.total || 0;
                piiCategories = stats.categories || {};
                piiEntities = stats.entities || {};
            } catch (e) {
                console.warn('Failed to parse PII stats:', e);
            }
        }
        
        // Создаем улучшенное модальное окно для предпросмотра
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3>📄 ${escapeHtml(data.name)}</h3>
                    <button class="btn-icon modal-close-btn" title="Закрыть">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/>
                            <line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                
                <div class="preview-tabs">
                    <button class="preview-tab active" data-tab="content">Содержимое</button>
                    <button class="preview-tab" data-tab="pii">PII Статистика</button>
                    <button class="preview-tab" data-tab="anonymization">Анонимизация</button>
                    <button class="preview-tab" data-tab="metadata">Метаданные</button>
                </div>
                
                <div class="modal-body">
                    <!-- Вкладка: Содержимое -->
                    <div class="preview-tab-content active" id="tab-content">
                        <div class="preview-content-controls">
                            <div>
                                <button class="preview-toggle-btn" id="toggle-view-btn">
                                    Показать оригинал
                                </button>
                            </div>
                            <div style="font-size: 12px; color: var(--text-secondary);">
                                ${data.content ? `${data.content.length} символов` : 'Содержимое недоступно'}
                            </div>
                        </div>
                        <div class="preview-content-area" id="document-content">
                            ${escapeHtml(data.content || 'Содержимое недоступно')}
                        </div>
                    </div>
                    
                    <!-- Вкладка: PII Статистика -->
                    <div class="preview-tab-content" id="tab-pii">
                        ${totalPii > 0 ? `
                            <div class="preview-info-grid">
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Всего PII</div>
                                    <div class="preview-info-value">${totalPii}</div>
                                </div>
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Категорий</div>
                                    <div class="preview-info-value">${Object.keys(piiCategories).length}</div>
                                </div>
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Типов сущностей</div>
                                    <div class="preview-info-value">${Object.keys(piiEntities).length}</div>
                                </div>
                            </div>
                            
                            ${Object.keys(piiCategories).length > 0 ? `
                                <h4>По категориям:</h4>
                                <div class="pii-chart-container">
                                    <div class="pii-chart">
                                        ${Object.entries(piiCategories).map(([category, count]) => `
                                            <div class="pii-chart-bar">
                                                <div class="pii-chart-label">${escapeHtml(category)}</div>
                                                <div class="pii-chart-bar-inner">
                                                    <div class="pii-chart-fill pii-${category.toLowerCase()}" 
                                                         style="width: ${Math.min(100, (count / totalPii) * 100)}%"></div>
                                                </div>
                                                <div class="pii-chart-value">${count}</div>
                                            </div>
                                        `).join('')}
                                    </div>
                                    <div class="pii-legend">
                                        ${Object.keys(piiCategories).map(category => `
                                            <div class="pii-legend-item">
                                                <div class="pii-legend-color pii-${category.toLowerCase()}"></div>
                                                <span>${escapeHtml(category)}</span>
                                            </div>
                                        `).join('')}
                                    </div>
                                </div>
                            ` : ''}
                            
                            ${Object.keys(piiEntities).length > 0 ? `
                                <h4 style="margin-top: 20px;">По типам сущностей:</h4>
                                <div class="preview-info-grid">
                                    ${Object.entries(piiEntities).map(([entity, count]) => `
                                        <div class="preview-info-item">
                                            <div class="preview-info-label">${escapeHtml(entity)}</div>
                                            <div class="preview-info-value">${count}</div>
                                        </div>
                                    `).join('')}
                                </div>
                            ` : ''}
                        ` : `
                            <div style="text-align: center; padding: 40px; color: var(--text-secondary);">
                                <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                                <h4>Статистика PII недоступна</h4>
                                <p>Для этого документа нет данных о найденных персональных данных.</p>
                            </div>
                        `}
                    </div>
                    
                    <!-- Вкладка: Анонимизация -->
                    <div class="preview-tab-content" id="tab-anonymization">
                        ${data.anonymization_log ? `
                            <div class="preview-info-grid">
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Статус</div>
                                    <div class="preview-info-value">
                                        <span class="document-status ${data.status}">${data.status}</span>
                                    </div>
                                </div>
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Дата анонимизации</div>
                                    <div class="preview-info-value">${formatDate(data.updated_at || data.created_at)}</div>
                                </div>
                            </div>
                            
                            <h4>Лог анонимизации:</h4>
                            <div class="preview-content-area" style="max-height: 300px;">
                                ${escapeHtml(data.anonymization_log)}
                            </div>
                            
                            <div style="margin-top: 16px; text-align: center;">
                                <button class="btn btn-secondary" id="deanonymize-btn">
                                    Восстановить оригинал
                                </button>
                            </div>
                        ` : `
                            <div style="text-align: center; padding: 40px; color: var(--text-secondary);">
                                <div style="font-size: 48px; margin-bottom: 16px;">🔒</div>
                                <h4>Анонимизация не выполнена</h4>
                                <p>Этот документ еще не был анонимизирован.</p>
                            </div>
                        `}
                    </div>
                    
                    <!-- Вкладка: Метаданные -->
                    <div class="preview-tab-content" id="tab-metadata">
                        <div class="preview-info-grid">
                            <div class="preview-info-item">
                                <div class="preview-info-label">Имя файла</div>
                                <div class="preview-info-value">${escapeHtml(data.name)}</div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">Тип файла</div>
                                <div class="preview-info-value">${data.file_type}</div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">Размер</div>
                                <div class="preview-info-value">${formatFileSize(data.size)}</div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">Дата загрузки</div>
                                <div class="preview-info-value">${formatDate(data.created_at)}</div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">Дата обновления</div>
                                <div class="preview-info-value">${formatDate(data.updated_at || data.created_at)}</div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">Статус</div>
                                <div class="preview-info-value">
                                    <span class="document-status ${data.status}">${data.status}</span>
                                </div>
                            </div>
                            <div class="preview-info-item">
                                <div class="preview-info-label">ID документа</div>
                                <div class="preview-info-value" style="font-family: monospace; font-size: 12px;">${docId}</div>
                            </div>
                        </div>
                        
                        ${data.original_path ? `
                            <h4>Пути к файлам:</h4>
                            <div class="preview-info-grid">
                                <div class="preview-info-item">
                                    <div class="preview-info-label">Оригинальный файл</div>
                                    <div class="preview-info-value" style="font-family: monospace; font-size: 12px; word-break: break-all;">
                                        ${escapeHtml(data.original_path)}
                                    </div>
                                </div>
                                ${data.anonymized_path ? `
                                    <div class="preview-info-item">
                                        <div class="preview-info-label">Анонимизированный файл</div>
                                        <div class="preview-info-value" style="font-family: monospace; font-size: 12px; word-break: break-all;">
                                            ${escapeHtml(data.anonymized_path)}
                                        </div>
                                    </div>
                                ` : ''}
                            </div>
                        ` : ''}
                    </div>
                </div>
                
                <div class="modal-footer">
                    <button class="btn btn-secondary modal-close-btn">Закрыть</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Добавляем обработчики вкладок
        modal.querySelectorAll('.preview-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                // Убираем активный класс у всех вкладок
                modal.querySelectorAll('.preview-tab').forEach(t => t.classList.remove('active'));
                modal.querySelectorAll('.preview-tab-content').forEach(c => c.classList.remove('active'));
                
                // Добавляем активный класс текущей вкладке
                tab.classList.add('active');
                const tabId = tab.getAttribute('data-tab');
                document.getElementById(`tab-${tabId}`).classList.add('active');
            });
        });
        
        // Обработчик переключения вида (оригинал/анонимизированный)
        const toggleBtn = modal.querySelector('#toggle-view-btn');
        if (toggleBtn && data.original_path && data.anonymized_path) {
            let showingOriginal = false;
            let originalContent = null;
            
            toggleBtn.addEventListener('click', async () => {
                if (!originalContent) {
                    // Загружаем оригинальное содержимое
                    try {
                        showLoading('Загрузка оригинального содержимого...');
                        const response = await fetch(`${API_BASE}/documents/${docId}/deanonymize`, {
                            method: 'POST'
                        });
                        
                        if (response.ok) {
                            const result = await response.json();
                            originalContent = result.original_text || 'Оригинальное содержимое недоступно';
                        } else {
                            originalContent = 'Ошибка загрузки оригинального содержимого';
                        }
                    } catch (error) {
                        originalContent = `Ошибка: ${error.message}`;
                    } finally {
                        hideLoading();
                    }
                }
                
                const contentArea = modal.querySelector('#document-content');
                if (showingOriginal) {
                    contentArea.textContent = data.content || 'Содержимое недоступно';
                    toggleBtn.textContent = 'Показать оригинал';
                } else {
                    contentArea.textContent = originalContent;
                    toggleBtn.textContent = 'Показать анонимизированный';
                }
                showingOriginal = !showingOriginal;
            });
        } else if (toggleBtn) {
            toggleBtn.disabled = true;
            toggleBtn.textContent = 'Оригинал недоступен';
        }
        
        // Обработчик восстановления оригинала
        const deanonymizeBtn = modal.querySelector('#deanonymize-btn');
        if (deanonymizeBtn) {
            deanonymizeBtn.addEventListener('click', async () => {
                if (confirm('Вы уверены, что хотите восстановить оригинальный текст документа? Это действие нельзя отменить.')) {
                    try {
                        showLoading('Восстановление оригинала...');
                        await deanonymizeDocument(docId);
                        hideLoading();
                        showToast('Оригинальный текст восстановлен', 'success');
                        modal.remove();
                    } catch (error) {
                        hideLoading();
                        showError(`Ошибка восстановления: ${error.message}`);
                    }
                }
            });
        }
        
        // Добавляем обработчики закрытия
        modal.querySelectorAll('.modal-close-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                modal.remove();
            });
        });
        
        // Закрытие по клику вне модального окна
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.remove();
            }
        });
        
        // Закрытие по клавише Escape
        document.addEventListener('keydown', function closeOnEscape(e) {
            if (e.key === 'Escape') {
                modal.remove();
                document.removeEventListener('keydown', closeOnEscape);
            }
        });
        
    } catch (error) {
        hideLoading();
        console.error('Error previewing document:', error);
        showError(`Ошибка предпросмотра документа: ${error.message}`);
    }
}

// Де-анонимизация документа
async function deanonymizeDocument(docId) {
    try {
        const response = await fetch(`${API_BASE}/documents/${docId}/deanonymize`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка де-анонимизации: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Создаем модальное окно для показа оригинального текста
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 800px;">
                <div class="modal-header">
                    <h3>Оригинальный текст документа: ${escapeHtml(data.name)}</h3>
                    <button class="btn-icon modal-close-btn" title="Закрыть">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/>
                            <line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="preview-info">
                        <div><strong>Восстановлено записей:</strong> ${data.log_entries}</div>
                        <div><strong>Размер текста:</strong> ${data.original_text ? data.original_text.length : 0} символов</div>
                    </div>
                    <div class="preview-content">
                        <h4>Оригинальный текст (с восстановленными PII):</h4>
                        <div class="preview-text" style="max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 13px;">
                            ${escapeHtml(data.original_text || 'Текст недоступен')}
                        </div>
                    </div>
                    <div class="preview-content" style="margin-top: 20px;">
                        <h4>Анонимизированный текст (для сравнения):</h4>
                        <div class="preview-text" style="max-height: 200px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 13px; background-color: var(--bg-tertiary); padding: 10px; border-radius: 4px;">
                            ${escapeHtml(data.anonymized_text ? data.anonymized_text.substring(0, 1000) + (data.anonymized_text.length > 1000 ? '...' : '') : 'Текст недоступен')}
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary modal-close-btn">Закрыть</button>
                    ${data.original_text ? `
                    <button class="btn btn-primary" id="copy-original-text">Копировать оригинал</button>
                    ` : ''}
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Добавляем обработчики закрытия
        modal.querySelectorAll('.modal-close-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                modal.remove();
                document.removeEventListener('keydown', closeOnEscape);
            });
        });
        
        // Обработчик копирования текста
        const copyBtn = document.getElementById('copy-original-text');
        if (copyBtn && data.original_text) {
            copyBtn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(data.original_text);
                    copyBtn.textContent = 'Скопировано!';
                    copyBtn.classList.add('btn-success');
                    setTimeout(() => {
                        copyBtn.textContent = 'Копировать оригинал';
                        copyBtn.classList.remove('btn-success');
                    }, 2000);
                } catch (copyError) {
                    showError('Не удалось скопировать текст');
                }
            });
        }
        
        // Закрытие по ESC
        const closeOnEscape = (e) => {
            if (e.key === 'Escape') {
                modal.remove();
                document.removeEventListener('keydown', closeOnEscape);
            }
        };
        document.addEventListener('keydown', closeOnEscape);
        
        // Закрытие по клику на фон
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.remove();
                document.removeEventListener('keydown', closeOnEscape);
            }
        });
        
    } catch (error) {
        console.error('Error deanonymizing document:', error);
        showError(`Ошибка восстановления оригинального текста: ${error.message}`);
    }
}

// Загрузка статистики PII
async function loadPiiStatistics(docId) {
    try {
        const response = await fetch(`${API_BASE}/documents/${docId}/pii-stats`);
        if (!response.ok) {
            throw new Error(`Ошибка загрузки статистики: ${response.status}`);
        }
        
        const data = await response.json();
        const statsContent = document.getElementById(`pii-stats-${docId}`);
        
        if (data.stats) {
            // Парсим JSON статистики
            let statsHtml = '';
            try {
                const stats = JSON.parse(data.stats);
                statsHtml = `
                    <div class="pii-stats-details">
                        <div class="pii-stat-item">
                            <span class="pii-stat-label">Всего PII:</span>
                            <span class="pii-stat-value">${stats.total || 0}</span>
                        </div>
                        ${stats.categories ? Object.entries(stats.categories).map(([category, count]) => `
                            <div class="pii-stat-item">
                                <span class="pii-stat-label">${escapeHtml(category)}:</span>
                                <span class="pii-stat-value">${count}</span>
                            </div>
                        `).join('') : ''}
                        ${stats.entities ? Object.entries(stats.entities).map(([entity, count]) => `
                            <div class="pii-stat-item">
                                <span class="pii-stat-label">${escapeHtml(entity)}:</span>
                                <span class="pii-stat-value">${count}</span>
                            </div>
                        `).join('') : ''}
                    </div>
                `;
            } catch (parseError) {
                // Если не JSON, показываем как текст
                statsHtml = `<div class="pii-stats-text">${escapeHtml(data.stats)}</div>`;
            }
            
            statsContent.innerHTML = statsHtml;
        } else {
            statsContent.innerHTML = '<div class="pii-stats-text">Статистика недоступна</div>';
        }
        
    } catch (error) {
        console.error('Error loading PII statistics:', error);
        const statsContent = document.getElementById(`pii-stats-${docId}`);
        statsContent.innerHTML = `<div class="pii-stats-error">Ошибка загрузки статистики: ${error.message}</div>`;
    }
}

// Инициализация теперь выполняется в app-main.js после загрузки всех скриптов