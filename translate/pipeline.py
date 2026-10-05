"""خط ترجمة المستند: الآيات من الترجمة المعتمدة وسائر النصوص بـ Gemini، والكتابة في content."""

from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from content.models import DocumentTranslation, PhraseTranslation
from translate.models import QuranTranslationKey
from translate.services import quran_extract, text_translate
from translate.services.llm import LLMError
from translate.services.quran_match import AyahIndex


@dataclass
class RunSummary:
    counts: dict = field(
        default_factory=lambda: {
            "quran_extract": 0,
            "quran_fallback": 0,
            "text": 0,
            "skipped_untranslatable": 0,
            "skipped_approved": 0,
            "skipped_existing": 0,
            "failed": 0,
        }
    )
    errors: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    partial: bool = False

    @property
    def written(self):
        return sum(self.counts[k] for k in ("quran_extract", "text"))


def is_ayah(phrase):
    if phrase.content_type.code == "ayah":
        return True
    analysis = getattr(phrase, "analysis", None)
    return bool(analysis and analysis.kind == "quran")


def translation_key_for(language):
    return QuranTranslationKey.objects.filter(language=language).first()


def translate_document(
    document_translation,
    *,
    force=False,
    dry_run=False,
    limit=None,
    phrase_ids=None,
    index=None,
    on_progress=None,
    on_result=None,
):
    """يترجم عبارات المستند ويعيد RunSummary؛ يواصل عند فشل عبارة ويبلّغ on_progress وon_result."""
    summary = RunSummary()
    language = document_translation.target_language
    key = translation_key_for(language)
    index = index if index is not None else (AyahIndex() if key else None)

    existing = {row.phrase_id: row for row in document_translation.phrases.all()}
    phrases = document_translation.document.phrases.select_related(
        "content_type", "analysis"
    ).order_by("group_id", "group_order")
    if phrase_ids:
        phrases = phrases.filter(phrase_id__in=phrase_ids)
        summary.partial = True

    phrases = list(phrases)
    total = sum(1 for p in phrases if p.translatable)
    done = 0

    def _tick():
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total)

    processed = 0
    for phrase in phrases:
        if not phrase.translatable:
            summary.counts["skipped_untranslatable"] += 1
            continue
        row = existing.get(phrase.pk)
        if row and row.status == PhraseTranslation.Status.APPROVED:
            summary.counts["skipped_approved"] += 1
            _tick()
            continue
        if row and row.status == PhraseTranslation.Status.SUGGESTED and not force:
            summary.counts["skipped_existing"] += 1
            _tick()
            continue
        if limit is not None and processed >= limit:
            summary.partial = True
            break
        processed += 1

        try:
            text, method, note = _translate_phrase(phrase, language, key, index, dry_run=dry_run)
        except LLMError as exc:
            summary.counts["failed"] += 1
            summary.errors.append((phrase.pk, str(exc)))
            summary.lines.append(f"فشل {phrase.pk}: {exc}")
            _tick()
            continue

        _tick()
        summary.counts[method] += 1
        if method == "quran_fallback":
            summary.counts["text"] += 1
        summary.lines.append(f"{method:<15} {phrase.pk} {note}".rstrip())
        if dry_run or text is None:
            continue
        if on_result:
            on_result(phrase, text, method)
        PhraseTranslation.objects.update_or_create(
            document_translation=document_translation,
            phrase=phrase,
            defaults={
                "ai_translation": text,
                "translation": text,
                "status": PhraseTranslation.Status.SUGGESTED,
            },
        )

    if not dry_run:
        finish(document_translation, summary, used_quran=key is not None)
    return summary


def _translate_phrase(phrase, language, key, index, *, dry_run):
    """(النص أو None في dry_run، الطريقة، ملاحظة للسجل)."""
    if is_ayah(phrase) and key:
        reference = getattr(getattr(phrase, "analysis", None), "reference", "") or ""
        match = index.find(phrase.text, reference)
        if match:
            if dry_run:
                return None, "quran_extract", f"← {match.reference} ({match.method})"
            result = quran_extract.translate_ayah(phrase.text, match, key)
            if result:
                return result[0], result[1], f"← {match.reference} ({match.method})"
            note = f"لا ترجمة معتمدة لـ {match.reference}؛ تُرجمت كنص"
        else:
            note = "لم تُطابَق بآية؛ تُرجمت كنص"
        if dry_run:
            return None, "quran_fallback", note
        return _text(phrase, language), "quran_fallback", note

    if dry_run:
        return None, "text", ""
    return _text(phrase, language), "text", ""


def _term_pairs(phrase, language):
    """أزواج التوحيد (عربي ← المقابل المعتمد بلغة الهدف) لكتلة TERMS_BLOCK."""
    from content.models import GlossaryTranslation

    iso = language.iso_code.lower()
    pairs = []
    for link in phrase.terms.select_related("glossary"):
        g = link.glossary
        if iso == "en":
            if g.en:
                pairs.append((g.ar, g.en))
            continue
        stored = GlossaryTranslation.objects.filter(glossary=g, language=language).first()
        if stored:
            pairs.append((g.ar, stored.title))
    return pairs


def _text(phrase, language):
    return text_translate.translate_text(phrase.text, language, terms=_term_pairs(phrase, language))


def finish(document_translation, summary, *, used_quran):
    """يسجل النماذج المستخدمة ويضبط الحالة: «قيد المراجعة» عند الاكتمال بلا فشل، وإلا «جارية»."""
    fields = ["updated_at"]
    if summary.written:
        models_used = settings.TRANSLATE_MODEL
        if used_quran:
            models_used = f"{models_used}; quran: {settings.QURAN_EXTRACT_MODEL}"
        document_translation.ai_model = models_used[:100]
        fields.append("ai_model")
    unfinished = (DocumentTranslation.Status.PENDING, DocumentTranslation.Status.TRANSLATING)
    if document_translation.status in unfinished:
        document_translation.status = (
            DocumentTranslation.Status.TRANSLATING
            if summary.errors or summary.partial
            else DocumentTranslation.Status.REVIEW
        )
        fields.append("status")
    document_translation.updated_at = timezone.now()
    document_translation.save(update_fields=fields)
