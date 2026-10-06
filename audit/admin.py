from django.contrib import admin

from .models import AuditFinding, AuditGroup, AuditJob, AuditRow


class AuditGroupInline(admin.TabularInline):
    model = AuditGroup
    extra = 0
    can_delete = False
    fields = ("key", "status", "attempts", "last_error", "started_at", "completed_at")
    readonly_fields = fields


@admin.register(AuditJob)
class AuditJobAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "status",
        "language",
        "model",
        "total_rows",
        "eligible_rows",
        "finding_count",
        "created_at",
        "finished_at",
    )
    list_filter = ("status", "document_translation__target_language")
    search_fields = ("document_translation__document__title", "language", "model")
    autocomplete_fields = ("document_translation", "created_by")
    date_hierarchy = "created_at"
    readonly_fields = (
        "status",
        "prompt_version",
        "prompt_snapshot",
        "request_config",
        "total_rows",
        "eligible_rows",
        "finding_count",
        "prompt_tokens",
        "output_tokens",
        "progress",
        "stats",
        "error_message",
        "created_at",
        "updated_at",
        "finished_at",
    )
    inlines = (AuditGroupInline,)


class AuditFindingInline(admin.TabularInline):
    model = AuditFinding
    extra = 0
    can_delete = False
    fields = (
        "seq",
        "source",
        "type_code",
        "type_name",
        "severity",
        "sharia_sensitive",
        "detection",
        "confidence",
        "explanation",
    )
    readonly_fields = fields


@admin.register(AuditRow)
class AuditRowAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "job",
        "seq",
        "status",
        "verdict",
        "error_count",
        "max_severity",
        "needs_human_review",
    )
    list_filter = ("status", "verdict", "max_severity", "needs_human_review", "sharia_sensitive")
    search_fields = ("source_text", "target_text", "phrase__phrase_id")
    raw_id_fields = ("job", "group", "phrase")
    inlines = (AuditFindingInline,)


@admin.register(AuditFinding)
class AuditFindingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "job", "row", "category", "sharia_sensitive", "detection", "source")
    list_filter = ("severity", "category_code", "sharia_sensitive", "detection", "source")
    search_fields = ("type_code", "explanation", "row__phrase__phrase_id")
    raw_id_fields = ("job", "row")
