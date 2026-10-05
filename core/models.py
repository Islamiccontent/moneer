"""البيانات المرجعية المشتركة بين تطبيقات المشروع."""

from django.db import models


class ContentTypeLookup(models.Model):
    """نوع المحتوى الإنتاجي (آية، حديث، أثر، نص، …)؛ طبقة مستقلة عن صنف التحليل."""

    id = models.PositiveSmallIntegerField("المعرّف", primary_key=True)
    code = models.CharField("الرمز", max_length=30, unique=True)
    name = models.CharField("الاسم", max_length=100)
    is_emitted = models.BooleanField("يُصدره المقطِّع", default=False)

    class Meta:
        ordering = ["id"]
        verbose_name = "نوع المحتوى"
        verbose_name_plural = "أنواع المحتوى"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.code = self.code.strip().lower()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.code = self.code.strip().lower()


class Language(models.Model):
    """لغة من لغات المحتوى أو الترجمة."""

    class Direction(models.TextChoices):
        RTL = "rtl", "من اليمين إلى اليسار"
        LTR = "ltr", "من اليسار إلى اليمين"

    iso_code = models.CharField("رمز ISO", max_length=12, unique=True)
    name = models.CharField("اسم اللغة", max_length=100)
    name_en = models.CharField("الاسم بالإنجليزية", max_length=100)
    direction = models.CharField(
        "اتجاه الكتابة",
        max_length=3,
        choices=Direction,
        default=Direction.LTR,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "لغة"
        verbose_name_plural = "اللغات"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.iso_code = self.iso_code.strip().lower()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.iso_code = self.iso_code.strip().lower()
