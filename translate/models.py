"""الترجمة المعتمدة للقرآن: آيات المصحف بالرسمين، ومفتاح ترجمة لكل لغة، وترجمة كل آية به."""

import textwrap

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from classify.services.normalizer import expand_dagger, light, normalize

SURAH_COUNT = 114
JUZ_COUNT = 30
PAGE_COUNT = 604


def matching_forms(text_uthmani, text_imlaei):
    """الأعمدة المحسوبة للمطابقة من الرسمين: بلا تشكيل (clean_*) ومطبّعة الحروف (normalized_*)."""
    return {
        "clean_uthmani": light(text_uthmani),
        "clean_imlaei": light(text_imlaei),
        "normalized_uthmani": normalize(expand_dagger(text_uthmani)),
        "normalized_imlaei": normalize(text_imlaei),
    }


class QuranAyah(models.Model):
    """آية من المصحف بالرسمين، مع صورها المحسوبة للمطابقة."""

    surah_no = models.PositiveSmallIntegerField(
        "رقم السورة", validators=[MinValueValidator(1), MaxValueValidator(SURAH_COUNT)]
    )
    ayah_no = models.PositiveSmallIntegerField("رقم الآية", validators=[MinValueValidator(1)])
    surah_name = models.CharField("اسم السورة", max_length=30)
    juz = models.PositiveSmallIntegerField(
        "الجزء", validators=[MinValueValidator(1), MaxValueValidator(JUZ_COUNT)]
    )
    page = models.PositiveSmallIntegerField(
        "الصفحة", validators=[MinValueValidator(1), MaxValueValidator(PAGE_COUNT)]
    )
    text_uthmani = models.TextField("النص بالرسم العثماني")
    text_imlaei = models.TextField("النص بالرسم الإملائي")
    clean_uthmani = models.TextField("العثماني بلا تشكيل", editable=False)
    clean_imlaei = models.TextField("الإملائي بلا تشكيل", editable=False)
    normalized_uthmani = models.TextField("العثماني مطبَّعاً", editable=False)
    normalized_imlaei = models.TextField("الإملائي مطبَّعاً", editable=False)

    class Meta:
        ordering = ["surah_no", "ayah_no"]
        constraints = [
            models.UniqueConstraint(fields=["surah_no", "ayah_no"], name="unique_ayah_per_surah")
        ]
        verbose_name = "آية"
        verbose_name_plural = "الآيات"

    def __str__(self):
        return f"سورة {self.surah_name} — {self.ayah_no}"

    def save(self, *args, **kwargs):
        self.surah_name = self.surah_name.strip()
        self.text_uthmani = self.text_uthmani.strip()
        self.text_imlaei = self.text_imlaei.strip()
        for field, value in matching_forms(self.text_uthmani, self.text_imlaei).items():
            setattr(self, field, value)
        super().save(*args, **kwargs)


class QuranTranslationKey(models.Model):
    """مفتاح ترجمة معتمدة في موسوعة القرآن الكريم للغة هدف واحدة."""

    language = models.OneToOneField(
        "core.Language",
        verbose_name="اللغة",
        on_delete=models.PROTECT,
        related_name="quran_translation_key",
    )
    key = models.CharField("مفتاح quranenc", max_length=100, unique=True)
    name = models.CharField("اسم الترجمة", max_length=200)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["language__name"]
        verbose_name = "مفتاح ترجمة القرآن"
        verbose_name_plural = "مفاتيح ترجمات القرآن"

    def __str__(self):
        return f"{self.name} ({self.language})"

    def save(self, *args, **kwargs):
        self.key = self.key.strip()
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.key = self.key.strip()
        self.name = self.name.strip()


class QuranAyahTranslation(models.Model):
    """ترجمة آية واحدة بمفتاح ترجمة واحد."""

    translation_key = models.ForeignKey(
        QuranTranslationKey,
        verbose_name="مفتاح الترجمة",
        on_delete=models.CASCADE,
        related_name="ayah_translations",
    )
    ayah = models.ForeignKey(
        QuranAyah,
        verbose_name="الآية",
        on_delete=models.PROTECT,
        related_name="translations",
    )
    text = models.TextField("الترجمة")
    text_raw = models.TextField("النص كما ورد من المصدر", blank=True)
    footnotes = models.TextField("الحواشي", blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["translation_key", "ayah__surah_no", "ayah__ayah_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["translation_key", "ayah"], name="unique_translation_per_key_and_ayah"
            )
        ]
        verbose_name = "ترجمة آية"
        verbose_name_plural = "ترجمات الآيات"

    def __str__(self):
        return textwrap.shorten(self.text, width=50, placeholder="…")
