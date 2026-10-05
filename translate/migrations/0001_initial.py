import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0004_initial_content_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuranAyah",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "surah_no",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(114),
                        ],
                        verbose_name="رقم السورة",
                    ),
                ),
                (
                    "ayah_no",
                    models.PositiveSmallIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="رقم الآية",
                    ),
                ),
                (
                    "surah_name",
                    models.CharField(max_length=30, verbose_name="اسم السورة"),
                ),
                (
                    "juz",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(30),
                        ],
                        verbose_name="الجزء",
                    ),
                ),
                (
                    "page",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(604),
                        ],
                        verbose_name="الصفحة",
                    ),
                ),
                ("text_uthmani", models.TextField(verbose_name="النص بالرسم العثماني")),
                ("text_imlaei", models.TextField(verbose_name="النص بالرسم الإملائي")),
                (
                    "clean_uthmani",
                    models.TextField(editable=False, verbose_name="العثماني بلا تشكيل"),
                ),
                (
                    "clean_imlaei",
                    models.TextField(editable=False, verbose_name="الإملائي بلا تشكيل"),
                ),
                (
                    "normalized_uthmani",
                    models.TextField(editable=False, verbose_name="العثماني مطبَّعاً"),
                ),
                (
                    "normalized_imlaei",
                    models.TextField(editable=False, verbose_name="الإملائي مطبَّعاً"),
                ),
            ],
            options={
                "verbose_name": "آية",
                "verbose_name_plural": "الآيات",
                "ordering": ["surah_no", "ayah_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("surah_no", "ayah_no"), name="unique_ayah_per_surah"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="QuranTranslationKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "key",
                    models.CharField(max_length=100, unique=True, verbose_name="مفتاح quranenc"),
                ),
                ("name", models.CharField(max_length=200, verbose_name="اسم الترجمة")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="آخر تعديل"),
                ),
                (
                    "language",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quran_translation_key",
                        to="core.language",
                        verbose_name="اللغة",
                    ),
                ),
            ],
            options={
                "verbose_name": "مفتاح ترجمة القرآن",
                "verbose_name_plural": "مفاتيح ترجمات القرآن",
                "ordering": ["language__name"],
            },
        ),
        migrations.CreateModel(
            name="QuranAyahTranslation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("text", models.TextField(verbose_name="الترجمة")),
                (
                    "text_raw",
                    models.TextField(blank=True, verbose_name="النص كما ورد من المصدر"),
                ),
                ("footnotes", models.TextField(blank=True, verbose_name="الحواشي")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="آخر تعديل"),
                ),
                (
                    "ayah",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="translations",
                        to="translate.quranayah",
                        verbose_name="الآية",
                    ),
                ),
                (
                    "translation_key",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ayah_translations",
                        to="translate.qurantranslationkey",
                        verbose_name="مفتاح الترجمة",
                    ),
                ),
            ],
            options={
                "verbose_name": "ترجمة آية",
                "verbose_name_plural": "ترجمات الآيات",
                "ordering": ["translation_key", "ayah__surah_no", "ayah__ayah_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("translation_key", "ayah"),
                        name="unique_translation_per_key_and_ayah",
                    )
                ],
            },
        ),
    ]
