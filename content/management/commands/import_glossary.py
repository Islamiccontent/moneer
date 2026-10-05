"""استيراد المعجم الموحّد إلى content.Glossary من ملف JSON؛ idempotent ولا يحذف المدخلات الغائبة."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content.models import Glossary

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "glossary_translations.json"

SYNCED_FIELDS = ("en", "category", "agreement_count", "agreement_total", "strong")

VALID_CATEGORIES = frozenset(Glossary.Category.values)


def load_entries(path):
    """يقرأ ملف المعجم JSON ويعيد قائمة ``entries`` منه."""
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise CommandError(f"تعذّر قراءة الملف {path}: {exc}") from exc
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise CommandError(f"الملف {path} لا يحوي JSON صالحاً: {exc}") from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise CommandError("صيغة الملف غير متوقعة: المطلوب كائن JSON فيه قائمة entries.")
    return entries


def normalize_entries(data, warn):
    """يحوّل عناصر المصدر إلى قاموس بمفتاح ar، متخطياً الناقص والمكرر والخارج عن المفردات."""
    limits = {
        "ar": Glossary._meta.get_field("ar").max_length,
        "en": Glossary._meta.get_field("en").max_length,
    }
    entries = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            warn(f"تخطي العنصر #{index}: ليس كائناً JSON.")
            continue
        ar = str(item.get("ar") or "").strip()
        en = str(item.get("en") or "").strip()
        category = str(item.get("category") or "").strip()
        agreement = item.get("en_agreement") or {}
        if not (ar and en and category):
            warn(f"تخطي العنصر #{index} ({ar or '?'}): ar أو en أو category فارغ.")
            continue
        if category not in VALID_CATEGORIES:
            warn(f"تخطي {ar}: الفئة {category!r} خارج المفردات المغلقة.")
            continue
        if len(ar) > limits["ar"] or len(en) > limits["en"]:
            warn(f"تخطي {ar}: ar أو en أطول من الحد المسموح في النموذج.")
            continue
        if ar in entries:
            warn(f"تخطي {ar}: مكرر في المصدر؛ اعتُمد أول ظهور.")
            continue
        try:
            count = int(agreement.get("count"))
            total = int(agreement.get("total"))
        except (TypeError, ValueError):
            warn(f"تخطي {ar}: en_agreement ناقص count أو total صحيحين.")
            continue
        entries[ar] = {
            "en": en,
            "category": category,
            "agreement_count": count,
            "agreement_total": total,
            "strong": bool(agreement.get("strong")),
        }
    return entries


class Command(BaseCommand):
    help = "يستورد المعجم الموحّد إلى جدول content.Glossary (idempotent، بلا حذف)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(DEFAULT_FILE),
            help="ملف المعجم JSON (الافتراضي content/data/glossary_translations.json).",
        )
        parser.add_argument("--dry-run", action="store_true", help="عرض التغييرات بلا كتابة.")

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        self.skipped = 0
        dry_run = options["dry_run"]
        source = options["file"]

        entries = normalize_entries(load_entries(source), self._warn)
        created = updated = unchanged = 0
        existing = {entry.ar: entry for entry in Glossary.objects.filter(ar__in=entries)}

        with transaction.atomic():
            for ar, fields in entries.items():
                entry = existing.get(ar)
                if entry is None:
                    created += 1
                    self._log(f"إضافة {ar}: {fields['en']} ({fields['category']})")
                    if not dry_run:
                        Glossary.objects.create(ar=ar, **fields)
                    continue

                changes = {
                    field: fields[field]
                    for field in SYNCED_FIELDS
                    if getattr(entry, field) != fields[field]
                }
                if not changes:
                    unchanged += 1
                    continue
                updated += 1
                details = "، ".join(
                    f"{field}: {getattr(entry, field)!r} -> {value!r}"
                    for field, value in changes.items()
                )
                self._log(f"تحديث {ar}: {details}")
                if not dry_run:
                    for field, value in changes.items():
                        setattr(entry, field, value)
                    entry.save(update_fields=list(changes))

        prefix = "[dry-run] " if dry_run else ""
        summary = (
            f"{prefix}المصدر: {source} — {len(entries)} مدخلاً صالحاً: "
            f"{created} مضاف، {updated} محدَّث، {unchanged} بلا تغيير، {self.skipped} متخطّى."
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
