from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Document,
    DocumentTranslation,
    Glossary,
    GlossaryTranslation,
    Phrase,
    PhraseAnalysis,
    PhraseTerm,
    PhraseTranslation,
)


class PhraseInline(admin.TabularInline):
    model = Phrase
    fields = ("group_id", "group_order", "content_type", "text")
    ordering = ("group_id", "group_order")
    extra = 0
    show_change_link = True


class DocumentTranslationInline(admin.TabularInline):
    """ترجمات المستند إلى لغاته الهدف، من داخل صفحة المستند."""

    model = DocumentTranslation
    fields = ("target_language", "status", "ai_model", "reviewer")
    autocomplete_fields = ("target_language", "reviewer")
    extra = 0
    show_change_link = True


class PhraseAnalysisInline(admin.StackedInline):
    model = PhraseAnalysis
    extra = 0


class PhraseTermInline(admin.TabularInline):
    model = PhraseTerm
    autocomplete_fields = ("glossary",)
    extra = 0


class PhraseTranslationInline(admin.TabularInline):
    """ترجمات الجمل بترتيب موضعها في المستند، من داخل صفحة ترجمة المستند."""

    model = PhraseTranslation
    fields = ("phrase", "status", "ai_translation", "translation", "approved_by")
    autocomplete_fields = ("phrase", "approved_by")
    ordering = ("phrase__group_id", "phrase__group_order")
    extra = 0
    show_change_link = True


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "created_by", "created_at")
    list_filter = ("kind",)
    search_fields = ("title", "source_file_name")
    autocomplete_fields = ("created_by",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    inlines = (PhraseInline, DocumentTranslationInline)


@admin.register(Phrase)
class PhraseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "document", "content_type", "group_id", "group_order")
    list_filter = ("content_type", "tag")
    search_fields = ("text", "phrase_id")
    autocomplete_fields = ("document",)
    readonly_fields = ("phrase_id", "created_at", "updated_at")
    inlines = (PhraseAnalysisInline, PhraseTermInline)


class GlossaryTranslationInline(admin.TabularInline):
    """ترجمات المدخل بكل اللغات، من داخل صفحته."""

    model = GlossaryTranslation
    fields = ("language", "title", "short_def")
    autocomplete_fields = ("language",)
    extra = 0
    show_change_link = True


@admin.register(Glossary)
class GlossaryAdmin(admin.ModelAdmin):
    list_display = ("ar", "en", "category", "agreement_count", "agreement_total", "strong")
    list_filter = ("category", "strong")
    search_fields = ("ar", "en")
    ordering = ("ar",)
    inlines = (GlossaryTranslationInline,)


@admin.register(GlossaryTranslation)
class GlossaryTranslationAdmin(admin.ModelAdmin):
    list_display = ("glossary", "language", "title", "updated_at")
    list_filter = ("language",)
    search_fields = ("glossary__ar", "title")
    autocomplete_fields = ("glossary", "language")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DocumentTranslation)
class DocumentTranslationAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "target_language",
        "status",
        "ai_model",
        "reviewer",
        "approved_at",
        "created_at",
        "export_links",
    )
    list_filter = ("status", "target_language")
    search_fields = ("document__title", "target_language__name", "target_language__name_en")
    autocomplete_fields = ("document", "target_language", "reviewer", "approved_by", "created_by")
    date_hierarchy = "created_at"
    readonly_fields = ("export_links", "created_at", "updated_at")
    inlines = (PhraseTranslationInline,)

    @admin.display(description="تصدير")
    def export_links(self, obj):
        """تنزيل آني من تطبيق export بتنسيق اللغة الافتراضي."""
        if obj.pk is None:
            return "—"
        return format_html(
            '<a href="{}">DOCX</a> · <a href="{}">PDF</a>',
            reverse("export:download", args=[obj.pk, "docx"]),
            reverse("export:download", args=[obj.pk, "pdf"]),
        )


@admin.register(PhraseTranslation)
class PhraseTranslationAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "document_translation",
        "phrase",
        "status",
        "approved_by",
        "updated_at",
    )
    list_filter = ("status", "document_translation__target_language")
    search_fields = ("translation", "ai_translation", "phrase__text", "phrase__phrase_id")
    autocomplete_fields = ("document_translation", "phrase", "edited_by", "approved_by")
    readonly_fields = ("created_at", "updated_at")
