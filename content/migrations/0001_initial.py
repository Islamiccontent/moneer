import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0003_contenttypelookup"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Glossary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("ar", models.CharField(max_length=100, unique=True, verbose_name="المدخل العربي")),
                ("en", models.CharField(max_length=255, verbose_name="المقابل الإنجليزي")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("term", "مصطلح يُرَدّ لمقابله"),
                            ("person", "عَلَم يُنقحَر"),
                            ("place", "مكان"),
                            ("divine_name", "اسم وصفة"),
                            ("sect", "فرقة"),
                            ("attribute", "صفة"),
                        ],
                        max_length=15,
                        verbose_name="الفئة",
                    ),
                ),
                ("agreement_count", models.PositiveIntegerField(verbose_name="ورودات الترجمة")),
                ("agreement_total", models.PositiveIntegerField(verbose_name="إجمالي الورودات")),
                ("strong", models.BooleanField(default=False, verbose_name="إجماع قوي")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
            ],
            options={
                "verbose_name": "مدخل معجمي",
                "verbose_name_plural": "المعجم",
                "ordering": ["ar"],
            },
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("title", models.CharField(max_length=255, verbose_name="العنوان")),
                (
                    "kind",
                    models.CharField(
                        choices=[("post", "منشور"), ("khutbah", "خطبة"), ("article", "مقال")],
                        max_length=10,
                        verbose_name="نوع المستند",
                    ),
                ),
                (
                    "source_file_name",
                    models.CharField(blank=True, max_length=255, verbose_name="اسم الملف الأصلي"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="documents",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="أنشأه",
                    ),
                ),
            ],
            options={
                "verbose_name": "مستند",
                "verbose_name_plural": "المستندات",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Phrase",
            fields=[
                (
                    "phrase_id",
                    models.CharField(
                        max_length=36,
                        primary_key=True,
                        serialize=False,
                        verbose_name="معرّف العبارة",
                    ),
                ),
                ("group_id", models.PositiveIntegerField(verbose_name="رقم الفقرة")),
                ("group_order", models.PositiveIntegerField(verbose_name="الترتيب داخل الفقرة")),
                ("text", models.TextField(verbose_name="النص العربي")),
                (
                    "tag",
                    models.CharField(
                        choices=[
                            ("p", "فقرة"),
                            ("heading1", "عنوان 1"),
                            ("heading2", "عنوان 2"),
                            ("heading3", "عنوان 3"),
                            ("heading4", "عنوان 4"),
                            ("heading5", "عنوان 5"),
                            ("listparagraph", "فقرة قائمة"),
                            ("footnote", "هامش"),
                        ],
                        default="p",
                        max_length=20,
                        verbose_name="الوسم",
                    ),
                ),
                (
                    "text_type",
                    models.CharField(
                        choices=[
                            ("p", "فقرة"),
                            ("h", "عنوان"),
                            ("listparagraph", "فقرة قائمة"),
                            ("footnote", "هامش"),
                            ("naqhara", "نقحرة"),
                            ("question", "سؤال"),
                            ("answer", "جواب"),
                            ("about", "تعريف"),
                        ],
                        default="p",
                        max_length=20,
                        verbose_name="نوع النص",
                    ),
                ),
                (
                    "align",
                    models.CharField(
                        choices=[
                            ("right", "يمين"),
                            ("left", "يسار"),
                            ("center", "وسط"),
                            ("justify", "مساواة"),
                            ("both", "الجانبان"),
                        ],
                        default="right",
                        max_length=10,
                        verbose_name="المحاذاة",
                    ),
                ),
                ("translatable", models.BooleanField(default=True, verbose_name="قابل للترجمة")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="phrases",
                        to="core.contenttypelookup",
                        verbose_name="نوع المحتوى",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="phrases",
                        to="content.document",
                        verbose_name="المستند",
                    ),
                ),
            ],
            options={
                "verbose_name": "عبارة",
                "verbose_name_plural": "العبارات",
                "ordering": ["document", "group_id", "group_order"],
            },
        ),
        migrations.CreateModel(
            name="PhraseAnalysis",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("quran", "آية"),
                            ("hadith", "حديث"),
                            ("athar", "أثر"),
                            ("heading", "عنوان"),
                            ("author", "مؤلف"),
                            ("attribution", "إسناد"),
                            ("citation", "عزو"),
                            ("term", "مصطلح"),
                            ("plain", "نص عادي"),
                        ],
                        max_length=15,
                        verbose_name="صنف التحليل",
                    ),
                ),
                (
                    "reason_code",
                    models.CharField(
                        choices=[
                            ("word_heading_style", "نمط عنوان في Word"),
                            ("index_match", "مطابقة فهرس"),
                            ("citation_ref", "إحالة عزو"),
                            ("attribution_formula", "صيغة إسناد"),
                            ("glossary_entry", "مدخل معجمي"),
                            ("unmatched_quran", "آية بلا مطابقة"),
                            ("unmatched_hadith", "حديث بلا مطابقة"),
                            ("no_evidence", "بلا قرينة"),
                        ],
                        max_length=25,
                        verbose_name="سبب الثقة",
                    ),
                ),
                (
                    "confidence",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="نسبة الثقة",
                    ),
                ),
                ("reference", models.CharField(blank=True, max_length=255, verbose_name="المرجع")),
                ("source", models.CharField(blank=True, max_length=150, verbose_name="المصدر")),
                ("source_url", models.URLField(blank=True, verbose_name="رابط المصدر")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                (
                    "phrase",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analysis",
                        to="content.phrase",
                        verbose_name="العبارة",
                    ),
                ),
            ],
            options={
                "verbose_name": "تحليل عبارة",
                "verbose_name_plural": "تحليلات العبارات",
            },
        ),
        migrations.CreateModel(
            name="PhraseTerm",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                (
                    "glossary",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="occurrences",
                        to="content.glossary",
                        verbose_name="المدخل المعجمي",
                    ),
                ),
                (
                    "phrase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="terms",
                        to="content.phrase",
                        verbose_name="العبارة",
                    ),
                ),
            ],
            options={
                "verbose_name": "ورود معجمي",
                "verbose_name_plural": "الورودات المعجمية",
                "ordering": ["id"],
            },
        ),
        migrations.AddConstraint(
            model_name="phrase",
            constraint=models.UniqueConstraint(
                fields=("document", "group_id", "group_order"),
                name="unique_phrase_slot_per_document",
            ),
        ),
        migrations.AddConstraint(
            model_name="phraseterm",
            constraint=models.UniqueConstraint(
                fields=("phrase", "glossary"), name="unique_glossary_entry_per_phrase"
            ),
        ),
    ]
