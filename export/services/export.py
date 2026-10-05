"""تصدير آني لترجمة مستند: اختيار التنسيق وبناء الصفوف وتوليد الملف في الذاكرة بلا تخزين."""

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.utils import timezone

from export.models import ExportFormat

from .docx_builder import TranslationDocxBuilder
from .rows import build_rows
from .xlsx_builder import build_xlsx

KINDS = ("docx", "pdf", "xlsx")
CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# تخطيط ملف Word من واجهة التصدير: يُطبَّق فوق خيارات تنسيق اللغة
LAYOUTS = {
    "translation": {
        "exclude_arabic_aya": True,
        "include_arabic_hadith": False,
        "include_arabic_naqhara": False,
        "include_arabic_paragraph": False,
    },
    "sequential": {
        "exclude_arabic_aya": False,
        "split_arabic_aya": True,
        "include_arabic_hadith": True,
        "split_arabic_hadith": True,
        "include_arabic_naqhara": True,
        "include_arabic_paragraph": True,
    },
}


class ExportError(Exception):
    """تعذّر التصدير: نوع ملف غير مدعوم أو لا تنسيق للغة."""


@dataclass
class ExportResult:
    """الملف المولَّد وبياناته."""

    content: bytes
    file_name: str
    kind: str
    rows: int  # الجمل المصدَّرة
    missing: int  # جمل قابلة للترجمة بلا ترجمة فأُسقطت
    stats: dict = field(default_factory=dict)  # إحصاء الحواشي من المولّد


def default_format_for(language):
    return ExportFormat.objects.filter(language=language, is_default=True).first()


def file_name(document_translation, kind):
    language = document_translation.target_language
    title = re.sub(r"[\\/:*?\"<>|]+", " ", document_translation.document.title).strip()
    return f"{title} - {language.name} [{language.iso_code}{document_translation.pk}].{kind}"


def book_tag(document_translation, prefs):
    language = document_translation.target_language
    tag = f"{language.iso_code}{document_translation.pk}"
    if prefs["include_date_first_page"]:
        tag += f" - {timezone.localdate():%d/%m/%Y}"
    return tag


def export_translation(document_translation, *, export_format=None, kind="docx", layout=None):
    """يولّد ملف الترجمة ويعيده ``ExportResult``؛ التنسيق الافتراضي للغة إن لم يُمرَّر تنسيق.

    ``xlsx`` جدول مراجعة لا يحتاج تنسيق تصدير؛ ``docx`` و``pdf`` كتاب بتنسيق اللغة، و``layout``
    (من ``LAYOUTS``) يحدد ظهور النص العربي فوق خيارات التنسيق.
    """
    if kind not in KINDS:
        raise ExportError(f"نوع ملف غير مدعوم: {kind}")
    if layout is not None and layout not in LAYOUTS:
        raise ExportError(f"تخطيط غير مدعوم: {layout}")
    if kind == "xlsx":
        content, rows, missing = build_xlsx(document_translation)
        return ExportResult(
            content=content,
            file_name=file_name(document_translation, kind),
            kind=kind,
            rows=rows,
            missing=missing,
        )
    language = document_translation.target_language
    export_format = export_format or default_format_for(language)
    if export_format is None:
        raise ExportError(
            f"لا تنسيق تصدير افتراضي للغة {language}؛ أنشئ واحداً أو شغّل ensure_default_formats."
        )
    prefs = {**export_format.preferences(), **LAYOUTS.get(layout, {})}
    rows, missing = build_rows(
        document_translation, include_untranslatable=prefs["include_untranslatable"]
    )
    builder = TranslationDocxBuilder(
        rows,
        arabic_title=document_translation.document.title,
        prefs=prefs,
        book_tag=book_tag(document_translation, prefs),
    )
    builder.build()
    with tempfile.TemporaryDirectory() as tmp:
        content = builder.save(Path(tmp) / f"export.{kind}", kind).read_bytes()
    return ExportResult(
        content=content,
        file_name=file_name(document_translation, kind),
        kind=kind,
        rows=len(rows),
        missing=len(missing),
        stats=builder.stats,
    )
