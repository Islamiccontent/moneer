from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("classify", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="SegmentationJob",
        ),
    ]
