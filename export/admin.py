from django.contrib import admin

from .models import ExportFormat


@admin.register(ExportFormat)
class ExportFormatAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "is_default", "updated_at")
    list_filter = ("is_default", "language__direction")
    search_fields = ("name", "language__name", "language__name_en")
    autocomplete_fields = ("language",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("language", "name", "is_default")}),
        (
            "الخيارات",
            {
                "fields": ("options",),
                "description": "مفاتيح نموذج Format في لوحة تنسيق الكتب؛ ما لم يُذكر يأخذ "
                "افتراضي اتجاه اللغة (export/defaults.py).",
            },
        ),
        ("تواريخ", {"fields": ("created_at", "updated_at")}),
    )
    actions = ("make_default",)

    @admin.action(description="اجعله التنسيق الافتراضي للغته")
    def make_default(self, request, queryset):
        for export_format in queryset:
            export_format.is_default = True
            export_format.save()
        self.message_user(request, f"صار افتراضياً: {queryset.count()}")
