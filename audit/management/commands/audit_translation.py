"""تدقيق ترجمة مستند من سطر الأوامر فورياً في هذه العملية (للتطوير والتشخيص)، مع Excel اختياري."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from audit import pipeline
from content.models import DocumentTranslation


class Command(BaseCommand):
    help = "يدقّق ترجمة مستند بالقواعد المحلية ثم Gemini فورياً ويحفظ النتائج في تطبيق audit."

    def add_arguments(self, parser):
        parser.add_argument(
            "document_translation", type=int, help="معرّف content.DocumentTranslation."
        )
        parser.add_argument("--limit", type=int, help="فحص أول N جملة فقط.")
        parser.add_argument(
            "--extra-rules", default="", help="قواعد إضافية خاصة باللغة تُدرج في البرومت."
        )
        parser.add_argument(
            "--output", help="مسار ملف Excel للنتائج (اختياري، بلا تخزين في القاعدة)."
        )

    def handle(self, *args, **options):
        translation = (
            DocumentTranslation.objects.select_related("document", "target_language")
            .filter(pk=options["document_translation"])
            .first()
        )
        if translation is None:
            raise CommandError("لا توجد ترجمة مستند بهذا المعرّف.")
        try:
            job = pipeline.run_audit(
                translation, extra_rules=options["extra_rules"], limit=options["limit"]
            )
        except pipeline.AuditError as exc:
            raise CommandError(str(exc)) from exc

        verdicts = ", ".join(
            f"{v['label']}: {v['count']}" for v in job.stats.get("verdicts", []) if v["count"]
        )
        self.stdout.write(
            f"مهمة التدقيق #{job.pk} — {translation}: {job.get_status_display()}\n"
            f"الصفوف: {job.total_rows} (مؤهلة للنموذج: {job.eligible_rows}) — "
            f"الملاحظات: {job.finding_count}" + (f" — الأحكام: {verdicts}" if verdicts else "")
        )
        self.stdout.write(f"التوكن: إدخال {job.prompt_tokens} / إخراج {job.output_tokens}")
        if job.error_message:
            self.stderr.write(job.error_message)
        if options["output"]:
            path = Path(options["output"])
            path.write_bytes(pipeline.export_xlsx(job))
            self.stdout.write(self.style.SUCCESS(f"ملف النتائج: {path}"))
