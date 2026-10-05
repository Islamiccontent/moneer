"""استيراد مفاتيح الترجمات المعتمدة إلى translate.QuranTranslationKey؛ مفتاح واحد لكل لغة."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from core.models import Language
from translate.importers import cell, read_sheet
from translate.models import QuranTranslationKey

REQUIRED = ("lang_iso", "key", "name")


def default_keys_file():
    """أحدث ملف ``QuranKB*.xlsx`` في ``settings.QURAN_KB_DIR`` (الأسماء المؤرَّخة تُرتَّب أبجدياً)."""
    directory = settings.QURAN_KB_DIR
    candidates = sorted(directory.glob("QuranKB*.xlsx")) if directory.is_dir() else []
    if not candidates:
        raise CommandError(f"لا ملف QuranKB*.xlsx في {directory}؛ ضع الملف هناك أو مرّر --file.")
    return candidates[-1]


class Command(BaseCommand):
    help = "يستورد مفاتيح ترجمات القرآن (لغة -> مفتاح quranenc) من ملف xlsx مصدَّر من مُلهم."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            help="ملف xlsx بأعمدة lang_iso وkey وname؛ الافتراضي أحدث QuranKB*.xlsx في المجلد.",
        )
        parser.add_argument("--dry-run", action="store_true", help="عرض التغييرات بلا كتابة.")

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        self.skipped = 0
        dry_run = options["dry_run"]

        path = options["file"] or default_keys_file()
        columns, rows = read_sheet(path, REQUIRED)
        languages = {lang.iso_code: lang for lang in Language.objects.all()}
        existing = {
            k.language_id: k for k in QuranTranslationKey.objects.select_related("language")
        }

        created = updated = unchanged = 0
        seen = set()
        with transaction.atomic():
            for index, row in enumerate(rows, start=2):
                iso = cell(row, columns, "lang_iso").lower()
                key = cell(row, columns, "key")
                name = cell(row, columns, "name")
                if not (iso and key and name):
                    self._warn(f"تخطي الصف {index}: lang_iso أو key أو name فارغ.")
                    continue
                language = languages.get(iso)
                if language is None:
                    self._warn(
                        f"تخطي الصف {index} ({key}): اللغة {iso} غير موجودة في core.Language."
                    )
                    continue
                if iso in seen:
                    self._warn(f"تخطي الصف {index}: اللغة {iso} مكررة في الملف؛ اعتُمد أول ظهور.")
                    continue
                seen.add(iso)

                current = existing.get(language.pk)
                if current is None:
                    created += 1
                    self._log(f"إضافة {iso}: {key} — {name}")
                    if not dry_run:
                        self._save(QuranTranslationKey(language=language, key=key, name=name), iso)
                    continue
                changes = {
                    f: v for f, v in (("key", key), ("name", name)) if getattr(current, f) != v
                }
                if not changes:
                    unchanged += 1
                    continue
                updated += 1
                self._log(f"تحديث {iso}: " + "، ".join(f"{f} -> {v}" for f, v in changes.items()))
                if not dry_run:
                    for field, value in changes.items():
                        setattr(current, field, value)
                    self._save(current, iso)

        prefix = "[dry-run] " if dry_run else ""
        if self.verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{prefix}المصدر: {path} — {len(seen)} مفتاح صالح: "
                    f"{created} مضاف، {updated} محدَّث، {unchanged} بلا تغيير، {self.skipped} متخطّى."
                )
            )

    def _save(self, obj, iso):
        try:
            with transaction.atomic():
                obj.save()
        except IntegrityError as exc:
            raise CommandError(
                f"المفتاح {obj.key} للغة {iso} يتعارض مع مفتاح موجود: {exc}"
            ) from exc

    def _log(self, message):
        if self.verbosity >= 1:
            self.stdout.write(message)

    def _warn(self, message):
        self.skipped += 1
        if self.verbosity >= 1:
            self.stderr.write(self.style.WARNING(message))
