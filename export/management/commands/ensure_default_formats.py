"""إنشاء تنسيق تصدير افتراضي لكل لغة ليس لها تنسيق، بافتراضيات اتجاهها (idempotent)."""

from django.core.management.base import BaseCommand

from core.models import Language
from export.models import ExportFormat

DEFAULT_NAME = "التنسيق الافتراضي"


class Command(BaseCommand):
    help = "ينشئ تنسيق تصدير افتراضياً لكل لغة بلا تنسيق؛ لا يمسّ التنسيقات الموجودة."

    def add_arguments(self, parser):
        parser.add_argument(
            "--language", action="append", dest="languages", help="رمز ISO للغة؛ يتكرر."
        )

    def handle(self, *args, **options):
        languages = Language.objects.all()
        if options["languages"]:
            languages = languages.filter(
                iso_code__in=[c.strip().lower() for c in options["languages"]]
            )
        created = 0
        for language in languages.order_by("name"):
            if ExportFormat.objects.filter(language=language).exists():
                continue
            ExportFormat.objects.create(language=language, name=DEFAULT_NAME, is_default=True)
            created += 1
        if options["verbosity"] >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"أُنشئ {created} تنسيق افتراضي؛ "
                    f"{languages.count() - created} لغة كان لها تنسيق."
                )
            )
