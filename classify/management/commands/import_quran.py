"""استيراد فهرس القرآن بالرسم العثماني من ICADB إلى classify/data/quran.json."""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from classify.services.normalizer import light

USER_AGENT = "moneer/0.1 (manage.py import_quran)"

TARGET = Path(__file__).resolve().parents[2] / "data" / "quran.json"

SURAH_COUNT = 114
AYA_COUNT = 6236

RECORD_FIELDS = ("surah", "surah_no", "ayah", "text")


def fetch_json(url, timeout):
    """يجلب JSON من المصدر عبر HTTP ويعيده مفكوكاً."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise CommandError(f"تعذّر الاتصال بالمصدر {url}: {exc}") from exc
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise CommandError(f"المصدر {url} لا يحوي JSON صالحاً: {exc}") from exc


def fetch_records(base_url, timeout, log):
    """سجلات الفهرس كاملةً من نقطتي ICADB، مع فحص العدّ سورةً سورة."""
    base = base_url.rstrip("/")
    surahs = fetch_json(f"{base}/surahs/", timeout)
    if not isinstance(surahs, list) or len(surahs) != SURAH_COUNT:
        raise CommandError(
            f"قائمة السور غير متوقعة: المطلوب {SURAH_COUNT} سورة، "
            f"والمصدر أعاد {len(surahs) if isinstance(surahs, list) else type(surahs).__name__}."
        )
    records = []
    for s in sorted(surahs, key=lambda s: int(s["surah_no"])):
        no = int(s["surah_no"])
        name = light(str(s.get("surah_name") or "")).strip()
        if not name:
            raise CommandError(f"السورة {no}: بلا اسم في قائمة المصدر.")
        data = fetch_json(f"{base}/surahs/{no}/ayas/", timeout)
        ayas = data.get("ayas") if isinstance(data, dict) else None
        if not isinstance(ayas, list):
            raise CommandError(f"السورة {no}: استجابة الآيات بلا قائمة «ayas».")
        expected = int(s.get("ayas_count") or 0)
        if expected and len(ayas) != expected:
            raise CommandError(f"السورة {no}: المصدر وعد بـ{expected} آية وأعاد {len(ayas)}.")
        for order, aya in enumerate(ayas, start=1):
            aya_no = int(aya.get("aya_no") or 0)
            text = str(aya.get("aya_uthmani") or "").strip()
            if aya_no != order or not text:
                raise CommandError(f"السورة {no}: الآية #{order} مختلّة الرقم أو فارغة النص.")
            records.append({"surah": name, "surah_no": no, "ayah": aya_no, "text": text})
        log(f"{no:>3} {name}: {len(ayas)} آية")
    return records


def load_records(path):
    """سجلات جاهزة من ملف محلي بالصيغة النهائية نفسها."""
    try:
        data = json.loads(Path(path).read_bytes())
    except OSError as exc:
        raise CommandError(f"تعذّر قراءة الملف {path}: {exc}") from exc
    except ValueError as exc:
        raise CommandError(f"الملف {path} لا يحوي JSON صالحاً: {exc}") from exc
    if not isinstance(data, list):
        raise CommandError("صيغة الملف غير متوقعة: المطلوب قائمة JSON من السجلات.")
    return data


def validate_records(records):
    """يتحقق أن السجلات مصحف تام: 114 سورة، 6236 آية، أرقام متتابعة بلا خلل."""
    if len(records) != AYA_COUNT:
        raise CommandError(f"الفهرس ناقص: {len(records)} آية بدل {AYA_COUNT}.")
    for index, r in enumerate(records):
        missing = [f for f in RECORD_FIELDS if not r.get(f)]
        if missing:
            raise CommandError(f"السجل #{index}: الحقل {', '.join(missing)} فارغ.")
    surah_nos = {int(r["surah_no"]) for r in records}
    missing_surahs = sorted(set(range(1, SURAH_COUNT + 1)) - surah_nos)
    if missing_surahs:
        raise CommandError(f"أرقام السور ليست 1..{SURAH_COUNT}: ينقص {missing_surahs}.")


class Command(BaseCommand):
    help = "يستورد فهرس القرآن (الرسم العثماني) من قرآن ICADB ويستبدل classify/data/quran.json."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--url",
            default=settings.ICADB_QURAN_URL,
            help="جذر قرآن ICADB (الافتراضي ICADB_QURAN_URL في settings).",
        )
        source.add_argument("--file", help="ملف JSON محلي بصيغة السجلات النهائية بدل الاتصال.")
        parser.add_argument("--dry-run", action="store_true", help="جلب وفحص بلا كتابة.")
        parser.add_argument(
            "--timeout", type=float, default=30, help="مهلة كل طلب بالثواني (الافتراضي 30)."
        )

    def handle(self, *args, **options):
        verbose = options["verbosity"] >= 2

        def log(message):
            if verbose:
                self.stdout.write(message)

        if options["file"]:
            source = options["file"]
            records = load_records(source)
        else:
            source = options["url"]
            records = fetch_records(source, options["timeout"], log)

        validate_records(records)

        surahs = len({r["surah_no"] for r in records})
        if options["dry_run"]:
            summary = (
                f"[dry-run] المصدر: {source} — {surahs} سورة، {len(records)} آية. لم يُكتب شيء."
            )
        else:
            TARGET.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            summary = f"المصدر: {source} — كُتب {TARGET.name}: {surahs} سورة، {len(records)} آية."
        if options["verbosity"] >= 1:
            self.stdout.write(self.style.SUCCESS(summary))
