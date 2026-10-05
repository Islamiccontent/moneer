"""الكنس الدوري: يُدرج مهمة ترجمة لكل ترجمة مستند لم تكتمل؛ يُشغَّل من cron كل عشر دقائق."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.tasks import TaskResultStatus

from translate.tasks import can_translate, translate_pending_task


class Command(BaseCommand):
    help = "يُدرج مهام ترجمة لكل ترجمة مستند لم تكتمل (كنس دوري من cron)."

    def handle(self, *args, **options):
        if not can_translate():
            raise CommandError("GEMINI_API_KEY غير مضبوط؛ لا يمكن تشغيل الترجمة.")
        result = translate_pending_task.enqueue()
        if options["verbosity"] < 1:
            return
        if result.status == TaskResultStatus.SUCCESSFUL:
            self.stdout.write(
                self.style.SUCCESS(
                    f"عولجت {result.return_value['enqueued']} ترجمة مستند غير مكتملة."
                )
            )
        elif result.status == TaskResultStatus.FAILED:
            raise CommandError(f"فشلت مهمة الكنس: {result.errors}")
        else:
            backend = settings.TASKS["default"]["BACKEND"].rsplit(".", 1)[-1]
            self.stdout.write(f"أُدرجت مهمة الكنس في الخلفية ({backend}).")
