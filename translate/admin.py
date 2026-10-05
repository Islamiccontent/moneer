import textwrap

from django.contrib import admin

from .models import QuranAyah, QuranAyahTranslation, QuranTranslationKey


@admin.register(QuranAyah)
class QuranAyahAdmin(admin.ModelAdmin):
    list_display = ("__str__", "surah_no", "ayah_no", "juz", "page", "short_imlaei")
    list_filter = ("juz",)
    search_fields = ("surah_name", "clean_imlaei", "clean_uthmani", "normalized_imlaei")
    ordering = ("surah_no", "ayah_no")
    readonly_fields = ("clean_uthmani", "clean_imlaei", "normalized_uthmani", "normalized_imlaei")
    fieldsets = (
        (None, {"fields": ("surah_no", "ayah_no", "surah_name", "juz", "page")}),
        ("النص", {"fields": ("text_uthmani", "text_imlaei")}),
        (
            "صور المطابقة (محسوبة)",
            {
                "classes": ("collapse",),
                "fields": (
                    "clean_uthmani",
                    "clean_imlaei",
                    "normalized_uthmani",
                    "normalized_imlaei",
                ),
            },
        ),
    )

    @admin.display(description="النص الإملائي")
    def short_imlaei(self, obj):
        return textwrap.shorten(obj.text_imlaei, width=60, placeholder="…")


@admin.register(QuranTranslationKey)
class QuranTranslationKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "key", "updated_at")
    search_fields = ("name", "key", "language__name", "language__name_en")
    autocomplete_fields = ("language",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(QuranAyahTranslation)
class QuranAyahTranslationAdmin(admin.ModelAdmin):
    list_display = ("__str__", "translation_key", "ayah", "updated_at")
    list_filter = ("translation_key",)
    search_fields = ("text", "ayah__surah_name", "ayah__clean_imlaei")
    autocomplete_fields = ("translation_key", "ayah")
    readonly_fields = ("created_at", "updated_at")
