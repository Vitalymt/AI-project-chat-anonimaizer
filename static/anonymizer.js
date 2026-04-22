// Клиентская анонимизация текста с использованием PII_PATTERNS
// Возвращает анонимизированный текст и карту замен

/**
 * Анонимизирует текст, заменяя PII на маркеры
 * @param {string} text - Исходный текст
 * @returns {Object} Объект с анонимизированным текстом и картой замен
 */
function anonymizeText(text) {
    if (!text || typeof text !== 'string') {
        return {
            anonymizedText: '',
            map: []
        };
    }
    
    let anonymizedText = text;
    const map = [];
    const counters = {};
    
    // Применяем все паттерны по порядку
    PII_PATTERNS.forEach(pattern => {
        const matches = [...text.matchAll(pattern.pattern)];
        
        matches.forEach(match => {
            const original = match[0];
            const type = pattern.type;
            
            // Создаем уникальный маркер
            if (!counters[type]) {
                counters[type] = 0;
            }
            counters[type]++;
            const marker = `[PII_${type}_${counters[type]}]`;
            
            // Заменяем в тексте (только первое вхождение в текущей позиции)
            const index = anonymizedText.indexOf(original);
            if (index !== -1) {
                anonymizedText = anonymizedText.substring(0, index) + 
                                marker + 
                                anonymizedText.substring(index + original.length);
                
                // Добавляем в карту замен
                map.push({
                    marker: marker,
                    original: original,
                    type: type,
                    description: pattern.description
                });
            }
        });
    });
    
    return {
        anonymizedText: anonymizedText,
        map: map
    };
}

/**
 * Восстанавливает оригинальный текст из анонимизированного
 * @param {string} anonymizedText - Анонимизированный текст
 * @param {Array} map - Карта замен
 * @returns {string} Восстановленный текст
 */
function deanonymizeText(anonymizedText, map) {
    if (!anonymizedText || !map || !Array.isArray(map)) {
        return anonymizedText || '';
    }
    
    let restoredText = anonymizedText;
    
    // Восстанавливаем в обратном порядке, чтобы маркеры не перекрывались
    const sortedMap = [...map].sort((a, b) => {
        return restoredText.indexOf(b.marker) - restoredText.indexOf(a.marker);
    });
    
    sortedMap.forEach(item => {
        restoredText = restoredText.replace(item.marker, item.original);
    });
    
    return restoredText;
}

/**
 * Извлекает текст из файла (PDF или TXT)
 * @param {File} file - Файл для обработки
 * @returns {Promise<string>} Извлеченный текст
 */
async function extractTextFromFile(file) {
    return new Promise((resolve, reject) => {
        if (!file) {
            reject(new Error('Файл не предоставлен'));
            return;
        }
        
        const fileName = file.name.toLowerCase();
        
        if (fileName.endsWith('.pdf')) {
            // Используем PDF.js для извлечения текста из PDF
            extractTextFromPDF(file).then(resolve).catch(reject);
        } else if (fileName.endsWith('.txt')) {
            // Читаем текстовый файл
            const reader = new FileReader();
            reader.onload = (e) => {
                resolve(e.target.result);
            };
            reader.onerror = (e) => {
                reject(new Error('Ошибка чтения файла'));
            };
            reader.readAsText(file);
        } else {
            reject(new Error('Неподдерживаемый формат файла. Поддерживаются PDF и TXT.'));
        }
    });
}

/**
 * Извлекает текст из PDF файла с использованием PDF.js
 * @param {File} file - PDF файл
 * @returns {Promise<string>} Извлеченный текст
 */
async function extractTextFromPDF(file) {
    return new Promise((resolve, reject) => {
        // Проверяем, загружена ли PDF.js
        if (typeof pdfjsLib === 'undefined') {
            reject(new Error('PDF.js не загружен. Убедитесь, что pdf.worker.min.js подключен.'));
            return;
        }
        
        const reader = new FileReader();
        reader.onload = async (e) => {
            try {
                const typedArray = new Uint8Array(e.target.result);
                const pdf = await pdfjsLib.getDocument({ data: typedArray }).promise;
                let fullText = '';
                
                // Извлекаем текст со всех страниц
                for (let i = 1; i <= pdf.numPages; i++) {
                    const page = await pdf.getPage(i);
                    const textContent = await page.getTextContent();
                    const pageText = textContent.items.map(item => item.str).join(' ');
                    fullText += pageText + '\n';
                }
                
                resolve(fullText);
            } catch (error) {
                reject(new Error(`Ошибка обработки PDF: ${error.message}`));
            }
        };
        
        reader.onerror = () => {
            reject(new Error('Ошибка чтения файла'));
        };
        
        reader.readAsArrayBuffer(file);
    });
}

/**
 * Обрабатывает файл: извлекает текст и анонимизирует его
 * @param {File} file - Файл для обработки
 * @returns {Promise<Object>} Результат обработки
 */
async function processFile(file) {
    try {
        // Извлекаем текст
        const text = await extractTextFromFile(file);
        
        // Анонимизируем текст
        const anonymizationResult = anonymizeText(text);
        
        return {
            success: true,
            fileName: file.name,
            fileSize: file.size,
            text: text,
            anonymizedText: anonymizationResult.anonymizedText,
            anonymizationMap: anonymizationResult.map,
            originalTextLength: text.length,
            anonymizedTextLength: anonymizationResult.anonymizedText.length,
            foundPII: anonymizationResult.map.length
        };
    } catch (error) {
        return {
            success: false,
            error: error.message,
            fileName: file.name
        };
    }
}

// Экспорт функций для использования в других файлах
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        anonymizeText,
        deanonymizeText,
        extractTextFromFile,
        extractTextFromPDF,
        processFile
    };
}