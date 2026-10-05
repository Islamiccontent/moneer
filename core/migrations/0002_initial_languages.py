"""اللغات الأولية (data migration قابلة للتراجع)؛ الإضافات اللاحقة في migration جديدة."""

from django.db import migrations

INITIAL_LANGUAGES = [
    ("ar", "العربية", "Arabic", "rtl"),
    ("en", "الإنجليزية", "English", "ltr"),
    ("fr", "الفرنسية", "French", "ltr"),
    ("id", "الإندونيسية", "Indonesian", "ltr"),
    ("tr", "التركية", "Turkish", "ltr"),
    ("ur", "الأردية", "Urdu", "rtl"),
]


def add_initial_languages(apps, schema_editor):
    Language = apps.get_model("core", "Language")
    for iso_code, name, name_en, direction in INITIAL_LANGUAGES:
        Language.objects.get_or_create(
            iso_code=iso_code,
            defaults={"name": name, "name_en": name_en, "direction": direction},
        )


def remove_initial_languages(apps, schema_editor):
    Language = apps.get_model("core", "Language")
    Language.objects.filter(iso_code__in=[code for code, *_ in INITIAL_LANGUAGES]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(add_initial_languages, remove_initial_languages)]
