"""استيراد ترجمات المصطلحات بكل اللغات من CSV إلى content.GlossaryTranslation؛ بلا حذف."""

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content.models import Glossary, GlossaryTranslation
from core.models import Language

GLOSSARY_INDEX = Path(settings.BASE_DIR) / "classify" / "data" / "glossary.json"
REQUIRED = {"term_id", "tr_title", "lang"}
FIELDS = {
    "tr_idio_def": "short_def",
    "tr_brief_expl": "explanation",
    "tr_brief_ling_def": "ling_def",
    "tr_ling_def": "long_ling_def",
    "tr_fawaed": "benefits",
}
BATCH = 500
_MISSING = object()


def _clean(value) -> str:
    value = (value or "").strip()
    return "" if value == "-" else value


class Command(BaseCommand):
    help = "يستورد ترجمات المصطلحات من CSV الموسوعة إلى GlossaryTranslation (قسم المصطلحات وحده)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="ملف CSV بصيغة تصدير الموسوعة.")
        parser.add_argument("--dry-run", action="store_true", help="عرض الحصيلة بلا كتابة.")

    def handle(self, *args, **options):
        csv.field_size_limit(10_000_000)
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"الملف {path} غير موجود.")
        try:
            index = json.loads(GLOSSARY_INDEX.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"تعذّر قراءة فهرس المعجم {GLOSSARY_INDEX}: {exc}") from exc
        terms_by_id = {
            t["id"]: t for t in index if t.get("id") and t.get("dict", "terms") == "terms"
        }
        languages = {lang.iso_code.lower(): lang for lang in Language.objects.all()}
        glossaries = {g.ar: g for g in Glossary.objects.all()}
        existing = {
            (t.glossary.ar, t.language_id): t
            for t in GlossaryTranslation.objects.select_related("glossary")
        }

        stats = {
            "rows": 0,
            "skipped_not_term": 0,
            "skipped_no_lang": 0,
            "skipped_empty": 0,
            "glossary_created": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
        }
        to_create, to_update = [], []
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"الملف ينقصه الأعمدة: {', '.join(sorted(missing))}.")
            for row in reader:
                stats["rows"] += 1
                term = terms_by_id.get(row["term_id"])
                if term is None:
                    stats["skipped_not_term"] += 1
                    continue
                language = languages.get((row["lang"] or "").strip().lower())
                if language is None:
                    stats["skipped_no_lang"] += 1
                    continue
                title = _clean(row["tr_title"])
                if not title:
                    stats["skipped_empty"] += 1
                    continue

                glossary = glossaries.get(term["arabic"])
                if glossary is None:
                    agreement = term.get("en_agreement") or {}
                    glossary = Glossary(
                        ar=term["arabic"],
                        en=(term.get("english") or "").strip(),
                        category=Glossary.Category.TERM,
                        agreement_count=agreement.get("count", 0),
                        agreement_total=agreement.get("total", 0),
                        strong=bool(agreement.get("strong")),
                    )
                    if not options["dry_run"]:
                        glossary.save()
                    glossaries[glossary.ar] = glossary
                    stats["glossary_created"] += 1

                fields = {"title": title}
                for column, field in FIELDS.items():
                    fields[field] = _clean(row.get(column))
                key = (glossary.ar, language.pk)
                current = existing.get(key, _MISSING)
                if current is _MISSING:
                    to_create.append(
                        GlossaryTranslation(glossary=glossary, language=language, **fields)
                    )
                    existing[key] = None
                    stats["created"] += 1
                    continue
                if current is None:
                    continue
                changed = {k: v for k, v in fields.items() if getattr(current, k) != v}
                if not changed:
                    stats["unchanged"] += 1
                    continue
                for field, value in changed.items():
                    setattr(current, field, value)
                to_update.append(current)
                stats["updated"] += 1

        if not options["dry_run"]:
            with transaction.atomic():
                GlossaryTranslation.objects.bulk_create(to_create, batch_size=BATCH)
                GlossaryTranslation.objects.bulk_update(
                    to_update, fields=["title", *FIELDS.values()], batch_size=BATCH
                )

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}{stats['rows']:,} صفاً: {stats['created']:,} ترجمة مضافة، "
                f"{stats['updated']:,} محدَّثة، {stats['unchanged']:,} بلا تغيير، "
                f"{stats['glossary_created']:,} مدخلاً معجمياً أُنشئ — المتخطَّى: "
                f"{stats['skipped_not_term']:,} ليست مصطلحاً، "
                f"{stats['skipped_no_lang']:,} لغة مجهولة، {stats['skipped_empty']:,} بلا عنوان."
            )
        )
