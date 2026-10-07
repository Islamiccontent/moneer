"""واجهة الترجمة البرمجية على مرحلتين: /api/translate/ للتصنيف، و/api/translate/run/ للترجمة."""

from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.tasks import TaskResultStatus
from django.tasks.exceptions import TaskException
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from classify import pipeline as classify_pipeline
from classify import progress
from classify.services.splitter import DocumentError, cover_title, extract_docx, extract_text
from content.models import Document, DocumentTranslation, PhraseTranslation
from core.models import Language
from translate import tasks
from translate.services import dashboard, moneer_ui, term_match

LANG_BY_LABEL = {
    "English": "en",
    "Français": "fr",
    "Bahasa Indonesia": "id",
    "Türkçe": "tr",
    "اردو": "ur",
    "Español": "es",
}


def _language_or_error(target):
    """لغة الهدف من target: رمز iso أو اسمها في قاعدتنا أو تسمية الحزمة الأصلية."""
    iso = LANG_BY_LABEL.get(target, target)
    language = (
        Language.objects.filter(iso_code__iexact=iso).first()
        or Language.objects.filter(name=target).first()
    )
    if language is None:
        return None, JsonResponse({"error": f"لغة غير معروفة: {target}"}, status=400)
    return language, None


@csrf_exempt
@require_POST
def api_translate(request):
    """المرحلة الأولى: ملف أو نص ← تصنيف وحفظ ← وحدات بلا ترجمة؛ target يُتحقق منه مبكراً."""
    target = (request.POST.get("target") or "English").strip()
    _language, error = _language_or_error(target)
    if error:
        return error

    f = request.FILES.get("file")
    text = (request.POST.get("text") or "").strip()
    title = (request.POST.get("title") or "").strip()
    progress.report("قراءة الملف", 3)
    try:
        if f:
            paragraphs = extract_docx(f)
            title = title or cover_title(paragraphs) or Path(f.name).stem
            source_name = f.name
        elif text:
            paragraphs = extract_text(text)
            title = title or "نص مباشر للترجمة"
            source_name = ""
        else:
            return JsonResponse({"error": "أرسل ملفاً (file) أو نصاً (text)."}, status=400)
    except DocumentError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not paragraphs:
        return JsonResponse({"error": "لم يُعثر على نص."}, status=400)

    segments = classify_pipeline.run(paragraphs, progress=progress.report)
    progress.report("الحفظ في القاعدة", 96)
    document, _payload = classify_pipeline.save_document(
        classify_pipeline.unique_title(title), Document.Kind.ARTICLE, source_name, segments
    )
    progress.report("اكتمل", 100)
    return JsonResponse(
        {
            "doc_id": document.pk,
            "title": document.title,
            "segments": moneer_ui.to_ui_segments(document),
        }
    )


@csrf_exempt
@require_POST
def api_translate_run(request):
    """المرحلة الثانية: ``doc_id`` + ``target`` ← مهمة ترجمة في الخلفية؛ تقدّمها من /progress/.

    لا تُترجم الجمل داخل الطلب: طلب طويل يقطعه الوكيل العكسي في الإنتاج (504) والترجمة جارية.
    """
    target = (request.POST.get("target") or "English").strip()
    language, error = _language_or_error(target)
    if error:
        return error
    document = get_object_or_404(Document, pk=request.POST.get("doc_id"))
    if not tasks.can_translate():
        return JsonResponse({"error": "الترجمة غير متاحة: مفتاح Gemini غير مضبوط."}, status=503)
    if document.translations.filter(target_language=language).exists():
        return JsonResponse({"error": "للمستند ترجمة بهذه اللغة من قبل."}, status=409)

    translation = DocumentTranslation.objects.create(
        document=document,
        target_language=language,
        status=DocumentTranslation.Status.TRANSLATING,
    )
    result = tasks.translate_document_task.enqueue(translation.pk)
    return JsonResponse(
        {
            "doc_id": document.pk,
            "translation_id": translation.pk,
            "task_id": result.id,
            "finished": result.is_finished,
        }
    )


def _task_state(task_id, translation):
    """(انتهت؟، ثواني انتظارها قبل أن يلتقطها عامل الخلفية) من نتيجة المهمة إن أمكن جلبها."""
    if task_id:
        try:
            result = tasks.translate_document_task.get_result(task_id)
        except (NotImplementedError, TaskException):
            pass
        else:
            queued_for = 0
            if result.status == TaskResultStatus.READY and result.enqueued_at:
                queued_for = int((timezone.now() - result.enqueued_at).total_seconds())
            return result.is_finished, queued_for
    return translation.status not in tasks.UNFINISHED, 0


@require_safe
def api_translate_progress(request):
    """تقدّم المرحلة الجارية: بلا ``doc_id`` مرحلة التصنيف، ومعه ترجمة المستند من القاعدة.

    ``after``: أحدث ترجمة يعرفها المتصفح قبل الطلب؛ تُتابَع ترجمة أحدث منها فقط.
    """
    if not request.GET.get("doc_id"):
        return JsonResponse(progress.snapshot())
    try:
        doc_id, after = int(request.GET["doc_id"]), int(request.GET.get("after") or 0)
    except ValueError:
        return JsonResponse({"error": "doc_id وafter أرقام."}, status=400)
    translation = (
        DocumentTranslation.objects.select_related("document", "target_language")
        .filter(document_id=doc_id, pk__gt=after)
        .order_by("-id")
        .first()
    )
    if translation is None:
        return JsonResponse({"stage": "بدء الترجمة", "pct": 1, "waiting": True, "finished": False})
    state = moneer_ui.translation_progress(translation)
    done, total = state["done"], state["total"]
    finished, queued_for = _task_state(request.GET.get("task_id"), translation)
    return JsonResponse(
        {
            **state,
            "stage": f"الترجمة ({done}/{total})",
            "pct": 2 + round(done / max(total, 1) * 94),
            "finished": finished,
            "queued_for": queued_for,
        }
    )


@require_safe
def api_languages(request):
    """اللغات التي لها ترجمات قرآن معتمدة بأسمائها في قاعدتنا؛ تغذي منتقي اللغة في الواجهة."""
    rows = [
        {"name": lang.name, "iso": lang.iso_code.lower()}
        for lang in Language.objects.filter(quran_translation_key__isnull=False).order_by("name")
    ]
    return JsonResponse({"languages": rows})


def _stage_of(document) -> str:
    """مرحلة المستند للعرض: «مصنَّف» إن لم تُطلب ترجمة، وإلا حالة أحدث ترجمة."""
    latest = document.translations.order_by("-id").first()
    return latest.get_status_display() if latest else "مصنَّف"


@require_safe
def api_documents(request):
    """قائمة المحتوى المحفوظ بمراحله ونسب تقدّمه لكل لغة — تغذي لوحة ``/translate/documents/``."""
    return JsonResponse(dashboard.payload(), json_dumps_params={"ensure_ascii": False})


@require_safe
def api_document(request, pk):
    """حالة مستند واحد بشكل الواجهة: وحداته وترجمته؛ ``?target=<iso>`` يختار لغة، وإلا الأحدث."""
    document = get_object_or_404(Document, pk=pk)
    translations = document.translations.select_related("target_language").order_by("-id")
    target = (request.GET.get("target") or "").strip()
    latest = (
        translations.filter(target_language__iso_code__iexact=target).first() if target else None
    ) or translations.first()
    segments = moneer_ui.to_ui_segments(document, latest)
    if latest and latest.target_language.iso_code.lower() != "en":
        term_match.localize_terms(segments, latest.target_language)
    term_match.prune_unmatched(segments)
    moneer_ui.mark_approved_terms(segments)
    return JsonResponse(
        {
            "doc_id": document.pk,
            "title": document.title,
            "source_file_name": document.source_file_name,
            "stage": _stage_of(document),
            "target_language": latest.target_language.name if latest else "",
            "target_iso": latest.target_language.iso_code.lower() if latest else "",
            "translation_id": latest.pk if latest else None,
            "segments": segments,
        }
    )


@csrf_exempt
@require_POST
def api_translate_approve(request):
    """اعتماد ترجمة جملة بنص المراجع أو إلغاؤه؛ ما لا يُترجم يُعتمد بنصه الأصلي إن لم يُكتب له نص."""
    translation = get_object_or_404(DocumentTranslation, pk=request.POST.get("translation_id"))
    phrase = get_object_or_404(translation.document.phrases, pk=request.POST.get("phrase_id"))
    row = PhraseTranslation.objects.filter(document_translation=translation, phrase=phrase).first()
    user = request.user if request.user.is_authenticated else None

    if request.POST.get("approved") != "1":
        if row and not phrase.translatable:
            row.delete()
            row = None
        elif row and row.status == PhraseTranslation.Status.APPROVED:
            row.status = PhraseTranslation.Status.SUGGESTED
            row.approved_by, row.approved_at = None, None
            row.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return JsonResponse({"phrase_id": phrase.pk, "approved": False})

    text = (request.POST.get("text") or "").strip() or ("" if phrase.translatable else phrase.text)
    if not text:
        return JsonResponse({"error": "لا تُعتمد ترجمة فارغة."}, status=400)
    row = row or PhraseTranslation(document_translation=translation, phrase=phrase)
    if text != row.translation:
        row.translation, row.edited_by = text, user
    row.status = PhraseTranslation.Status.APPROVED
    row.approved_by, row.approved_at = user, timezone.now()
    row.save()
    return JsonResponse({"phrase_id": phrase.pk, "approved": True, "translation": text})
