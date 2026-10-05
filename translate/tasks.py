"""المهام الخلفية للترجمة على django.tasks: ترجمة مستند عند إضافة لغة، وكنس دوري لغير المكتمل."""

import logging

from django.conf import settings
from django.db import transaction
from django.tasks import task

from content.models import DocumentTranslation

from . import pipeline

logger = logging.getLogger("translate.tasks")

UNFINISHED = (DocumentTranslation.Status.PENDING, DocumentTranslation.Status.TRANSLATING)


def can_translate():
    """لا تُدرَج مهام ترجمة بلا مفتاح Gemini؛ تبقى الترجمة «بانتظار البدء» حتى يُضبط."""
    return bool(settings.GEMINI_API_KEY)


@task
def translate_document_task(document_translation_id, force=False):
    """يترجم عبارات ترجمة مستند ويعيد عدّاد الملخص (قابل للتسلسل JSON)."""
    document_translation = (
        DocumentTranslation.objects.select_related("document", "target_language")
        .filter(pk=document_translation_id)
        .first()
    )
    if document_translation is None:
        logger.warning("ترجمة المستند %s غير موجودة؛ تُتجاهل.", document_translation_id)
        return {"document_translation": document_translation_id, "missing": True}
    if not can_translate():
        logger.warning("GEMINI_API_KEY غير مضبوط؛ ترجمة المستند %s تنتظر.", document_translation_id)
        return {"document_translation": document_translation_id, "skipped": "no_api_key"}

    summary = pipeline.translate_document(document_translation, force=force)
    for phrase_id, message in summary.errors:
        logger.warning(
            "فشل %s في ترجمة المستند %s: %s", phrase_id, document_translation_id, message
        )
    return {
        "document_translation": document_translation_id,
        **summary.counts,
        "errors": len(summary.errors),
    }


@task
def translate_pending_task():
    """يُدرج مهمة لكل ترجمة مستند لم تكتمل؛ يعيد عددها."""
    ids = list(
        DocumentTranslation.objects.filter(status__in=UNFINISHED)
        .order_by("created_at")
        .values_list("pk", flat=True)
    )
    for pk in ids:
        translate_document_task.enqueue(pk)
    return {"enqueued": len(ids)}


def enqueue_translation(document_translation):
    """يعلّم الترجمة «جارية» ويُدرج مهمتها بعد commit. يعيد False إن لم يكن الإدراج ممكناً."""
    if not can_translate():
        return False
    pk = document_translation.pk

    def _enqueue():
        DocumentTranslation.objects.filter(pk=pk, status=DocumentTranslation.Status.PENDING).update(
            status=DocumentTranslation.Status.TRANSLATING
        )
        translate_document_task.enqueue(pk)

    transaction.on_commit(_enqueue)
    return True
