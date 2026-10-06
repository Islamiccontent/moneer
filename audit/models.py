"""مخرجات التدقيق: مهمة لكل تشغيل على ترجمة مستند، ومجموعات الطلبات، وصف لكل جملة، وملاحظة لكل خطأ.

المبدأ (كما في منصة تدقيق): «الحقيقة» القابلة للاستعلام تُحفظ صفاً لكل جملة وملاحظةً لكل
خطأ مصنَّف، مع لقطة البرومت وإعدادات الطلب والإحصائيات على مستوى المهمة.
"""

from django.conf import settings
from django.db import models

from .services.taxonomy import DETECTIONS, SEVERITIES, VERDICTS


class AuditJob(models.Model):
    """تشغيل واحد لأداة التدقيق على ترجمة مستند بلغة هدف واحدة."""

    class Status(models.TextChoices):
        PENDING = "pending", "بانتظار البدء"
        RUNNING = "running", "قيد التدقيق"
        DONE = "done", "مكتمل"
        PARTIAL = "partial", "مكتمل جزئياً"
        FAILED = "failed", "فشل"

    document_translation = models.ForeignKey(
        "content.DocumentTranslation",
        verbose_name="ترجمة المستند",
        on_delete=models.CASCADE,
        related_name="audits",
    )
    status = models.CharField("الحالة", max_length=10, choices=Status, default=Status.PENDING)
    language = models.CharField("اللغة كما تُذكر في البرومت", max_length=100)
    arabic_script = models.BooleanField("تُكتب بالحرف العربي", default=False)
    model = models.CharField("نموذج Gemini", max_length=100)
    group_size = models.PositiveSmallIntegerField("صفوف لكل طلب")
    prompt_version = models.PositiveSmallIntegerField("نسخة البرومت")
    prompt_snapshot = models.TextField("لقطة البرومت")
    request_config = models.JSONField("إعدادات الطلب", default=dict, blank=True)
    extra_rules = models.TextField("قواعد إضافية", blank=True)
    total_rows = models.PositiveIntegerField("إجمالي الصفوف", default=0)
    eligible_rows = models.PositiveIntegerField("الصفوف المؤهلة للنموذج", default=0)
    finding_count = models.PositiveIntegerField("عدد الملاحظات", default=0)
    prompt_tokens = models.PositiveIntegerField("توكن الإدخال", default=0)
    output_tokens = models.PositiveIntegerField("توكن الإخراج", default=0)
    progress = models.JSONField("التقدّم", default=dict, blank=True)
    stats = models.JSONField("الإحصائيات", default=dict, blank=True)
    error_message = models.TextField("رسالة الخطأ", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="طلبه",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_jobs",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)
    finished_at = models.DateTimeField("تاريخ الانتهاء", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "مهمة تدقيق"
        verbose_name_plural = "مهام التدقيق"

    def __str__(self):
        return f"تدقيق #{self.pk}: {self.document_translation}"

    @property
    def is_finished(self):
        return self.status in (self.Status.DONE, self.Status.PARTIAL, self.Status.FAILED)


class AuditGroup(models.Model):
    """مجموعة صفوف = طلب واحد للنموذج؛ تُعاد عند الفشل حتى حدّ المحاولات."""

    class Status(models.TextChoices):
        PENDING = "pending", "معلّقة"
        DONE = "done", "منجزة"
        FAILED = "failed", "فاشلة"

    job = models.ForeignKey(
        AuditJob, verbose_name="المهمة", on_delete=models.CASCADE, related_name="groups"
    )
    key = models.CharField("المفتاح", max_length=50)
    status = models.CharField("الحالة", max_length=10, choices=Status, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField("المحاولات", default=0)
    last_error = models.TextField("آخر خطأ", blank=True)
    raw_response = models.TextField("الرد الخام", blank=True)
    started_at = models.DateTimeField("بدء آخر محاولة", null=True, blank=True)
    completed_at = models.DateTimeField("تاريخ الإنجاز", null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["job", "key"], name="unique_audit_group_key_per_job")
        ]
        verbose_name = "مجموعة تدقيق"
        verbose_name_plural = "مجموعات التدقيق"

    def __str__(self):
        return self.key


class AuditRow(models.Model):
    """صف واحد (جملة) في مهمة تدقيق مع حكمه النهائي."""

    class Status(models.TextChoices):
        PENDING = "pending", "لم يُفحص بعد"
        DONE = "done", "تم"
        FAILED = "failed", "فشل الفحص"
        SKIPPED = "skipped", "مستبعد"

    class RowType(models.TextChoices):
        TRANSLATION = "translation", "ترجمة معنى"
        NAQHARA = "naqhara", "نقحرة"

    job = models.ForeignKey(
        AuditJob, verbose_name="المهمة", on_delete=models.CASCADE, related_name="rows"
    )
    group = models.ForeignKey(
        AuditGroup,
        verbose_name="المجموعة",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rows",
    )
    seq = models.PositiveIntegerField("الترتيب (id في البرومت)")
    phrase = models.ForeignKey(
        "content.Phrase",
        verbose_name="الجملة",
        on_delete=models.CASCADE,
        related_name="audit_rows",
    )
    source_text = models.TextField("النص الأصلي")
    target_text = models.TextField("الترجمة", blank=True)
    row_type = models.CharField(
        "نوع الصف", max_length=12, choices=RowType, default=RowType.TRANSLATION
    )
    hints = models.JSONField("تنبيهات آلية", default=list, blank=True)
    status = models.CharField("حالة الفحص", max_length=10, choices=Status, default=Status.PENDING)
    skip_reason = models.CharField("سبب الاستبعاد", max_length=255, blank=True)
    verdict = models.CharField(
        "الحكم", max_length=30, blank=True, choices=[(v, v) for v in VERDICTS]
    )
    summary = models.TextField("ملخص المراجعة", blank=True)
    error_count = models.PositiveSmallIntegerField("عدد الأخطاء", default=0)
    max_severity = models.CharField(
        "أعلى خطورة", max_length=20, blank=True, choices=[(s, s) for s in SEVERITIES]
    )
    sharia_sensitive = models.BooleanField("حساسية شرعية", default=False)
    needs_human_review = models.BooleanField("يحتاج مراجعة بشرية", default=False)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["job", "seq"], name="unique_audit_row_seq_per_job"),
            models.UniqueConstraint(
                fields=["job", "phrase"], name="unique_audit_row_phrase_per_job"
            ),
        ]
        verbose_name = "صف تدقيق"
        verbose_name_plural = "صفوف التدقيق"

    def __str__(self):
        return f"{self.job_id}/{self.seq}"


class AuditFinding(models.Model):
    """ملاحظة مصنَّفة واحدة على صف: من قاعدة محلية قطعية أو من النموذج."""

    class Source(models.TextChoices):
        RULE = "rule", "قاعدة آلية"
        MODEL = "model", "النموذج"

    job = models.ForeignKey(
        AuditJob, verbose_name="المهمة", on_delete=models.CASCADE, related_name="findings"
    )
    row = models.ForeignKey(
        AuditRow, verbose_name="الصف", on_delete=models.CASCADE, related_name="findings"
    )
    seq = models.PositiveSmallIntegerField("الترتيب", default=1)
    source = models.CharField("مصدر الكشف", max_length=10, choices=Source, default=Source.MODEL)
    category_code = models.CharField("رمز الفئة", max_length=10, blank=True)
    category = models.CharField("الفئة", max_length=100, blank=True)
    type_code = models.CharField("رمز النوع", max_length=20, blank=True, db_index=True)
    type_name = models.CharField("نوع الخطأ", max_length=150, blank=True)
    severity = models.CharField(
        "الخطورة",
        max_length=20,
        blank=True,
        choices=[(s, s) for s in SEVERITIES],
        db_index=True,
    )
    sharia_sensitive = models.BooleanField("حساسية شرعية", default=False)
    detection = models.CharField(
        "طريقة الكشف", max_length=30, blank=True, choices=[(d, d) for d in DETECTIONS]
    )
    confidence = models.PositiveSmallIntegerField("الثقة %", null=True, blank=True)
    location = models.TextField("موضع الخطأ", blank=True)
    explanation = models.TextField("شرح المشكلة", blank=True)
    required_action = models.TextField("المطلوب", blank=True)
    suggested_fix = models.TextField("التصحيح المقترح", blank=True)
    needs_human_review = models.BooleanField("يحتاج مراجعة بشرية", default=False)

    class Meta:
        ordering = ["row__seq", "seq"]
        verbose_name = "ملاحظة تدقيق"
        verbose_name_plural = "ملاحظات التدقيق"

    def __str__(self):
        return f"{self.type_code} ({self.severity})"
