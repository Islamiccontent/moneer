"""واجهة التدقيق البرمجية: طلب تدقيق ترجمة مستند، وقراءة نتائجه، وتنزيلها ملف Excel.

صفحة المراجعة ستطلب التدقيق وتعرض نتائجه من هذه المسارات لاحقاً؛ لا تعديل عليها هنا.
"""

import io

from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from content.models import DocumentTranslation

from . import pipeline, tasks
from .models import AuditJob

ACTIVE = (AuditJob.Status.PENDING, AuditJob.Status.RUNNING)
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FINDING_FIELDS = (
    "seq",
    "source",
    "category_code",
    "category",
    "type_code",
    "type_name",
    "severity",
    "sharia_sensitive",
    "detection",
    "confidence",
    "location",
    "explanation",
    "required_action",
    "suggested_fix",
    "needs_human_review",
)
ROW_FIELDS = (
    "seq",
    "phrase_id",
    "source_text",
    "target_text",
    "row_type",
    "status",
    "skip_reason",
    "verdict",
    "summary",
    "error_count",
    "max_severity",
    "sharia_sensitive",
    "needs_human_review",
    "hints",
)


def row_payload(row):
    return {
        **{name: getattr(row, name) for name in ROW_FIELDS},
        "status_label": row.get_status_display(),
        "findings": [
            {name: getattr(f, name) for name in FINDING_FIELDS}
            for f in row.findings.all()  # مرتبة بـ seq عبر Meta.ordering
        ],
    }


def job_payload(job, *, with_rows=True):
    """تمثيل مهمة التدقيق للواجهة: الحالة والعدّادات والتقدّم الحي والإحصائيات، وصفوفها بملاحظاتها."""
    data = {
        "job_id": job.pk,
        "translation_id": job.document_translation_id,
        "status": job.status,
        "status_label": job.get_status_display(),
        "finished": job.is_finished,
        "language": job.language,
        "model": job.model,
        "group_size": job.group_size,
        "prompt_version": job.prompt_version,
        "counts": {
            "rows": job.total_rows,
            "eligible": job.eligible_rows,
            "findings": job.finding_count,
        },
        "progress": {
            "groups": pipeline.group_status_counts(job),
            "rows": pipeline.row_status_counts(job),
        },
        "tokens": {"prompt": job.prompt_tokens, "output": job.output_tokens},
        "stats": job.stats,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "xlsx_url": reverse("audit:xlsx", args=[job.pk]),
    }
    if with_rows:
        data["rows"] = [row_payload(r) for r in job.rows.prefetch_related("findings")]
    return data


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def api_audit_run(request):
    """``translation_id`` (+ ``extra_rules`` اختياري) ← مهمة تدقيق جديدة تُنفَّذ على django.tasks.

    التدقيق فوري (نداءات Gemini مباشرة لا Batch)؛ مع الـ backend الفوري ينتهي داخل الطلب نفسه،
    ومع db_worker يُتابَع من ``/api/audit/jobs/<id>/``.
    """
    translation = get_object_or_404(
        DocumentTranslation.objects.select_related("document", "target_language"),
        pk=request.POST.get("translation_id"),
    )
    if not tasks.can_audit():
        return _json({"error": "التدقيق غير متاح: مفتاح Gemini غير مضبوط."}, status=503)
    if translation.audits.filter(status__in=ACTIVE).exists():
        return _json({"error": "لهذه الترجمة تدقيق جارٍ الآن."}, status=409)
    user = request.user if request.user.is_authenticated else None
    try:
        job = pipeline.create_job(
            translation,
            created_by=user,
            extra_rules=(request.POST.get("extra_rules") or "").strip(),
        )
    except pipeline.AuditError as exc:
        return _json({"error": str(exc)}, status=400)
    result = tasks.audit_job_task.enqueue(job.pk)
    job.refresh_from_db()
    return _json(
        {
            "job_id": job.pk,
            "translation_id": translation.pk,
            "status": job.status,
            "task_id": result.id,
            "finished": result.is_finished,
        }
    )


@require_safe
def api_audit_job(request, pk):
    """مهمة تدقيق بصفوفها وملاحظاتها؛ ``?rows=0`` يعيد الحالة والعدّادات فقط (لاستطلاع التقدّم)."""
    job = get_object_or_404(AuditJob.objects.select_related("document_translation"), pk=pk)
    return _json({"job": job_payload(job, with_rows=request.GET.get("rows") != "0")})


@require_safe
def api_audit_latest(request, pk):
    """أحدث تدقيق لترجمة مستند (أو ``null`` إن لم تُدقَّق بعد)؛ ``?rows=0`` كما في السابق."""
    translation = get_object_or_404(DocumentTranslation, pk=pk)
    job = translation.audits.order_by("-id").first()
    payload = job_payload(job, with_rows=request.GET.get("rows") != "0") if job else None
    return _json({"translation_id": translation.pk, "job": payload})


@require_safe
def api_audit_xlsx(request, pk):
    """ملف Excel للنتائج بأوراقه الأربع، يُولَّد آنياً بلا تخزين."""
    job = get_object_or_404(
        AuditJob.objects.select_related("document_translation__document"), pk=pk
    )
    name = f"{job.document_translation.document.title} - {job.language} - تدقيق-{job.pk}"
    filename = "".join(ch for ch in name if ch not in '\\/:*?"<>|') + ".xlsx"
    return FileResponse(
        io.BytesIO(pipeline.export_xlsx(job)),
        as_attachment=True,
        filename=filename,
        content_type=XLSX_TYPE,
    )
