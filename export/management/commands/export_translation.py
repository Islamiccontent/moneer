"""تصدير ترجمة مستند إلى ملف Word أو PDF أو Excel من سطر الأوامر آنياً بلا تسجيل في القاعدة."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from content.models import DocumentTranslation
from export.models import ExportFormat
from export.services.export import KINDS, LAYOUTS, ExportError, export_translation


class Command(BaseCommand):
    help = "يصدّر ترجمة مستند إلى DOCX أو PDF بتنسيق اللغة الافتراضي أو تنسيق محدد، أو XLSX."

    def add_arguments(self, parser):
        parser.add_argument(
            "document_translation", type=int, help="معرّف content.DocumentTranslation."
        )
        parser.add_argument("--format", type=int, dest="export_format", help="معرّف تنسيق التصدير.")
        parser.add_argument(
            "--kind", choices=KINDS, default="docx", help="نوع الملف (الافتراضي docx)."
        )
        parser.add_argument(
            "--layout", choices=sorted(LAYOUTS), help="تخطيط Word: الترجمة فقط أو ثنائي متتابع."
        )
        parser.add_argument(
            "--output",
            help="مسار الملف الناتج أو مجلده؛ الافتراضي الاسم المولَّد في المجلد الحالي.",
        )

    def handle(self, *args, **options):
        try:
            document_translation = DocumentTranslation.objects.select_related(
                "document", "target_language"
            ).get(pk=options["document_translation"])
        except DocumentTranslation.DoesNotExist as exc:
            raise CommandError(
                f"لا ترجمة مستند بالمعرّف {options['document_translation']}."
            ) from exc
        export_format = None
        if options["export_format"]:
            try:
                export_format = ExportFormat.objects.get(pk=options["export_format"])
            except ExportFormat.DoesNotExist as exc:
                raise CommandError(f"لا تنسيق بالمعرّف {options['export_format']}.") from exc
        try:
            result = export_translation(
                document_translation,
                export_format=export_format,
                kind=options["kind"],
                layout=options["layout"],
            )
        except ExportError as exc:
            raise CommandError(str(exc)) from exc
        path = Path(options["output"] or result.file_name)
        if path.is_dir():
            path = path / result.file_name
        path.write_bytes(result.content)
        if options["verbosity"] >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"صُدِّر {result.rows} جملة ({result.missing} بلا ترجمة أُسقطت؛ "
                    f"حواشٍ {result.stats.get('footnotes_placed', 0)} مُعلَّقة و"
                    f"{result.stats.get('footnotes_missed', 0)} لم تُعلَّق) إلى {path}"
                )
            )
