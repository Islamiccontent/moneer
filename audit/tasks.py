"""مهمة التدقيق على django.tasks: تنفيذ مهمة مُنشأة (فورياً في التطوير، وبـ db_worker في الإنتاج)."""

import logging

from django.conf import settings
from django.tasks import task

from . import pipeline
from .models import AuditJob

logger = logging.getLogger("audit.tasks")


def can_audit():
    """لا تدقيق بلا مفتاح Gemini."""
    return bool(settings.GEMINI_API_KEY)


@task
def audit_job_task(job_id):
    """ينفّذ مجموعات مهمة تدقيق «بانتظار البدء» ويعيد ملخصاً (قابل للتسلسل JSON)."""
    job = AuditJob.objects.select_related("document_translation").filter(pk=job_id).first()
    if job is None:
        logger.warning("مهمة التدقيق %s غير موجودة؛ تُتجاهل.", job_id)
        return {"job": job_id, "missing": True}
    if job.status != AuditJob.Status.PENDING:
        logger.warning("مهمة التدقيق %s ليست بانتظار البدء (%s)؛ تُتجاهل.", job_id, job.status)
        return {"job": job_id, "skipped": job.status}
    pipeline.run_job(job)
    return {
        "job": job_id,
        "status": job.status,
        "rows": job.total_rows,
        "findings": job.finding_count,
        "errors": job.error_message,
    }
