import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase, override_settings

from .management.commands import import_languages
from .models import ContentTypeLookup, Language


class ContentTypeLookupModelTests(TestCase):
    def test_code_is_lowercased_and_stripped_on_save(self):
        content_type = ContentTypeLookup.objects.create(id=90, code="  DUA ", name="دعاء")
        content_type.refresh_from_db()
        self.assertEqual(content_type.code, "dua")

    def test_clean_normalizes_code(self):
        content_type = ContentTypeLookup(id=91, code=" Poem ", name="شعر")
        content_type.full_clean()
        self.assertEqual(content_type.code, "poem")

    def test_duplicate_id_is_rejected(self):
        with self.assertRaises(IntegrityError):
            ContentTypeLookup.objects.create(id=1, code="ayah2", name="آية مكررة")

    def test_str_is_arabic_name(self):
        self.assertEqual(str(ContentTypeLookup(id=92, code="x", name="تجريبي")), "تجريبي")

    def test_ordering_is_by_id(self):
        self.assertEqual(ContentTypeLookup._meta.ordering, ["id"])

    def test_is_registered_in_admin(self):
        self.assertIn(ContentTypeLookup, admin.site._registry)


class InitialContentTypesMigrationTests(TestCase):
    """الأنواع السبعة تأتي من data migration لا من الإدخال اليدوي."""

    def test_the_seven_types_exist(self):
        expected = {
            1: ("ayah", "آية", True),
            2: ("hadith", "حديث", True),
            3: ("athar", "أثر", True),
            4: ("text", "نص", True),
            5: ("footnote", "هامش", False),
            6: ("heading", "العنوان", False),
            7: ("author", "المؤلف", False),
        }
        for type_id, (code, name, is_emitted) in expected.items():
            row = ContentTypeLookup.objects.get(id=type_id)
            self.assertEqual((row.code, row.name, row.is_emitted), (code, name, is_emitted))

    def test_emitted_types_are_ayah_hadith_athar_text(self):
        emitted = set(
            ContentTypeLookup.objects.filter(is_emitted=True).values_list("id", flat=True)
        )
        self.assertEqual(emitted, {1, 2, 3, 4})


class LanguageModelTests(TestCase):
    def test_iso_code_is_lowercased_and_stripped_on_save(self):
        language = Language.objects.create(
            iso_code="  PT-BR ", name="البرتغالية البرازيلية", name_en="Brazilian Portuguese"
        )
        language.refresh_from_db()
        self.assertEqual(language.iso_code, "pt-br")

    def test_clean_normalizes_iso_code(self):
        language = Language(iso_code=" SW ", name="السواحلية", name_en="Swahili")
        language.full_clean()
        self.assertEqual(language.iso_code, "sw")

    def test_iso_codes_differing_only_in_case_are_rejected(self):
        Language.objects.create(iso_code="ha", name="الهوسا", name_en="Hausa")
        with self.assertRaises(IntegrityError):
            Language.objects.create(iso_code="HA", name="الهوسا", name_en="Hausa")

    def test_direction_defaults_to_ltr(self):
        language = Language.objects.create(iso_code="es", name="الإسبانية", name_en="Spanish")
        self.assertEqual(language.direction, Language.Direction.LTR)

    def test_invalid_direction_fails_validation(self):
        language = Language(iso_code="xx", name="تجريبية", name_en="Test", direction="ttb")
        with self.assertRaises(ValidationError):
            language.full_clean()

    def test_str_is_arabic_name(self):
        language = Language(iso_code="de", name="الألمانية", name_en="German")
        self.assertEqual(str(language), "الألمانية")

    def test_ordering_is_by_arabic_name(self):
        self.assertEqual(Language._meta.ordering, ["name"])


class InitialLanguagesMigrationTests(TestCase):
    """اللغات الأولية تأتي من data migration لا من الإدخال اليدوي."""

    def test_arabic_and_english_exist(self):
        arabic = Language.objects.get(iso_code="ar")
        english = Language.objects.get(iso_code="en")
        self.assertEqual(arabic.direction, Language.Direction.RTL)
        self.assertEqual(english.direction, Language.Direction.LTR)

    def test_all_seeded_codes_are_lowercase(self):
        for code in Language.objects.values_list("iso_code", flat=True):
            self.assertEqual(code, code.lower())


class LanguageAdminTests(TestCase):
    def test_language_is_registered_in_admin(self):
        self.assertIn(Language, admin.site._registry)


class ImportLanguagesCommandTests(TestCase):
    """أمر import_languages: استيراد idempotent من ICADB أو من ملف بالصيغة نفسها، بلا حذف."""

    SAMPLE = [
        {"iso_code": "fa", "name": "الفارسية", "english_name": "Persian", "id": 1},
        {"iso_code": "de", "name": "الألمانية", "english_name": "German", "id": 2},
        {
            "iso_code": " PT-BR ",
            "name": "البرتغالية البرازيلية",
            "english_name": "Brazilian Portuguese",
        },
    ]

    def run_with_file(self, data, **options):
        """يكتب البيانات في ملف مؤقت ويشغّل الأمر عليه، ويعيد (stdout, stderr)."""
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "languages.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            call_command("import_languages", file=str(path), stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_creates_languages_and_sets_direction_from_rtl_list(self):
        before = Language.objects.count()
        out, err = self.run_with_file(self.SAMPLE)
        self.assertEqual(Language.objects.count(), before + 3)
        self.assertEqual(err, "")
        persian = Language.objects.get(iso_code="fa")
        german = Language.objects.get(iso_code="de")
        self.assertEqual(persian.direction, Language.Direction.RTL)
        self.assertEqual(german.direction, Language.Direction.LTR)
        self.assertEqual((german.name, german.name_en), ("الألمانية", "German"))
        self.assertIn("3 مضافة", out)

    def test_normalizes_iso_code_like_the_model(self):
        self.run_with_file(self.SAMPLE)
        self.assertTrue(Language.objects.filter(iso_code="pt-br").exists())

    def test_updates_changed_fields_only(self):
        Language.objects.create(iso_code="de", name="ألمانية قديمة", name_en="German")
        out, _ = self.run_with_file(self.SAMPLE)
        german = Language.objects.get(iso_code="de")
        self.assertEqual(german.name, "الألمانية")
        self.assertIn("1 محدَّثة", out)
        self.assertIn("2 مضافة", out)

    def test_is_idempotent(self):
        self.run_with_file(self.SAMPLE)
        count = Language.objects.count()
        out, _ = self.run_with_file(self.SAMPLE)
        self.assertEqual(Language.objects.count(), count)
        self.assertIn("0 مضافة، 0 محدَّثة، 3 بلا تغيير", out)

    def test_dry_run_writes_nothing(self):
        Language.objects.create(iso_code="de", name="ألمانية قديمة", name_en="German")
        before = Language.objects.count()
        out, _ = self.run_with_file(self.SAMPLE, dry_run=True)
        self.assertEqual(Language.objects.count(), before)
        self.assertEqual(Language.objects.get(iso_code="de").name, "ألمانية قديمة")
        self.assertIn("[dry-run]", out)
        self.assertIn("2 مضافة، 1 محدَّثة", out)

    def test_does_not_delete_languages_absent_from_source(self):
        seeded = set(Language.objects.values_list("iso_code", flat=True))
        self.run_with_file(self.SAMPLE)
        self.assertTrue(seeded <= set(Language.objects.values_list("iso_code", flat=True)))

    def test_skips_invalid_or_duplicate_entries_with_warnings(self):
        data = [
            {"iso_code": "", "name": "بلا رمز", "english_name": "No code"},
            {"iso_code": "zz", "name": "", "english_name": "No Arabic name"},
            {"iso_code": "yy", "name": "بلا إنجليزي"},
            {"iso_code": "x" * 13, "name": "رمز طويل", "english_name": "Too long"},
            {"iso_code": "sw", "name": "السواحلية", "english_name": "Swahili"},
            {"iso_code": "SW", "name": "مكرر", "english_name": "Duplicate"},
            "ليس كائناً",
        ]
        out, err = self.run_with_file(data)
        self.assertEqual(Language.objects.filter(iso_code__in=["zz", "yy", "x" * 13]).count(), 0)
        self.assertEqual(Language.objects.get(iso_code="sw").name, "السواحلية")
        self.assertIn("6 متخطّاة", out)
        self.assertEqual(err.count("تخطي"), 6)

    def test_rejects_payload_that_is_not_a_list(self):
        with self.assertRaises(CommandError):
            self.run_with_file({"results": self.SAMPLE})

    def test_rejects_invalid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("import_languages", file=str(path), verbosity=0)

    @override_settings(ICADB_LANGUAGES_URL="https://example.test/languages/")
    def test_default_source_is_the_settings_url(self):
        with mock.patch.object(
            import_languages, "fetch_languages", return_value=self.SAMPLE
        ) as fetch:
            call_command("import_languages", verbosity=0)
        fetch.assert_called_once_with("https://example.test/languages/", 30)
        self.assertTrue(Language.objects.filter(iso_code="fa").exists())

    def test_network_failure_is_a_command_error(self):
        with (
            mock.patch.object(import_languages, "urlopen", side_effect=URLError("boom")),
            self.assertRaises(CommandError),
        ):
            call_command("import_languages", url="https://example.test/languages/", verbosity=0)

    def test_rtl_codes_match_the_owner_list(self):
        self.assertEqual(
            import_languages.RTL_CODES,
            {"ar", "fa", "he", "ur", "ps", "ku", "sd", "prs", "ug", "bal", "dv", "nqo", "kmr"},
        )
