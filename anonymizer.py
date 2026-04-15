"""
Russian-language text anonymization using Presidio + spaCy ru_core_news_lg.

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
]


def _build_engines():
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    nlp_configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "ru", "model_name": "ru_core_news_lg"}],
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

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["ru"])
    analyzer.registry.add_recognizer(ru_phone)
    analyzer.registry.add_recognizer(ru_inn)
    analyzer.registry.add_recognizer(ru_snils)

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
