import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0002_documenttranslation_phrasetranslation"),
        ("core", "0004_initial_content_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="GlossaryTranslation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("title", models.CharField(max_length=255, verbose_name="العنوان المعتمد")),
                ("short_def", models.TextField(blank=True, verbose_name="التعريف المختصر")),
                ("explanation", models.TextField(blank=True, verbose_name="الشرح الموجز")),
                ("ling_def", models.TextField(blank=True, verbose_name="التعريف اللغوي المختصر")),
                ("long_ling_def", models.TextField(blank=True, verbose_name="التعريف اللغوي")),
                ("benefits", models.TextField(blank=True, verbose_name="الفوائد")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخر تعديل")),
                (
                    "glossary",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="translations",
                        to="content.glossary",
                        verbose_name="المدخل المعجمي",
                    ),
                ),
                (
                    "language",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="glossary_translations",
                        to="core.language",
                        verbose_name="اللغة",
                    ),
                ),
            ],
            options={
                "verbose_name": "ترجمة مدخل معجمي",
                "verbose_name_plural": "ترجمات المعجم",
                "ordering": ["glossary__ar", "language__iso_code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("glossary", "language"),
                        name="unique_glossary_translation_per_language",
                    )
                ],
            },
        ),
    ]
