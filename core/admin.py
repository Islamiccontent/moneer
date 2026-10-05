from django.contrib import admin

from .models import ContentTypeLookup, Language


@admin.register(ContentTypeLookup)
class ContentTypeLookupAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "is_emitted")
    search_fields = ("name", "code")
    list_filter = ("is_emitted",)
    ordering = ("id",)


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("name", "name_en", "iso_code", "direction")
    search_fields = ("name", "name_en", "iso_code")
    list_filter = ("direction",)
    ordering = ("name",)
