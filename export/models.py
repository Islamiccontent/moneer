"""تنسيقات التصدير: ExportFormat لكل لغة هدف بخيارات JSON وافتراضي واحد؛ التصدير آني بلا تخزين."""

from django.core.exceptions import ValidationError
from django.db import models, transaction

from .defaults import defaults_for, validate_options


class ExportFormat(models.Model):
    """تنسيق تصدير للغة هدف؛ خياراته تُدمج فوق افتراضيات اتجاه اللغة."""

    language = models.ForeignKey(
        "core.Language",
        verbose_name="اللغة",
        on_delete=models.PROTECT,
        related_name="export_formats",
    )
    name = models.CharField("اسم التنسيق", max_length=100)
    is_default = models.BooleanField("الافتراضي للغة", default=False)
    # مفاتيح نموذج Format في لوحة تنسيق الكتب؛ ما لم يُذكر يأخذ افتراضي اتجاه اللغة
    options = models.JSONField("الخيارات", default=dict, blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["language__name", "-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["language", "name"], name="unique_export_format_name_per_language"
            ),
            models.UniqueConstraint(
                fields=["language"],
                condition=models.Q(is_default=True),
                name="unique_default_export_format_per_language",
            ),
        ]
        verbose_name = "تنسيق تصدير"
        verbose_name_plural = "تنسيقات التصدير"

    def __str__(self):
        return f"{self.name} ({self.language})"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        with transaction.atomic():
            siblings = ExportFormat.objects.filter(language=self.language).exclude(pk=self.pk)
            if self.is_default:
                siblings.filter(is_default=True).update(is_default=False)
            elif not siblings.exists():
                self.is_default = True  # أول تنسيق للغة يصبح افتراضيها تلقائياً
            super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        errors = validate_options(self.options)
        if errors:
            raise ValidationError({"options": errors})

    def preferences(self):
        """الخيارات الفعلية: افتراضيات اتجاه اللغة مع ما ضُبط هنا فوقها."""
        return {**defaults_for(self.language.direction), **(self.options or {})}
