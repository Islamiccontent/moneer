"""مطابقة مقابل المصطلح داخل الترجمة بغير الإنجليزية للتظليل وحده؛ لا يُعتمد إلا مقطع يرد حرفياً."""

from __future__ import annotations

import json

from django.conf import settings

from . import llm

PROMPT = """You are aligning Islamic terminology across languages. For each numbered item below you are given an Arabic term, its canonical English equivalent, and a sentence translated into {lang}. Return the EXACT substring of that sentence which expresses the term — copy it verbatim from the sentence, preserving case, diacritics and punctuation-free boundaries. Respond ONLY with a JSON object mapping item numbers to substrings, e.g. {{"1": "...", "2": ""}}. Use "" when the term is not expressed in the sentence.

{items}"""


def localize_terms(segments: list[dict], language) -> None:
    """يعدّل segments موضعياً: مقابل كل مصطلح يصير مقطعه في الترجمة، ويبقى الإنجليزي في tr."""
    refs = []
    for seg in segments:
        if not seg.get("en"):
            continue
        for term in seg.get("terms") or []:
            if term["en"] and term["en"].lower() in seg["en"].lower():
                continue
            refs.append((seg, term))
    if not refs:
        return

    items = "\n".join(
        f'{n}. Arabic term: "{term["w"]}" (English: {term["en"]}) — sentence: "{seg["en"]}"'
        for n, (seg, term) in enumerate(refs, 1)
    )
    try:
        raw = llm.gemini_generate(
            PROMPT.format(lang=language.name_en, items=items),
            model=settings.TRANSLATE_MODEL,
            api_key=settings.GEMINI_API_KEY,
            temperature=0.0,
        )
        mapping = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except (llm.LLMError, ValueError):
        return
    if not isinstance(mapping, dict):
        return
    for n, (seg, term) in enumerate(refs, 1):
        sub = str(mapping.get(str(n)) or "").strip()
        if sub and sub in seg["en"]:
            term["tr"] = f"English: {term['en']}"
            term["en"] = sub


def prune_unmatched(segments: list[dict]) -> None:
    """يزيل تظليل المصطلح الذي لا مقابل له في ترجمته؛ ما لا ترجمة له بعد يُترك بتظليله العربي."""
    for seg in segments:
        en = (seg.get("en") or "").lower()
        if not en or not seg.get("terms"):
            continue
        kept = [t for t in seg["terms"] if t["en"].lower() in en]
        if kept:
            seg["terms"] = kept
        else:
            del seg["terms"]
