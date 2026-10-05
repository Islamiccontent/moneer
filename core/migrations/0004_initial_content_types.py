"""أنواع المحتوى الأولية (data migration قابلة للتراجع)؛ الإضافات اللاحقة في migration جديدة."""

from django.db import migrations

INITIAL_CONTENT_TYPES = [
    (1, "ayah", "آية", True),
    (2, "hadith", "حديث", True),
    (3, "athar", "أثر", True),
    (4, "text", "نص", True),
    (5, "footnote", "هامش", False),
    (6, "heading", "العنوان", False),
    (7, "author", "المؤلف", False),
]


def add_initial_content_types(apps, schema_editor):
    ContentTypeLookup = apps.get_model("core", "ContentTypeLookup")
    for type_id, code, name, is_emitted in INITIAL_CONTENT_TYPES:
        ContentTypeLookup.objects.get_or_create(
            id=type_id,
            defaults={"code": code, "name": name, "is_emitted": is_emitted},
        )


def remove_initial_content_types(apps, schema_editor):
    ContentTypeLookup = apps.get_model("core", "ContentTypeLookup")
    ContentTypeLookup.objects.filter(
        id__in=[type_id for type_id, *_ in INITIAL_CONTENT_TYPES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0003_contenttypelookup")]

    operations = [migrations.RunPython(add_initial_content_types, remove_initial_content_types)]
