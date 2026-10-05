"""التقطيع في الخلفية على django.tasks: الطلب الطويل كان يقطعه الوكيل العكسي في الإنتاج (504)."""

import logging
from dataclasses import asdict

from django.tasks import task

from classify import pipeline, progress
from classify.models import SegmentationJob
from classify.services import moneer_ui
from classify.services.splitter import Paragraph
from content.models import Document

logger = logging.getLogger("classify.tasks")


def start(title, source_file_name, paragraphs):
    """ينشئ مهمة التقطيع ويُدرجها؛ يعيدها بحالتها بعد الإدراج (مكتملة إن كان الخلفي فورياً)."""
    job = SegmentationJob.objects.create(title=title, source_file_name=source_file_name)
    segment_document_task.enqueue(job.pk, [asdict(p) for p in paragraphs])
    job.refresh_from_db()
    return job


def result_payload(document, segments) -> dict:
    """نتيجة التقطيع بالشكل الذي تقرؤه صفحة التقطيع."""
    return {
        "doc_id": document.pk,
        "title": document.title,
        "segments": moneer_ui.to_ui_segments(segments),
        "json_url": f"/classify/documents/{document.pk}.json?download=1",
        "xlsx_url": f"/classify/documents/{document.pk}/export.xlsx",
        "result_url": f"/admin/content/document/{document.pk}/change/",
    }


def _reporter(job_id):
    """يسجل المرحلة في ذاكرة العملية (الخادم المحلي) وفي المهمة (تقرؤها الواجهة من أي عملية)."""

    def report(stage, pct):
        progress.report(stage, pct)
        SegmentationJob.objects.filter(pk=job_id).update(
            stage=str(stage)[:120], pct=max(0, min(100, int(pct)))
        )

    return report


@task
def segment_document_task(job_id, paragraphs):
    """يقطّع الفقرات ويصنّفها ويحفظ المستند، ثم يسجّل نتيجة الواجهة في المهمة."""
    job = SegmentationJob.objects.filter(pk=job_id).first()
    if job is None:
        logger.warning("مهمة التقطيع %s غير موجودة؛ تُتجاهل.", job_id)
        return {"job": job_id, "missing": True}
    SegmentationJob.objects.filter(pk=job_id).update(status=SegmentationJob.Status.RUNNING)
    report = _reporter(job_id)
    try:
        segments = pipeline.run([Paragraph(**p) for p in paragraphs], progress=report)
        report("الحفظ في القاعدة", 96)
        document, _payload = pipeline.save_document(
            pipeline.unique_title(job.title),
            Document.Kind.ARTICLE,
            job.source_file_name,
            segments,
        )
    except Exception:
        logger.exception("فشل تقطيع المهمة %s", job_id)
        SegmentationJob.objects.filter(pk=job_id).update(
            status=SegmentationJob.Status.FAILED, error="تعذّر تقطيع المستند وتصنيفه."
        )
        raise
    progress.report("اكتمل", 100)
    job.status, job.stage, job.pct = SegmentationJob.Status.DONE, "اكتمل", 100
    job.document, job.result = document, result_payload(document, segments)
    job.save(update_fields=["status", "stage", "pct", "document", "result", "updated_at"])
    return {"job": job_id, "document": document.pk}
