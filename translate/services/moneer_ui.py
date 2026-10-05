"""تحويل ترجمة المستند إلى شكل وحدات واجهة «التجربة الكاملة» (pages/html/translate.html)."""

from __future__ import annotations

from classify.services.moneer_ui import (
    _EMPTY_AYA_BRACKETS,
    attribution_label,
    title_label,
    variant_warning,
)
from classify.services.moneer_ui import (
    surface as _surface,
)
from content.models import GlossaryTranslation, PhraseTranslation
from translate.models import QuranTranslationKey

_KIND = {
    "quran": "aya",
    "hadith": "hadith",
    "athar": "athar",
    "term": "term",
}


def _terms(phrase, language=None, text=None) -> list[dict]:
    """مصطلحات العبارة للواجهة: المقابل بلغة الهدف إن وُجد وإلا الإنجليزي، والتعريف للبطاقة."""
    localized = language is not None and language.iso_code.lower() != "en"
    text = text if text is not None else phrase.text
    out = []
    for link in phrase.terms.select_related("glossary"):
        g = link.glossary
        if not g.ar:
            continue
        equivalent, definition, tr = g.en, "", ""
        if localized:
            stored = GlossaryTranslation.objects.filter(glossary=g, language=language).first()
            if stored:
                equivalent = stored.title
                definition = stored.short_def
                tr = f"English: {g.en}" if g.en else ""
        if not equivalent:
            continue
        out.append({"w": _surface(text, g.ar), "en": equivalent, "def": definition, "tr": tr})
    return out


def to_ui_segments(document, document_translation=None) -> list[dict]:
    """قائمة وحدات الواجهة من عبارات المستند؛ بلا document_translation تُعاد بتصنيفها فقط."""
    translations = (
        {
            row.phrase_id: row
            for row in PhraseTranslation.objects.filter(document_translation=document_translation)
        }
        if document_translation
        else {}
    )
    approved_source = (
        bool(document_translation)
        and QuranTranslationKey.objects.filter(
            language=document_translation.target_language
        ).exists()
    )
    out, part = [], ""
    phrases = document.phrases.select_related("analysis").order_by("group_id", "group_order")
    for phrase in phrases:
        analysis = getattr(phrase, "analysis", None)
        kind = analysis.kind if analysis else "plain"
        conf = f"{analysis.confidence}%" if analysis else ""
        reason_code = (analysis.reason_code or "") if analysis else ""
        row = translations.get(phrase.pk)
        en = (row.translation or "") if row else ""
        ar = _EMPTY_AYA_BRACKETS.sub("", phrase.text).strip()

        if kind == "heading":
            part = ar
            out.append(
                {
                    "k": "text",
                    "ar": ar,
                    "en": en,
                    "meta": "",
                    "src": "",
                    "conf": conf,
                    "ai": True,
                    "gen": True,
                    "part": part,
                    "tagLabel": title_label(phrase.text),
                }
            )
            continue

        unit = {
            "k": _KIND.get(kind, "text"),
            "ar": ar,
            "en": en,
            "meta": "",
            "src": "",
            "conf": conf,
            "ai": True,
            "gen": False,
            "part": part,
        }
        if kind == "quran":
            locked = approved_source and bool(en)
            variant = reason_code == "unmatched_quran"
            unit.update(
                ai=not locked,
                locked=locked,
                src="الترجمة المعتمدة" if locked else "ترجمة مُنير",
                warn=variant,
                warnText=variant_warning("") if variant else "",
            )
        elif kind in ("hadith", "athar", "term"):
            unit.update(src="ترجمة مُنير", locked=False)
        elif kind == "attribution":
            unit.update(lead=True, tagLabel=attribution_label(phrase.text))
        elif kind == "citation":
            unit.update(tagLabel="عزو", en="", conf="100%")
        else:
            unit.update(gen=True)
        if kind not in ("quran", "citation"):
            terms = _terms(
                phrase,
                document_translation.target_language if document_translation else None,
                text=ar,
            )
            if terms:
                unit["terms"] = terms
        out.append(unit)
    return out
