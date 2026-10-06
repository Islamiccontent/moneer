"""إحالات المصادر (العزو) صارت تُترجم: تُفتح للترجمة في المستندات القائمة كذلك."""

from django.db import migrations


def make_translatable(apps, schema_editor):
    apps.get_model("content", "Phrase").objects.filter(translatable=False).update(translatable=True)


class Migration(migrations.Migration):
    dependencies = [("content", "0003_glossarytranslation")]

    operations = [migrations.RunPython(make_translatable, migrations.RunPython.noop)]
