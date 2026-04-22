"""
Russian-language text anonymization using Presidio + spaCy ru_core_news_sm.

Lazy initialization: the heavy NLP model is loaded on first call to anonymize(),
not at module import time.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

_lock = threading.Lock()
_analyzer: "AnalyzerEngine | None" = None
_anonymizer_engine: "AnonymizerEngine | None" = None

ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "ORGANIZATION",
    "DATE_TIME",
    "RU_PHONE",
    "RU_INN",
    "RU_SNILS",
    "RU_KPP",
    "RU_BANK_ACCOUNT",
    "RU_CORR_ACCOUNT",
    "RU_BIK",
    "RU_PASSPORT",
    "RU_OGRN",
    "RU_OGRNIP",
    "RU_OKTMO",
    "RU_CAR_NUMBER",
    "RU_CONTRACT_NUMBER",
    "RU_POLICY_NUMBER",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "VIN",
]


def _build_engines():
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    nlp_configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "ru", "model_name": "ru_core_news_sm"}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
    nlp_engine = provider.create_engine()

    # Russian phone patterns: +7 (xxx) xxx-xx-xx, 8-xxx-xxx-xx-xx, etc.
    ru_phone = PatternRecognizer(
        supported_entity="RU_PHONE",
        patterns=[
            Pattern(
                name="ru_phone",
                regex=r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
                score=0.8,
            )
        ],
        context=["телефон", "тел", "phone", "моб", "мобильный"],
    )

    # Russian INN (taxpayer ID): 10 or 12 digits
    ru_inn = PatternRecognizer(
        supported_entity="RU_INN",
        patterns=[
            Pattern(
                name="ru_inn_10",
                regex=r"\b\d{10}\b",
                score=0.5,
            ),
            Pattern(
                name="ru_inn_12",
                regex=r"\b\d{12}\b",
                score=0.5,
            ),
        ],
        context=["ИНН", "инн", "taxpayer", "налог"],
    )

    # Russian SNILS (pension fund): xxx-xxx-xxx xx
    ru_snils = PatternRecognizer(
        supported_entity="RU_SNILS",
        patterns=[
            Pattern(
                name="ru_snils",
                regex=r"\b\d{3}-\d{3}-\d{3}\s\d{2}\b",
                score=0.9,
            )
        ],
        context=["СНИЛС", "снилс", "пенсионный"],
    )

    # Russian KPP (registration reason code): 9 digits
    ru_kpp = PatternRecognizer(
        supported_entity="RU_KPP",
        patterns=[
            Pattern(
                name="ru_kpp",
                regex=r"\b\d{9}\b",
                score=0.8,
            )
        ],
        context=["КПП", "кпп"],
    )

    # Russian bank account: 20 digits with context
    ru_bank_account = PatternRecognizer(
        supported_entity="RU_BANK_ACCOUNT",
        patterns=[
            Pattern(
                name="ru_bank_account",
                regex=r"\b\d{20}\b",
                score=0.7,
            )
        ],
        context=["р/с", "р.с.", "счет", "счёт", "банковский счет"],
    )

    # Russian BIK (bank identification code): 9 digits
    ru_bik = PatternRecognizer(
        supported_entity="RU_BIK",
        patterns=[
            Pattern(
                name="ru_bik",
                regex=r"\b\d{9}\b",
                score=0.8,
            )
        ],
        context=["БИК", "бик"],
    )

    # Russian passport: series and number
    ru_passport = PatternRecognizer(
        supported_entity="RU_PASSPORT",
        patterns=[
            Pattern(
                name="ru_passport_series",
                regex=r"\b\d{2}\s?\d{2}\b",
                score=0.6,
            ),
            Pattern(
                name="ru_passport_number",
                regex=r"\b\d{6}\b",
                score=0.7,
            )
        ],
        context=["паспорт", "серия", "номер"],
    )

    # Russian OGRN (main state registration number): 13 digits
    ru_ogrn = PatternRecognizer(
        supported_entity="RU_OGRN",
        patterns=[
            Pattern(
                name="ru_ogrn",
                regex=r"\b\d{13}\b",
                score=0.8,
            )
        ],
        context=["ОГРН", "огрн"],
    )

    # Russian OGRNIP (for individual entrepreneurs): 15 digits
    ru_ogrnip = PatternRecognizer(
        supported_entity="RU_OGRNIP",
        patterns=[
            Pattern(
                name="ru_ogrnip",
                regex=r"\b\d{15}\b",
                score=0.8,
            )
        ],
        context=["ОГРНИП", "огрнип"],
    )

    # Credit card numbers
    credit_card = PatternRecognizer(
        supported_entity="CREDIT_CARD",
        patterns=[
            Pattern(
                name="credit_card",
                regex=r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
                score=0.9,
            )
        ],
        context=["карта", "карту", "номер карты", "credit card"],
    )

    # IP addresses
    ip_address = PatternRecognizer(
        supported_entity="IP_ADDRESS",
        patterns=[
            Pattern(
                name="ip_address",
                regex=r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
                score=0.7,
            )
        ],
        context=["IP", "адрес", "сеть"],
    )

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["ru"])
    analyzer.registry.add_recognizer(ru_phone)
    analyzer.registry.add_recognizer(ru_inn)
    analyzer.registry.add_recognizer(ru_snils)
    analyzer.registry.add_recognizer(ru_kpp)
    analyzer.registry.add_recognizer(ru_bank_account)
    analyzer.registry.add_recognizer(ru_bik)
    analyzer.registry.add_recognizer(ru_passport)
    analyzer.registry.add_recognizer(ru_ogrn)
    analyzer.registry.add_recognizer(ru_ogrnip)
    analyzer.registry.add_recognizer(credit_card)
    analyzer.registry.add_recognizer(ip_address)

    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


def _get_engines():
    global _analyzer, _anonymizer_engine
    if _analyzer is None:
        with _lock:
            if _analyzer is None:
                _analyzer, _anonymizer_engine = _build_engines()
    return _analyzer, _anonymizer_engine


def anonymize(text: str) -> tuple[str, list[dict]]:
    """
    Anonymize PII in Russian text.

    Returns:
        (anonymized_text, log) where log is a list of dicts:
        {"original": str, "replaced_with": str, "type": str}
        ordered by first appearance in the original document.
    """
    if not text or not text.strip():
        return text, []

    analyzer, _ = _get_engines()

    try:
        results = analyzer.analyze(text=text, language="ru", entities=ENTITIES)
    except Exception as e:
        raise RuntimeError(f"Anonymization analysis failed: {e}") from e

    if not results:
        return text, []

    # Deduplicate overlapping spans — keep highest-score result per position
    results = _deduplicate(results)

    # Pass 1: sort by start position ASC, assign sequential labels per entity type
    results_asc = sorted(results, key=lambda r: r.start)
    counters: dict[str, int] = {}
    assignments: list[tuple[str, object]] = []  # (replacement_label, result)

    for result in results_asc:
        et = result.entity_type
        counters[et] = counters.get(et, 0) + 1
        label = f"<{et}_{counters[et]}>"
        assignments.append((label, result))

    # Pass 2: apply replacements end-to-start (preserves offsets)
    anonymized = text
    log = []
    for label, result in reversed(assignments):
        original = anonymized[result.start:result.end]
        log.append({"original": original, "replaced_with": label, "type": result.entity_type})
        anonymized = anonymized[:result.start] + label + anonymized[result.end:]

    # Reverse log so entries are in document order (top-to-bottom)
    log.reverse()

    return anonymized, log


def _deduplicate(results: list) -> list:
    """Remove overlapping spans, keeping the highest-score result for each."""
    if not results:
        return results

    sorted_results = sorted(results, key=lambda r: (r.start, -r.score))
    deduped = []
    last_end = -1

    for result in sorted_results:
        if result.start >= last_end:
            deduped.append(result)
            last_end = result.end
        else:
            # Overlapping span: keep the one with higher score
            if deduped and result.score > deduped[-1].score:
                deduped[-1] = result
                last_end = result.end

    return deduped


def deanonymize(anonymized_text: str, log: list[dict]) -> str:
    """
    Restore original text from anonymized text using the anonymization log.
    
    Args:
        anonymized_text: Text with PII tags like <PERSON_1>
        log: List of dicts with keys: "original", "replaced_with", "type"
    
    Returns:
        Original text with PII restored
    """
    if not log or not anonymized_text:
        return anonymized_text
    
    # Create mapping from replacement tag to original value
    mapping = {entry["replaced_with"]: entry["original"] for entry in log}
    
    # Replace all occurrences of each tag
    restored_text = anonymized_text
    for tag, original in mapping.items():
        restored_text = restored_text.replace(tag, original)
    
    return restored_text
