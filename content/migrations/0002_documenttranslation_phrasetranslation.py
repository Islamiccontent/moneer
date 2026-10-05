import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0001_initial"),
        ("core", "0004_initial_content_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentTranslation",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "بانتظار البدء"),
                            ("translating", "الترجمة الآلية جارية"),
                            ("review", "قيد المراجعة"),
                            ("approved", "معتمدة"),
                            ("archived", "مؤرشفة"),
                        ],
                        default="pending",
                        max_length=12,
                        verbose_name="الحالة",
                    ),
                ),
                (
                    "ai_model",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="نموذج الذكاء الاصطناعي",
                    ),
                ),
                (
                    "approved_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="تاريخ الاعتماد"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="آخر تعديل"),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_translations_approved",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="اعتمدها",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_translations_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="أنشأها",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="translations",
                        to="content.document",
                        verbose_name="المستند",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_translations_as_reviewer",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="المراجع",
                    ),
                ),
                (
                    "target_language",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_translations",
                        to="core.language",
                        verbose_name="اللغة الهدف",
                    ),
                ),
            ],
            options={
                "verbose_name": "ترجمة مستند",
                "verbose_name_plural": "ترجمات المستندات",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PhraseTranslation",
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
                    "ai_translation",
                    models.TextField(blank=True, verbose_name="الترجمة الآلية المقترحة"),
                ),
                (
                    "translation",
                    models.TextField(blank=True, verbose_name="الترجمة الحالية"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "بانتظار الترجمة"),
                            ("suggested", "مقترحة آلياً"),
                            ("approved", "اعتمدها المراجع"),
                        ],
                        default="pending",
                        max_length=10,
                        verbose_name="الحالة",
                    ),
                ),
                (
                    "approved_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="تاريخ الاعتماد"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="آخر تعديل"),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phrase_translations_approved",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="اعتمدها",
                    ),
                ),
                (
                    "document_translation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="phrases",
                        to="content.documenttranslation",
                        verbose_name="ترجمة المستند",
                    ),
                ),
                (
                    "edited_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phrase_translations_edited",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="آخر من حرّرها",
                    ),
                ),
                (
                    "phrase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="translations",
                        to="content.phrase",
                        verbose_name="الجملة",
                    ),
                ),
            ],
            options={
                "verbose_name": "ترجمة جملة",
                "verbose_name_plural": "ترجمات الجمل",
                "ordering": ["phrase__group_id", "phrase__group_order"],
            },
        ),
        migrations.AddConstraint(
            model_name="documenttranslation",
            constraint=models.UniqueConstraint(
                fields=("document", "target_language"),
                name="unique_translation_per_document_and_language",
            ),
        ),
        migrations.AddConstraint(
            model_name="phrasetranslation",
            constraint=models.UniqueConstraint(
                fields=("document_translation", "phrase"),
                name="unique_phrase_translation_per_document_translation",
            ),
        ),
    ]
