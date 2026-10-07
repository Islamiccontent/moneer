"""واجهة التقطيع والتصنيف البرمجية؛ /api/segment/ من الجذر لأن الحزمة المجمّعة تناديه بمسار مطلق."""

import json
from pathlib import Path
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from classify import pipeline, progress
from classify.services import moneer_ui
from classify.services.exporter import to_xlsx
from classify.services.payload import build_payload
from classify.services.splitter import DocumentError, cover_title, extract_docx, extract_text
from content.models import Document


@csrf_exempt
@require_POST
def api_segment(request):
    """ملف (file) أو نص (text) ← تصنيف وحفظ في content؛ معفاة من CSRF لأن الحزمة بلا رمز."""
    f = request.FILES.get("file")
    text = (request.POST.get("text") or "").strip()
    title = (request.POST.get("title") or "").strip()
    progress.report("قراءة الملف", 3)
    try:
        if f:
            paragraphs = extract_docx(f)
            title = title or cover_title(paragraphs) or Path(f.name).stem
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

    segments = pipeline.run(paragraphs, progress=progress.report)
    progress.report("الحفظ في القاعدة", 96)
    document, _payload = pipeline.save_document(
        pipeline.unique_title(title), Document.Kind.ARTICLE, source_file_name, segments
    )
    progress.report("اكتمل", 100)
    return JsonResponse(
        {
            "doc_id": document.pk,
            "title": document.title,
            "segments": moneer_ui.to_ui_segments(segments),
            "json_url": f"/classify/documents/{document.pk}.json?download=1",
            "xlsx_url": f"/classify/documents/{document.pk}/export.xlsx",
            "result_url": f"/admin/content/document/{document.pk}/change/",
        },
        json_dumps_params={"ensure_ascii": False},
    )


@require_safe
def api_progress(request):
    """أحدث مرحلة جارية ونسبتها — يسألها شريط الواجهة أثناء المعالجة."""
    return JsonResponse(progress.snapshot(), json_dumps_params={"ensure_ascii": False})


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
