"""لوحة متابعة المستندات: مرحلة كل مستند وكل لغة في خط الإنتاج ونسبة تقدّمها، من القاعدة وحدها.

خط الإنتاج خمس مراحل بترتيب واجهة مُنير: رفع الملف، التقطيع الذكي، المطابقة والترجمة، المراجعة،
التصدير. المستند المحفوظ تجاوز المرحلتين الأوليين دائماً (لا يُحفظ إلا بعد التقطيع والتصنيف)،
وما بعدهما يُقرأ من حالة ترجمته إلى كل لغة ومن عدّادات جملها المترجمة والمعتمدة.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q
from django.urls import reverse

from content.models import Document, DocumentTranslation, PhraseTranslation

STAGES = ("رفع الملف", "التقطيع الذكي", "المطابقة والترجمة", "المراجعة", "التصدير")
SAVED_STAGE = 2  # آخر مرحلة يضمنها مجرد وجود المستند في القاعدة
SAVED_PROGRESS = 40  # نصيب المرحلتين الأوليين من المئة؛ ولكل مرحلة تالية عشرون
EXPORT_KINDS = ("docx", "pdf", "xlsx")

_Status = DocumentTranslation.Status
_STATUS_STAGE = {
    _Status.PENDING: 3,
    _Status.TRANSLATING: 3,
    _Status.REVIEW: 4,
    _Status.APPROVED: 5,
    _Status.ARCHIVED: 5,
}
_STAGE_SLUG = {3: "translation", 4: "review", 5: "export"}


def _percent(value: float) -> int:
    """تقريب إلى أقرب عدد صحيح بلا تقريب مصرفي (52.5 ← 53)."""
    return int(value + 0.5)


def _share(part: int, total: int) -> float:
    return part / total if total else 0.0


def translation_progress(status: str, translated: int, approved: int, total: int) -> int:
    """نسبة تقدّم ترجمة لغة: 40 للرفع والتقطيع، +20 بنسبة المترجَم، +20 بنسبة المعتمَد، +20 للاعتماد.

    الاعتماد النهائي («معتمدة» أو «مؤرشفة») يعني اكتمال الخط كله مهما كانت العدّادات.
    """
    if status in (_Status.APPROVED, _Status.ARCHIVED):
        return 100
    if status == _Status.REVIEW:
        return _percent(60 + 20 * _share(approved, total))
    if status == _Status.TRANSLATING:
        return _percent(SAVED_PROGRESS + 20 * _share(translated, total))
    return SAVED_PROGRESS


def _translation_row(translation, document_id: int, total: int) -> dict:
    language = translation.target_language
    iso = language.iso_code.lower()
    translated, approved = translation.translated, translation.approved
    stage = _STATUS_STAGE[translation.status]
    # لغة لم تُترجم منها جملة بعد تُفتح على وحداتها المقطّعة؛ فتح «الترجمة» بلا جمل يعيد تشغيلها
    slug = "segments" if stage == 3 and not translated else _STAGE_SLUG[stage]
    url = reverse("pages:document_stage", args=[document_id, slug])
    return {
        "id": translation.pk,
        "language": language.name,
        "name_en": language.name_en,
        "iso": iso,
        "direction": language.direction,
        "status": translation.status,
        "status_label": translation.get_status_display(),
        "stage_index": stage,
        "stage_label": STAGES[stage - 1],
        "progress": translation_progress(translation.status, translated, approved, total),
        "total": total,
        "translated": translated,
        "approved": approved,
        "updated_at": translation.updated_at.isoformat(),
        "url": f"{url}?target={iso}",
        "export_urls": {
            kind: reverse("export:download", args=[translation.pk, kind]) for kind in EXPORT_KINDS
        },
    }


def _translations_by_document() -> dict[int, list]:
    """ترجمات كل مستند بعدّادَي جملها المترجمة والمعتمدة (من القابلة للترجمة) في استعلام واحد."""
    translatable = Q(phrases__phrase__translatable=True)
    rows = (
        DocumentTranslation.objects.select_related("target_language")
        .annotate(
            translated=Count("phrases", filter=translatable & ~Q(phrases__translation="")),
            approved=Count(
                "phrases",
                filter=translatable & Q(phrases__status=PhraseTranslation.Status.APPROVED),
            ),
        )
        .order_by("target_language__name", "id")
    )
    grouped = defaultdict(list)
    for translation in rows:
        grouped[translation.document_id].append(translation)
    return grouped


def legacy_stage(translations: list) -> str:
    """مرحلة المستند بلفظها القديم: «مصنَّف» بلا ترجمة، وإلا حالة أحدث ترجمة."""
    latest = max(translations, key=lambda t: t.pk, default=None)
    return latest.get_status_display() if latest else "مصنَّف"


def document_rows() -> list[dict]:
    """صفوف لوحة المتابعة لكل المستندات، الأحدث أولاً."""
    documents = Document.objects.order_by("-id").annotate(
        phrase_total=Count("phrases", distinct=True),
        translatable_total=Count("phrases", filter=Q(phrases__translatable=True), distinct=True),
    )
    translations = _translations_by_document()
    out = []
    for document in documents:
        own = translations.get(document.pk, [])
        languages = [_translation_row(t, document.pk, document.translatable_total) for t in own]
        # مرحلة المستند هي مرحلة أبطأ لغاته الحيّة (ما لم تُؤرشف)، وتقدّمه متوسط تقدّمها
        live = [row for row in languages if row["status"] != _Status.ARCHIVED] or languages
        stage = min((row["stage_index"] for row in live), default=SAVED_STAGE)
        progress = (
            _percent(sum(row["progress"] for row in languages) / len(languages))
            if languages
            else SAVED_PROGRESS
        )
        out.append(
            {
                "id": document.pk,
                "title": document.title,
                "kind": document.kind,
                "kind_label": document.get_kind_display(),
                "source": document.source_file_name or "نص مباشر",
                "source_kind": "file" if document.source_file_name else "text",
                "phrases": document.phrase_total,
                "translatable": document.translatable_total,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat(),
                "stage": legacy_stage(own),
                "stage_index": stage,
                "stage_label": STAGES[stage - 1],
                "progress": progress,
                "translations": languages,
                "url": reverse("pages:document", args=[document.pk]),
                "json_url": reverse("classify:api", args=[document.pk]),
                "xlsx_url": reverse("classify:export", args=[document.pk]),
            }
        )
    return out


def payload() -> dict:
    """جسم ``/api/translate/documents/``: أسماء المراحل الخمس ثم صفوف المستندات."""
    return {"stages": list(STAGES), "documents": document_rows()}
