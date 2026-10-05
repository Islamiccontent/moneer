"""زرع آيات المصحف في translate.QuranAyah من ملف JSON مشحون مع التطبيق؛ idempotent ولا يحذف."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from translate.models import JUZ_COUNT, PAGE_COUNT, SURAH_COUNT, QuranAyah, matching_forms

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "quran_ayat.json"
BATCH = 500
TEXT_FIELDS = ("surah_name", "juz", "page", "text_uthmani", "text_imlaei")
DERIVED_FIELDS = ("clean_uthmani", "clean_imlaei", "normalized_uthmani", "normalized_imlaei")


def load_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CommandError(f"تعذّر قراءة الملف {path}: {exc}") from exc
    except ValueError as exc:
        raise CommandError(f"الملف {path} لا يحوي JSON صالحاً: {exc}") from exc
    if not isinstance(data, list):
        raise CommandError("صيغة الملف غير متوقعة: المطلوب قائمة JSON من الآيات.")
    return data


def _int_in(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def normalize_entries(data, warn):
    """يحوّل عناصر الملف إلى ``{(surah_no, ayah_no): fields}`` مع تخطي غير الصالح (بتنبيه)."""
    entries = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            warn(f"تخطي العنصر #{index}: ليس كائناً JSON.")
            continue
        surah_no, ayah_no = item.get("surah_no"), item.get("ayah_no")
        if not (_int_in(surah_no, 1, SURAH_COUNT) and _int_in(ayah_no, 1, 286)):
            warn(f"تخطي العنصر #{index}: رقم سورة أو آية غير صالح ({surah_no}:{ayah_no}).")
            continue
        fields = {
            "surah_name": str(item.get("surah_name") or "").strip(),
            "juz": item.get("juz"),
            "page": item.get("page"),
            "text_uthmani": str(item.get("uthmani") or "").strip(),
            "text_imlaei": str(item.get("imlaei") or "").strip(),
        }
        if not (fields["surah_name"] and fields["text_uthmani"] and fields["text_imlaei"]):
            warn(f"تخطي {surah_no}:{ayah_no}: اسم السورة أو أحد النصين فارغ.")
            continue
        if not (_int_in(fields["juz"], 1, JUZ_COUNT) and _int_in(fields["page"], 1, PAGE_COUNT)):
            warn(f"تخطي {surah_no}:{ayah_no}: الجزء أو الصفحة خارج النطاق.")
            continue
        if (surah_no, ayah_no) in entries:
            warn(f"تخطي {surah_no}:{ayah_no}: مكرر في الملف؛ اعتُمد أول ظهور.")
            continue
        entries[(surah_no, ayah_no)] = fields
    return entries


class Command(BaseCommand):
    help = "يزرع آيات المصحف بالرسمين في translate.QuranAyah من ملف JSON (idempotent، بلا حذف)."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_FILE), help="ملف JSON بالصيغة نفسها.")
        parser.add_argument("--dry-run", action="store_true", help="عرض التغييرات بلا كتابة.")

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        self.skipped = 0
        dry_run = options["dry_run"]

        entries = normalize_entries(load_file(options["file"]), self._warn)
        existing = {(a.surah_no, a.ayah_no): a for a in QuranAyah.objects.all()}

        to_create, to_update, unchanged = [], [], 0
        for (surah_no, ayah_no), fields in entries.items():
            derived = matching_forms(fields["text_uthmani"], fields["text_imlaei"])
            ayah = existing.get((surah_no, ayah_no))
            if ayah is None:
                to_create.append(QuranAyah(surah_no=surah_no, ayah_no=ayah_no, **fields, **derived))
                continue
            changed = {f: v for f, v in {**fields, **derived}.items() if getattr(ayah, f) != v}
            if not changed:
                unchanged += 1
                continue
            for field, value in changed.items():
                setattr(ayah, field, value)
            to_update.append(ayah)
            self._log(f"تحديث {surah_no}:{ayah_no}: {', '.join(changed)}")

        if not dry_run:
            with transaction.atomic():
                QuranAyah.objects.bulk_create(to_create, batch_size=BATCH)
                QuranAyah.objects.bulk_update(
                    to_update, fields=[*TEXT_FIELDS, *DERIVED_FIELDS], batch_size=BATCH
                )

        prefix = "[dry-run] " if dry_run else ""
        summary = (
            f"{prefix}المصدر: {options['file']} — {len(entries)} آية صالحة: "
            f"{len(to_create)} مضافة، {len(to_update)} محدَّثة، {unchanged} بلا تغيير، "
            f"{self.skipped} متخطّاة."
        )
        if self.verbosity >= 1:
            self.stdout.write(self.style.SUCCESS(summary))

    def _log(self, message):
        if self.verbosity >= 1:
            self.stdout.write(message)

    def _warn(self, message):
        self.skipped += 1
        if self.verbosity >= 1:
            self.stderr.write(self.style.WARNING(message))
