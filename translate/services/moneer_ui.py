"""تحويل ترجمة المستند إلى شكل وحدات واجهة «التجربة الكاملة» (pages/html/translate.html)."""

from __future__ import annotations

from classify.services.moneer_ui import (
    _EMPTY_AYA_BRACKETS,
    FOOTNOTE_LABEL,
    attribution_label,
    title_label,
    variant_warning,
)
from classify.services.moneer_ui import (
    surface as _surface,
)
from content.models import GlossaryTranslation, PhraseTerm, PhraseTranslation
from translate.models import QuranTranslationKey

_KIND = {
    "quran": "aya",
    "hadith": "hadith",
    "athar": "athar",
    "term": "term",
}

QURAN_SOURCE = "الترجمة المعتمدة"
GLOSSARY_SOURCE = "معجم المصطلحات"
_NO_TERM_SOURCE = ("quran", "hadith", "athar", "citation")


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
        approved = bool(row) and row.status == PhraseTranslation.Status.APPROVED
        ar = _EMPTY_AYA_BRACKETS.sub("", phrase.text).strip()

        if kind == "heading":
            part = ar
            out.append(
                {
                    "id": phrase.pk,
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
                    "approved": approved,
                }
            )
            continue

        unit = {
            "id": phrase.pk,
            "k": _KIND.get(kind, "text"),
            "ar": ar,
            "en": en,
            "meta": "",
            "src": "",
            "conf": conf,
            "ai": True,
            "gen": False,
            "part": part,
            "approved": approved,
        }
        if kind == "quran":
            locked = approved_source and bool(en)
            variant = reason_code == "unmatched_quran"
            unit.update(
                ai=not locked,
                locked=locked,
                src=QURAN_SOURCE if locked else "ترجمة مُنير",
                warn=variant,
                warnText=variant_warning("") if variant else "",
            )
        elif kind in ("hadith", "athar", "term"):
            unit.update(src="ترجمة مُنير", locked=False)
        elif kind == "attribution":
            unit.update(lead=True, tagLabel=attribution_label(phrase.text))
        elif kind == "citation":
            unit.update(tagLabel="عزو", src="ترجمة مُنير", locked=False)
        else:
            unit.update(gen=True)
        if phrase.tag == "footnote":
            unit.update(tagLabel=FOOTNOTE_LABEL, isFootnote=True)
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


def mark_approved_terms(segments: list[dict]) -> None:
    """بعد prune_unmatched: ما ثبت مقابل مصطلحه في ترجمته يُعرض معتمداً ويبقى قابلاً للتحرير."""
    for seg in segments:
        if seg["k"] in ("term", "text") and seg.get("en") and seg.get("terms"):
            seg.update(ai=False, src=GLOSSARY_SOURCE)


def _approved_equivalents(document, language) -> dict[str, list[str]]:
    """المقابل المعتمد لمصطلحات كل جملة بلغة الهدف (كـ pipeline._term_pairs) باستعلامين للمستند."""
    links = list(PhraseTerm.objects.filter(phrase__document=document).select_related("glossary"))
    english = language.iso_code.lower() == "en"
    titles = (
        {}
        if english
        else dict(
            GlossaryTranslation.objects.filter(
                language=language, glossary__in=[link.glossary_id for link in links]
            ).values_list("glossary_id", "title")
        )
    )
    out = {}
    for link in links:
        equivalent = link.glossary.en if english else titles.get(link.glossary_id)
        if equivalent:
            out.setdefault(link.phrase_id, []).append(equivalent)
    return out


def translation_progress(document_translation) -> dict:
    """تقدّم ترجمة مستند من القاعدة: نص كل جملة تُرجمت بفهرسها في الواجهة، ومصدرها المعتمد.

    المصدر بقاعدة to_ui_segments: الآية مقفلة إن كان للغة مفتاح ترجمة معتمد، وما سواها من
    المعجم إن ورد في ترجمته مقابل مصطلحه المعتمد.
    """
    document, language = document_translation.document, document_translation.target_language
    approved_quran = QuranTranslationKey.objects.filter(language=language).exists()
    texts = dict(
        document_translation.phrases.exclude(translation="").values_list("phrase_id", "translation")
    )
    equivalents = _approved_equivalents(document, language)
    rows, sources, done, total = {}, {}, 0, 0
    phrases = document.phrases.select_related("analysis").order_by("group_id", "group_order")
    for i, phrase in enumerate(phrases):
        total += phrase.translatable
        text = texts.get(phrase.pk)
        if not text:
            continue
        done += phrase.translatable
        rows[i] = text
        analysis = getattr(phrase, "analysis", None)
        kind = analysis.kind if analysis else "plain"
        if kind == "quran":
            if approved_quran:
                sources[i] = {"src": QURAN_SOURCE, "locked": True}
        elif kind not in _NO_TERM_SOURCE:
            low = text.lower()
            if any(eq.lower() in low for eq in equivalents.get(phrase.pk, ())):
                sources[i] = {"src": GLOSSARY_SOURCE}
    return {
        "translation_id": document_translation.pk,
        "status": document_translation.status,
        "done": done,
        "total": total,
        "rows": rows,
        "sources": sources,
    }
