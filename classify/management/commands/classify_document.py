"""تشغيل خط التقطيع والتصنيف على ملف Word أو نص وحفظ الناتج في تطبيق content."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from classify import pipeline
from classify.services.splitter import DocumentError, cover_title, extract_docx, extract_text
from content.models import Document


class Command(BaseCommand):
    help = "يقطّع ملف Word أو نصاً ويصنّفه ويحفظ الناتج في تطبيق content."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--file", help="ملف ‎.docx يُقطَّع.")
        source.add_argument("--text", help="نص مباشر يُقطَّع.")
        parser.add_argument("--title", help="عنوان المستند (الافتراضي اسم الملف).")
        parser.add_argument(
            "--kind",
            choices=Document.Kind.values,
            default=Document.Kind.ARTICLE,
            help="نوع المستند (الافتراضي article).",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="حذف المستند السابق بالعنوان نفسه قبل الحفظ.",
        )

    def handle(self, *args, **options):
        title, source_file_name, paragraphs = self._extract(options)
        if not paragraphs:
            raise CommandError("لم يُعثر على نص.")

        segments = pipeline.run(paragraphs)
        try:
            document, payload = pipeline.save_document(
                title, options["kind"], source_file_name, segments, replace=options["replace"]
            )
        except pipeline.DuplicateTitleError as exc:
            raise CommandError(
                f"يوجد مستند بالعنوان «{title}» (استخدم --replace لاستبداله)."
            ) from exc

        doc_info = payload["document"]
        self.stdout.write(
            self.style.SUCCESS(
                f"حُفظ المستند #{document.pk} «{title}»: "
                f"{doc_info['phrases']} عبارة في {doc_info['paragraphs']} فقرة — "
                + "، ".join(f"{name} {n}" for name, n in doc_info["by_content_type"].items())
                + f" — تحتاج مراجعة: {doc_info['needs_review']}."
            )
        )

    def _extract(self, options):
        if options["file"]:
            path = Path(options["file"])
            if not path.is_file():
                raise CommandError(f"الملف غير موجود: {path}")
            try:
                with path.open("rb") as handle:
                    paragraphs = extract_docx(handle)
            except DocumentError as exc:
                raise CommandError(str(exc)) from exc
            title = options["title"] or cover_title(paragraphs) or path.stem
            return title, path.name, paragraphs
        text = options["text"].strip()
        if not text:
            raise CommandError("النص فارغ.")
        return options["title"] or "نص مباشر", "", extract_text(text)
