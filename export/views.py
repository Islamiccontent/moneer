"""تنزيل آني لملف الترجمة من /export/<id>/<docx|pdf|xlsx>/؛ ?format=<id> و?layout=<تخطيط>."""

import io

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404

from content.models import DocumentTranslation

from .models import ExportFormat
from .services.export import CONTENT_TYPES, KINDS, ExportError, export_translation


def download(request, pk, kind):
    if kind not in KINDS:
        raise Http404("نوع ملف غير مدعوم.")
    document_translation = get_object_or_404(
        DocumentTranslation.objects.select_related("document", "target_language"), pk=pk
    )
    export_format = None
    format_id = request.GET.get("format", "")
    if format_id:
        if not format_id.isdigit():
            raise Http404("معرّف تنسيق غير صالح.")
        export_format = get_object_or_404(
            ExportFormat, pk=int(format_id), language=document_translation.target_language
        )
    try:
        result = export_translation(
            document_translation,
            export_format=export_format,
            kind=kind,
            layout=request.GET.get("layout") or None,
        )
    except ExportError as exc:
        return HttpResponse(str(exc), status=400, content_type="text/plain; charset=utf-8")
    return FileResponse(
        io.BytesIO(result.content),
        as_attachment=True,
        filename=result.file_name,
        content_type=CONTENT_TYPES[kind],
    )
