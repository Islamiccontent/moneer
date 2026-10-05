"""واجهة التقطيع والتصنيف البرمجية؛ /api/segment/ من الجذر لأن الحزمة المجمّعة تناديه بمسار مطلق."""

import json
from pathlib import Path
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from classify import pipeline, progress, tasks
from classify.models import SegmentationJob
from classify.services.exporter import to_xlsx
from classify.services.payload import build_payload
from classify.services.splitter import DocumentError, extract_docx, extract_text
from content.models import Document


@csrf_exempt
@require_POST
def api_segment(request):
    """ملف (file) أو نص (text) ← مهمة تقطيع في الخلفية تحفظ في content؛ بلا CSRF لأن الحزمة بلا رمز.

    القراءة تتم في الطلب (أخطاء الملف تُرد فوراً)، والتقطيع في المهمة؛ تتابعها الواجهة من /progress/.
    """
    f = request.FILES.get("file")
    text = (request.POST.get("text") or "").strip()
    title = (request.POST.get("title") or "").strip()
    progress.report("قراءة الملف", 3)
    try:
        if f:
            paragraphs = extract_docx(f)
            title = title or Path(f.name).stem
            source_file_name = f.name
        elif text:
            paragraphs = extract_text(text)
            title = title or "نص مباشر"
            source_file_name = ""
        else:
            return JsonResponse({"error": "أرسل ملفاً (file) أو نصاً (text)."}, status=400)
    except DocumentError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not paragraphs:
        return JsonResponse({"error": "لم يُعثر على نص."}, status=400)

    job = tasks.start(title, source_file_name, paragraphs)
    return JsonResponse(job.payload(), json_dumps_params={"ensure_ascii": False})


@require_safe
def api_progress(request):
    """حالة مهمة التقطيع ``?job=`` ومرحلتها، أو أحدث مرحلة في ذاكرة هذه العملية بلا ``job``."""
    if not request.GET.get("job"):
        return JsonResponse(progress.snapshot(), json_dumps_params={"ensure_ascii": False})
    try:
        job_id = int(request.GET["job"])
    except ValueError:
        return JsonResponse({"error": "job رقم."}, status=400)
    job = get_object_or_404(SegmentationJob, pk=job_id)
    return JsonResponse(job.payload(), json_dumps_params={"ensure_ascii": False})


@require_safe
def api(request, pk):
    """عقد الواجهة 2.0 لمستند محفوظ، مبنيّ من صفوف content. ‎?download=1 يحفظه ملفاً."""
    document = get_object_or_404(Document, pk=pk)
    segments = pipeline.segments_from_document(document)
    data = build_payload(
        document.title,
        segments,
        source={
            "kind": "file" if document.source_file_name else "text",
            "name": document.source_file_name,
        },
    )
    if not request.GET.get("download"):
        return JsonResponse(data, json_dumps_params={"ensure_ascii": False, "indent": 2})
    body = json.dumps(data, ensure_ascii=False, indent=2)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(document.title)}.json"
    return response


@require_safe
def export(request, pk):
    """جدول Excel بصيغة خط الإنتاج لمستند محفوظ."""
    document = get_object_or_404(Document, pk=pk)
    data = to_xlsx(document.title, pipeline.segments_from_document(document))
    response = HttpResponse(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(document.title)}.xlsx"
    return response
