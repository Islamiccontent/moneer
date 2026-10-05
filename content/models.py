"""المحتوى العربي بعد التقطيع والتصنيف: المستند وعباراته وتحليلها والمعجم وترجمات المستند وجمله."""

import hashlib
import textwrap

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def derive_phrase_id(title, group_id, group_order, text):
    """sha1 على ``title|group:order|text`` وأول 32 خانة hex بصيغة 8-4-4-4-12."""
    h = hashlib.sha1(f"{title}|{group_id}:{group_order}|{text}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class Document(models.Model):
    """مستند محتوى مصدري؛ عنوانه مدخل في مفاتيح عباراته فيُعامل كثابت."""

    class Kind(models.TextChoices):
        POST = "post", "منشور"
        KHUTBAH = "khutbah", "خطبة"
        ARTICLE = "article", "مقال"

    title = models.CharField("العنوان", max_length=255)
    kind = models.CharField("نوع المستند", max_length=10, choices=Kind)
    source_file_name = models.CharField("اسم الملف الأصلي", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="أنشأه",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "مستند"
        verbose_name_plural = "المستندات"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.title = self.title.strip()


class Phrase(models.Model):
    """عبارة مصنّفة ببنية فقرات ومفتاح حتمي يُحسب عند أول حفظ إن لم يُمرَّر."""

    class Tag(models.TextChoices):
        P = "p", "فقرة"
        HEADING1 = "heading1", "عنوان 1"
        HEADING2 = "heading2", "عنوان 2"
        HEADING3 = "heading3", "عنوان 3"
        HEADING4 = "heading4", "عنوان 4"
        HEADING5 = "heading5", "عنوان 5"
        LISTPARAGRAPH = "listparagraph", "فقرة قائمة"
        FOOTNOTE = "footnote", "هامش"

    class TextType(models.TextChoices):
        P = "p", "فقرة"
        H = "h", "عنوان"
        LISTPARAGRAPH = "listparagraph", "فقرة قائمة"
        FOOTNOTE = "footnote", "هامش"
        NAQHARA = "naqhara", "نقحرة"
        QUESTION = "question", "سؤال"
        ANSWER = "answer", "جواب"
        ABOUT = "about", "تعريف"

    class Align(models.TextChoices):
        RIGHT = "right", "يمين"
        LEFT = "left", "يسار"
        CENTER = "center", "وسط"
        JUSTIFY = "justify", "مساواة"
        BOTH = "both", "الجانبان"

    phrase_id = models.CharField("معرّف العبارة", max_length=36, primary_key=True)
    document = models.ForeignKey(
        Document,
        verbose_name="المستند",
        on_delete=models.CASCADE,
        related_name="phrases",
    )
    content_type = models.ForeignKey(
        "core.ContentTypeLookup",
        verbose_name="نوع المحتوى",
        on_delete=models.PROTECT,
        related_name="phrases",
    )
    group_id = models.PositiveIntegerField("رقم الفقرة")
    group_order = models.PositiveIntegerField("الترتيب داخل الفقرة")
    text = models.TextField("النص العربي")
    tag = models.CharField("الوسم", max_length=20, choices=Tag, default=Tag.P)
    text_type = models.CharField("نوع النص", max_length=20, choices=TextType, default=TextType.P)
    align = models.CharField("المحاذاة", max_length=10, choices=Align, default=Align.RIGHT)
    translatable = models.BooleanField("قابل للترجمة", default=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["document", "group_id", "group_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "group_id", "group_order"],
                name="unique_phrase_slot_per_document",
            )
        ]
        verbose_name = "عبارة"
        verbose_name_plural = "العبارات"

    def __str__(self):
        return textwrap.shorten(self.text, width=50, placeholder="…")

    def save(self, *args, **kwargs):
        if not self.phrase_id:
            self.phrase_id = derive_phrase_id(
                self.document.title, self.group_id, self.group_order, self.text
            )
        super().save(*args, **kwargs)


class PhraseAnalysis(models.Model):
    """نتيجة تحليل عبارة: صنفها وسبب الثقة ونسبتها ومرجعها."""

    class Kind(models.TextChoices):
        QURAN = "quran", "آية"
        HADITH = "hadith", "حديث"
        ATHAR = "athar", "أثر"
        HEADING = "heading", "عنوان"
        AUTHOR = "author", "مؤلف"
        ATTRIBUTION = "attribution", "إسناد"
        CITATION = "citation", "عزو"
        TERM = "term", "مصطلح"
        PLAIN = "plain", "نص عادي"

    class ReasonCode(models.TextChoices):
        WORD_HEADING_STYLE = "word_heading_style", "نمط عنوان في Word"
        INDEX_MATCH = "index_match", "مطابقة فهرس"
        CITATION_REF = "citation_ref", "إحالة عزو"
        ATTRIBUTION_FORMULA = "attribution_formula", "صيغة إسناد"
        GLOSSARY_ENTRY = "glossary_entry", "مدخل معجمي"
        UNMATCHED_QURAN = "unmatched_quran", "آية بلا مطابقة"
        UNMATCHED_HADITH = "unmatched_hadith", "حديث بلا مطابقة"
        NO_EVIDENCE = "no_evidence", "بلا قرينة"

    phrase = models.OneToOneField(
        Phrase,
        verbose_name="العبارة",
        on_delete=models.CASCADE,
        related_name="analysis",
    )
    kind = models.CharField("صنف التحليل", max_length=15, choices=Kind)
    reason_code = models.CharField("سبب الثقة", max_length=25, choices=ReasonCode)
    confidence = models.PositiveSmallIntegerField(
        "نسبة الثقة",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    reference = models.CharField("المرجع", max_length=255, blank=True)
    source = models.CharField("المصدر", max_length=150, blank=True)
    source_url = models.URLField("رابط المصدر", blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        verbose_name = "تحليل عبارة"
        verbose_name_plural = "تحليلات العبارات"

    def __str__(self):
        return f"تحليل: {self.phrase}"


class Glossary(models.Model):
    """المعجم الموحّد: مدخل عربي واحد بمقابله الإنجليزي المعتمد."""

    class Category(models.TextChoices):
        TERM = "term", "مصطلح يُرَدّ لمقابله"
        PERSON = "person", "عَلَم يُنقحَر"
        PLACE = "place", "مكان"
        DIVINE_NAME = "divine_name", "اسم وصفة"
        SECT = "sect", "فرقة"
        ATTRIBUTE = "attribute", "صفة"

    ar = models.CharField("المدخل العربي", max_length=100, unique=True)
    en = models.CharField("المقابل الإنجليزي", max_length=255)
    category = models.CharField("الفئة", max_length=15, choices=Category)
    agreement_count = models.PositiveIntegerField("ورودات الترجمة")
    agreement_total = models.PositiveIntegerField("إجمالي الورودات")
    strong = models.BooleanField("إجماع قوي", default=False)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["ar"]
        verbose_name = "مدخل معجمي"
        verbose_name_plural = "المعجم"

    def __str__(self):
        return self.ar

    def save(self, *args, **kwargs):
        self.ar = self.ar.strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.ar = self.ar.strip()


class GlossaryTranslation(models.Model):
    """ترجمة مدخل معجمي إلى لغة: العنوان المعتمد الذي تُلزم به الترجمة وتعريفاته لبطاقة التعريف."""

    glossary = models.ForeignKey(
        Glossary,
        verbose_name="المدخل المعجمي",
        on_delete=models.CASCADE,
        related_name="translations",
    )
    language = models.ForeignKey(
        "core.Language",
        verbose_name="اللغة",
        on_delete=models.PROTECT,
        related_name="glossary_translations",
    )
    title = models.CharField("العنوان المعتمد", max_length=255)
    short_def = models.TextField("التعريف المختصر", blank=True)
    explanation = models.TextField("الشرح الموجز", blank=True)
    ling_def = models.TextField("التعريف اللغوي المختصر", blank=True)
    long_ling_def = models.TextField("التعريف اللغوي", blank=True)
    benefits = models.TextField("الفوائد", blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["glossary__ar", "language__iso_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["glossary", "language"],
                name="unique_glossary_translation_per_language",
            )
        ]
        verbose_name = "ترجمة مدخل معجمي"
        verbose_name_plural = "ترجمات المعجم"

    def __str__(self):
        return f"{self.glossary.ar} ({self.language.iso_code}): {self.title}"


class PhraseTerm(models.Model):
    """ورود مدخل معجمي في عبارة — ربط فقط، بلا نسخ للنص أو الترجمة."""

    phrase = models.ForeignKey(
        Phrase,
        verbose_name="العبارة",
        on_delete=models.CASCADE,
        related_name="terms",
    )
    glossary = models.ForeignKey(
        Glossary,
        verbose_name="المدخل المعجمي",
        on_delete=models.PROTECT,
        related_name="occurrences",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["phrase", "glossary"],
                name="unique_glossary_entry_per_phrase",
            )
        ]
        verbose_name = "ورود معجمي"
        verbose_name_plural = "الورودات المعجمية"

    def __str__(self):
        return str(self.glossary)


class DocumentTranslation(models.Model):
    """مشروع ترجمة مستند إلى لغة هدف واحدة: الحالة والإعدادات والتكليف والاعتماد."""

    class Status(models.TextChoices):
        PENDING = "pending", "بانتظار البدء"
        TRANSLATING = "translating", "الترجمة الآلية جارية"
        REVIEW = "review", "قيد المراجعة"
        APPROVED = "approved", "معتمدة"
        ARCHIVED = "archived", "مؤرشفة"

    document = models.ForeignKey(
        Document,
        verbose_name="المستند",
        on_delete=models.CASCADE,
        related_name="translations",
    )
    target_language = models.ForeignKey(
        "core.Language",
        verbose_name="اللغة الهدف",
        on_delete=models.PROTECT,
        related_name="document_translations",
    )
    status = models.CharField("الحالة", max_length=12, choices=Status, default=Status.PENDING)

    ai_model = models.CharField("نموذج الذكاء الاصطناعي", max_length=100, blank=True)

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="المراجع",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_translations_as_reviewer",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="اعتمدها",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_translations_approved",
    )
    approved_at = models.DateTimeField("تاريخ الاعتماد", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="أنشأها",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_translations_created",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "target_language"],
                name="unique_translation_per_document_and_language",
            )
        ]
        verbose_name = "ترجمة مستند"
        verbose_name_plural = "ترجمات المستندات"

    def __str__(self):
        return f"{self.document} إلى {self.target_language}"


class PhraseTranslation(models.Model):
    """ترجمة جملة واحدة داخل ترجمة مستند: اقتراح الذكاء الاصطناعي، النص المعتمد، ودورة الاعتماد."""

    class Status(models.TextChoices):
        PENDING = "pending", "بانتظار الترجمة"
        SUGGESTED = "suggested", "مقترحة آلياً"
        APPROVED = "approved", "اعتمدها المراجع"

    document_translation = models.ForeignKey(
        DocumentTranslation,
        verbose_name="ترجمة المستند",
        on_delete=models.CASCADE,
        related_name="phrases",
    )

    phrase = models.ForeignKey(
        Phrase,
        verbose_name="الجملة",
        on_delete=models.CASCADE,
        related_name="translations",
    )

    ai_translation = models.TextField("الترجمة الآلية المقترحة", blank=True)
    translation = models.TextField("الترجمة الحالية", blank=True)

    status = models.CharField("الحالة", max_length=10, choices=Status, default=Status.PENDING)

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="آخر من حرّرها",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phrase_translations_edited",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="اعتمدها",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phrase_translations_approved",
    )
    approved_at = models.DateTimeField("تاريخ الاعتماد", null=True, blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        ordering = ["phrase__group_id", "phrase__group_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_translation", "phrase"],
                name="unique_phrase_translation_per_document_translation",
            )
        ]
        verbose_name = "ترجمة جملة"
        verbose_name_plural = "ترجمات الجمل"

    def __str__(self):
        text = self.translation or self.ai_translation or "(بلا ترجمة بعد)"
        return textwrap.shorten(text, width=50, placeholder="…")

    def clean(self):
        super().clean()
        if (
            self.phrase_id
            and self.document_translation_id
            and self.phrase.document_id != self.document_translation.document_id
        ):
            raise ValidationError({"phrase": "الجملة لا تنتمي إلى مستند هذه الترجمة."})
        if self.status == self.Status.APPROVED and not self.translation.strip():
            raise ValidationError({"translation": "لا تُعتمد ترجمة فارغة."})
