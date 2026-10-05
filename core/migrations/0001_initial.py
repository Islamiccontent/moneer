from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Language",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("iso_code", models.CharField(max_length=12, unique=True, verbose_name="رمز ISO")),
                ("name", models.CharField(max_length=100, verbose_name="اسم اللغة")),
                ("name_en", models.CharField(max_length=100, verbose_name="الاسم بالإنجليزية")),
                (
                    "direction",
                    models.CharField(
                        choices=[("rtl", "من اليمين إلى اليسار"), ("ltr", "من اليسار إلى اليمين")],
                        default="ltr",
                        max_length=3,
                        verbose_name="اتجاه الكتابة",
                    ),
                ),
            ],
            options={
                "verbose_name": "لغة",
                "verbose_name_plural": "اللغات",
                "ordering": ["name"],
            },
        ),
    ]
