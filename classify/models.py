"""مهام التقطيع في الخلفية: حالة كل مهمة ومرحلتها لشريط الواجهة، والمستند ونتيجته عند الاكتمال."""

from django.db import models


class SegmentationJob(models.Model):
    """تقطيع مستند وتصنيفه في الخلفية؛ تقرؤه الواجهة من /api/segment/progress/?job=."""

    class Status(models.TextChoices):
        QUEUED = "queued", "في الانتظار"
        RUNNING = "running", "جارٍ"
        DONE = "done", "اكتمل"
        FAILED = "failed", "فشل"

    status = models.CharField("الحالة", max_length=8, choices=Status, default=Status.QUEUED)
    stage = models.CharField("المرحلة الجارية", max_length=120, blank=True)
    pct = models.PositiveSmallIntegerField("النسبة", default=0)
    title = models.CharField("العنوان المطلوب", max_length=255)
    source_file_name = models.CharField("اسم الملف الأصلي", max_length=255, blank=True)
    document = models.ForeignKey(
        "content.Document",
        verbose_name="المستند",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    result = models.JSONField("نتيجة الواجهة", null=True, blank=True)
    error = models.TextField("الخطأ", blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تحديث", auto_now=True)

    class Meta:
        verbose_name = "مهمة تقطيع"
        verbose_name_plural = "مهام التقطيع"

    def __str__(self):
        return f"{self.title} — {self.get_status_display()}"

    def payload(self) -> dict:
        """حالة المهمة للواجهة؛ عند الاكتمال تُلحق نتيجتها بالشكل الذي كانت تعيده /api/segment/."""
        out = {"job_id": self.pk, "status": self.status, "stage": self.stage, "pct": self.pct}
        if self.status == self.Status.DONE:
            out.update(self.result or {})
        elif self.status == self.Status.FAILED:
            out["error"] = self.error
        return out
