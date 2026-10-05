from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_initial_languages"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentTypeLookup",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        primary_key=True, serialize=False, verbose_name="المعرّف"
                    ),
                ),
                ("code", models.CharField(max_length=30, unique=True, verbose_name="الرمز")),
                ("name", models.CharField(max_length=100, verbose_name="الاسم")),
                ("is_emitted", models.BooleanField(default=False, verbose_name="يُصدره المقطِّع")),
            ],
            options={
                "verbose_name": "نوع المحتوى",
                "verbose_name_plural": "أنواع المحتوى",
                "ordering": ["id"],
            },
        ),
    ]
