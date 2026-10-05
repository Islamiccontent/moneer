"""استيراد قائمة اللغات من ICADB إلى core.Language؛ idempotent ولا يحذف اللغات الغائبة عن المصدر."""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Language

RTL_CODES = frozenset(
    {"ar", "fa", "he", "ur", "ps", "ku", "sd", "prs", "ug", "bal", "dv", "nqo", "kmr"}
)

USER_AGENT = "moneer/0.1 (manage.py import_languages)"

SYNCED_FIELDS = ("name", "name_en", "direction")


def fetch_languages(url, timeout):
    """يجلب JSON من المصدر عبر HTTP ويعيده مفكوكاً."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise CommandError(f"تعذّر الاتصال بالمصدر {url}: {exc}") from exc
    return _decode(payload, url)


def load_languages(path):
    """يقرأ JSON من ملف محلي بالصيغة نفسها (للاستخدام بلا شبكة وفي الاختبارات)."""
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise CommandError(f"تعذّر قراءة الملف {path}: {exc}") from exc
    return _decode(payload, path)


def _decode(payload, source):
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise CommandError(f"المصدر {source} لا يحوي JSON صالحاً: {exc}") from exc


def normalize_entries(data, warn):
    """يحوّل عناصر المصدر إلى {iso_code: {name, name_en, direction}} ويتخطى الناقص والمكرر."""
    if not isinstance(data, list):
        raise CommandError("صيغة المصدر غير متوقعة: المطلوب قائمة JSON من اللغات.")

    limits = {
        "iso_code": Language._meta.get_field("iso_code").max_length,
        "name": Language._meta.get_field("name").max_length,
        "name_en": Language._meta.get_field("name_en").max_length,
    }
    entries = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            warn(f"تخطي العنصر #{index}: ليس كائناً JSON.")
            continue
        code = str(item.get("iso_code") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        name_en = str(item.get("english_name") or "").strip()
        if not (code and name and name_en):
            warn(f"تخطي العنصر #{index} ({code or '?'}): iso_code أو name أو english_name فارغ.")
            continue
        too_long = [
            field
            for field, value in (("iso_code", code), ("name", name), ("name_en", name_en))
            if len(value) > limits[field]
        ]
        if too_long:
            warn(f"تخطي {code}: الحقل {', '.join(too_long)} أطول من الحد المسموح في النموذج.")
            continue
        if code in entries:
            warn(f"تخطي {code}: مكرر في المصدر؛ اعتُمد أول ظهور.")
            continue
        direction = Language.Direction.RTL if code in RTL_CODES else Language.Direction.LTR
        entries[code] = {"name": name, "name_en": name_en, "direction": direction}
    return entries


class Command(BaseCommand):
    help = "يستورد قائمة اللغات من ICADB إلى جدول core.Language (idempotent، بلا حذف)."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--url",
            default=settings.ICADB_LANGUAGES_URL,
            help="عنوان المصدر (الافتراضي ICADB_LANGUAGES_URL في settings).",
        )
        source.add_argument("--file", help="ملف JSON محلي بالصيغة نفسها بدل الاتصال بالمصدر.")
        parser.add_argument("--dry-run", action="store_true", help="عرض التغييرات بلا كتابة.")
        parser.add_argument(
            "--timeout", type=float, default=30, help="مهلة الاتصال بالثواني (الافتراضي 30)."
        )

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        self.skipped = 0
        dry_run = options["dry_run"]

        if options["file"]:
            source = options["file"]
            data = load_languages(source)
        else:
            source = options["url"]
            data = fetch_languages(source, options["timeout"])

        entries = normalize_entries(data, self._warn)
        created = updated = unchanged = 0
        existing = {lang.iso_code: lang for lang in Language.objects.filter(iso_code__in=entries)}

        with transaction.atomic():
            for code, fields in entries.items():
                language = existing.get(code)
                if language is None:
                    created += 1
                    self._log(
                        f"إضافة {code}: {fields['name']} / {fields['name_en']} "
                        f"({fields['direction']})"
                    )
                    if not dry_run:
                        Language.objects.create(iso_code=code, **fields)
                    continue

                changes = {
                    field: fields[field]
                    for field in SYNCED_FIELDS
                    if getattr(language, field) != fields[field]
                }
                if not changes:
                    unchanged += 1
                    continue
                updated += 1
                details = "، ".join(
                    f"{field}: {getattr(language, field)!r} -> {value!r}"
                    for field, value in changes.items()
                )
                self._log(f"تحديث {code}: {details}")
                if not dry_run:
                    for field, value in changes.items():
                        setattr(language, field, value)
                    language.save(update_fields=list(changes))

        prefix = "[dry-run] " if dry_run else ""
        summary = (
            f"{prefix}المصدر: {source} — {len(entries)} لغة صالحة: "
            f"{created} مضافة، {updated} محدَّثة، {unchanged} بلا تغيير، {self.skipped} متخطّاة."
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
