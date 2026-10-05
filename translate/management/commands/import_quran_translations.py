"""استيراد ترجمات الآيات المعتمدة إلى translate.QuranAyahTranslation من ملفات quran_<iso>.xlsx."""

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from translate.importers import cell, clean_translation, read_sheet, to_int
from translate.models import QuranAyah, QuranAyahTranslation, QuranTranslationKey

REQUIRED = ("sura", "aya", "translation")
FILE_PATTERN = re.compile(r"^quran_(?P<iso>[a-z0-9-]+)\.xlsx$", re.IGNORECASE)
BATCH = 1000


class Command(BaseCommand):
    help = "يستورد ترجمات الآيات من ملفات quran_<iso>.xlsx إلى translate.QuranAyahTranslation."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--dir", help="مجلد يحوي ملفات quran_<iso>.xlsx (الافتراضي QURAN_KB_DIR)."
        )
        source.add_argument("--file", help="ملف xlsx واحد.")
        parser.add_argument("--language", help="رمز اللغة بدل استنتاجه من اسم الملف (مع --file).")
        parser.add_argument("--dry-run", action="store_true", help="عرض التغييرات بلا كتابة.")

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        self.dry_run = options["dry_run"]
        self.skipped_rows = 0
        self.totals = {"created": 0, "updated": 0, "unchanged": 0}

        self.ayah_ids = {
            (a.surah_no, a.ayah_no): a.pk
            for a in QuranAyah.objects.only("pk", "surah_no", "ayah_no")
        }
        if not self.ayah_ids:
            raise CommandError("جدول الآيات فارغ؛ شغّل import_quran_ayat أولاً.")
        self.keys = {
            k.language.iso_code: k for k in QuranTranslationKey.objects.select_related("language")
        }

        files = self._collect_files(options)
        imported = 0
        for path, iso in files:
            key = self.keys.get(iso)
            if key is None:
                self._warn(f"تخطي {path.name}: لا مفتاح ترجمة للغة {iso}؛ شغّل import_quran_keys.")
                continue
            if self._import_file(path, key):
                imported += 1

        prefix = "[dry-run] " if self.dry_run else ""
        if self.verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{prefix}{imported} من {len(files)} ملفاً: "
                    f"{self.totals['created']} مضافة، {self.totals['updated']} محدَّثة، "
                    f"{self.totals['unchanged']} بلا تغيير، {self.skipped_rows} صفاً متخطّى."
                )
            )

    def _collect_files(self, options):
        """``[(path, iso)]`` من --dir أو --file."""
        if options["file"]:
            path = Path(options["file"])
            iso = (options["language"] or "").strip().lower()
            if not iso:
                match = FILE_PATTERN.match(path.name)
                if not match:
                    raise CommandError(
                        f"تعذّر استنتاج اللغة من اسم الملف {path.name}؛ مرّر --language."
                    )
                iso = match["iso"].lower()
            return [(path, iso)]
        if options["language"]:
            raise CommandError("--language يُستخدم مع --file فقط.")
        directory = Path(options["dir"]) if options["dir"] else settings.QURAN_KB_DIR
        if not directory.is_dir():
            raise CommandError(f"المجلد غير موجود: {directory}")
        files = []
        for path in sorted(directory.iterdir()):
            match = FILE_PATTERN.match(path.name)
            if match:
                files.append((path, match["iso"].lower()))
        if not files:
            raise CommandError(f"لا ملفات quran_<iso>.xlsx في {directory}")
        return files

    def _import_file(self, path, key):
        """يستورد ملفاً واحداً؛ يعيد False إن تُخطّي الملف كله."""
        try:
            columns, rows = read_sheet(path, REQUIRED)
        except CommandError as exc:
            self._warn(f"تخطي {path.name}: {exc}")
            return False

        existing = {t.ayah_id: t for t in key.ayah_translations.all()}
        to_create, to_update, unchanged, seen = [], [], 0, set()
        for index, row in enumerate(rows, start=2):
            surah_no, ayah_no = (
                to_int(cell(row, columns, "sura")),
                to_int(cell(row, columns, "aya")),
            )
            raw = cell(row, columns, "translation")
            ayah_id = self.ayah_ids.get((surah_no, ayah_no))
            if ayah_id is None:
                self._warn(f"{path.name} صف {index}: لا آية برقم {surah_no}:{ayah_no}.")
                continue
            if not raw:
                self._warn(f"{path.name} صف {index}: ترجمة {surah_no}:{ayah_no} فارغة.")
                continue
            if ayah_id in seen:
                self._warn(f"{path.name} صف {index}: {surah_no}:{ayah_no} مكررة؛ اعتُمد أول ظهور.")
                continue
            seen.add(ayah_id)

            text = clean_translation(raw)
            text_raw = raw if raw != text else ""
            current = existing.get(ayah_id)
            if current is None:
                to_create.append(
                    QuranAyahTranslation(
                        translation_key=key, ayah_id=ayah_id, text=text, text_raw=text_raw
                    )
                )
            elif (current.text, current.text_raw) != (text, text_raw):
                current.text, current.text_raw = text, text_raw
                to_update.append(current)
            else:
                unchanged += 1

        if not self.dry_run:
            with transaction.atomic():
                QuranAyahTranslation.objects.bulk_create(to_create, batch_size=BATCH)
                QuranAyahTranslation.objects.bulk_update(
                    to_update, fields=["text", "text_raw"], batch_size=BATCH
                )

        self.totals["created"] += len(to_create)
        self.totals["updated"] += len(to_update)
        self.totals["unchanged"] += unchanged
        self._log(
            f"{path.name} ({key.key}): {len(to_create)} مضافة، {len(to_update)} محدَّثة، "
            f"{unchanged} بلا تغيير."
        )
        return True

    def _log(self, message):
        if self.verbosity >= 1:
            self.stdout.write(message)

    def _warn(self, message):
        self.skipped_rows += 1
        if self.verbosity >= 1:
            self.stderr.write(self.style.WARNING(message))
