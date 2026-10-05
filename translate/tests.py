import json
import tempfile
from collections import Counter
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.tasks import default_task_backend
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from content.models import (
    Document,
    DocumentTranslation,
    Glossary,
    Phrase,
    PhraseAnalysis,
    PhraseTerm,
    PhraseTranslation,
)
from core.models import ContentTypeLookup, Language
from users.models import User

from . import pipeline, tasks
from .importers import clean_translation
from .management.commands.import_quran_ayat import DEFAULT_FILE
from .models import QuranAyah, QuranAyahTranslation, QuranTranslationKey, matching_forms
from .services import examples, llm, quran_extract, text_translate
from .services.quran_match import AyahIndex, query_forms, quoted_part

_AYAT = None


def load_ayat():
    """يحمّل ملف الآيات المشحون مرة واحدة لكل تشغيل."""
    global _AYAT
    if _AYAT is None:
        _AYAT = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
    return _AYAT


def ayah_fields(surah_no, ayah_no):
    """حقول نموذج QuranAyah لآية بعينها من ملف البيانات."""
    item = next(d for d in load_ayat() if d["surah_no"] == surah_no and d["ayah_no"] == ayah_no)
    return {
        "surah_no": item["surah_no"],
        "ayah_no": item["ayah_no"],
        "surah_name": item["surah_name"],
        "juz": item["juz"],
        "page": item["page"],
        "text_uthmani": item["uthmani"],
        "text_imlaei": item["imlaei"],
    }


class TranslateUrlsTests(SimpleTestCase):
    """المسار /translate/ يعمل بلا تسجيل دخول ولا يمسّ الصفحة الرئيسية على /."""

    def test_home_url_is_served_by_pages(self):
        self.assertEqual(reverse("pages:translate"), "/translate/")
        self.assertEqual(reverse("translate:api_translate"), "/api/translate/")

    def test_home_serves_the_bundle_byte_for_byte(self):
        from pages.views import TRANSLATE_PAGE

        response = self.client.get("/translate/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(b"".join(response.streaming_content), TRANSLATE_PAGE.read_bytes())

    def test_home_rejects_unsafe_methods(self):
        self.assertEqual(self.client.post("/translate/").status_code, 405)


class QuranAyatDataFileTests(SimpleTestCase):
    """ملف translate/data/quran_ayat.json: المصحف كاملاً بالرسمين."""

    def test_file_has_every_ayah_once(self):
        ayat = load_ayat()
        pairs = [(d["surah_no"], d["ayah_no"]) for d in ayat]
        self.assertEqual(len(ayat), 6236)
        self.assertEqual(len(set(pairs)), 6236)
        per_surah = Counter(p[0] for p in pairs)
        self.assertEqual(len(per_surah), 114)
        self.assertEqual((per_surah[1], per_surah[2], per_surah[114]), (7, 286, 6))

    def test_every_row_has_both_scripts_and_positions(self):
        for d in load_ayat():
            with self.subTest(ayah=(d["surah_no"], d["ayah_no"])):
                self.assertTrue(d["uthmani"] and d["imlaei"] and d["surah_name"])
                self.assertTrue(1 <= d["juz"] <= 30)
                self.assertTrue(1 <= d["page"] <= 604)


class MatchingFormsTests(SimpleTestCase):
    """صور المطابقة: تنظيف ثم تطبيع يقرّب الرسمين."""

    def test_clean_forms_drop_diacritics_and_quran_marks(self):
        fields = ayah_fields(1, 1)
        forms = matching_forms(fields["text_uthmani"], fields["text_imlaei"])
        self.assertEqual(forms["clean_imlaei"], "بسم الله الرحمن الرحيم")
        for mark in ("ۡ", "ٰ", "َ", "ِ", "ّ"):
            self.assertNotIn(mark, forms["clean_uthmani"])

    def test_normalized_forms_agree_when_dagger_alif_is_a_written_alif(self):
        fields = ayah_fields(1, 2)
        forms = matching_forms(fields["text_uthmani"], fields["text_imlaei"])
        self.assertEqual(forms["normalized_uthmani"], forms["normalized_imlaei"])
        self.assertEqual(forms["normalized_imlaei"], "الحمد لله رب العالمين")

    def test_both_normalized_forms_are_kept_because_they_can_differ(self):
        fields = ayah_fields(1, 1)
        forms = matching_forms(fields["text_uthmani"], fields["text_imlaei"])
        self.assertEqual(forms["normalized_imlaei"], "بسم الله الرحمن الرحيم")
        self.assertNotEqual(forms["normalized_uthmani"], forms["normalized_imlaei"])


class QuranAyahModelTests(TestCase):
    def test_save_computes_matching_forms(self):
        ayah = QuranAyah.objects.create(**ayah_fields(1, 1))
        ayah.refresh_from_db()
        self.assertEqual(ayah.clean_imlaei, "بسم الله الرحمن الرحيم")
        self.assertEqual(ayah.normalized_imlaei, "بسم الله الرحمن الرحيم")
        self.assertTrue(ayah.clean_uthmani and ayah.normalized_uthmani)

    def test_str_matches_the_classifier_reference_format(self):
        self.assertEqual(str(QuranAyah(**ayah_fields(2, 153))), "سورة البقرة — 153")

    def test_unique_per_surah_and_ayah(self):
        QuranAyah.objects.create(**ayah_fields(1, 1))
        with self.assertRaises(IntegrityError):
            QuranAyah.objects.create(**ayah_fields(1, 1))

    def test_out_of_range_numbers_fail_validation(self):
        for override in ({"surah_no": 115}, {"surah_no": 0}, {"juz": 31}, {"page": 605}):
            with self.subTest(**override):
                ayah = QuranAyah(**{**ayah_fields(1, 1), **override})
                with self.assertRaises(ValidationError):
                    ayah.full_clean()

    def test_ordering_follows_the_mushaf(self):
        self.assertEqual(QuranAyah._meta.ordering, ["surah_no", "ayah_no"])


class QuranTranslationKeyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.english = Language.objects.get(iso_code="en")
        cls.french = Language.objects.get(iso_code="fr")

    def test_one_key_per_language(self):
        QuranTranslationKey.objects.create(language=self.english, key="english_saheeh", name="S")
        with self.assertRaises(IntegrityError):
            QuranTranslationKey.objects.create(
                language=self.english, key="english_hilali", name="H"
            )

    def test_key_is_unique_across_languages(self):
        QuranTranslationKey.objects.create(language=self.english, key="shared", name="A")
        with self.assertRaises(IntegrityError):
            QuranTranslationKey.objects.create(language=self.french, key="shared", name="B")

    def test_strips_key_and_name(self):
        key = QuranTranslationKey.objects.create(
            language=self.english, key="  english_saheeh ", name=" Saheeh International "
        )
        key.refresh_from_db()
        self.assertEqual((key.key, key.name), ("english_saheeh", "Saheeh International"))
        self.assertEqual(str(key), f"Saheeh International ({self.english})")

    def test_language_in_use_is_protected(self):
        language = Language.objects.create(iso_code="tt", name="تجريبية", name_en="Test")
        QuranTranslationKey.objects.create(language=language, key="test_key", name="T")
        with self.assertRaises(ProtectedError):
            language.delete()


class QuranAyahTranslationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ayah = QuranAyah.objects.create(**ayah_fields(1, 1))
        cls.key = QuranTranslationKey.objects.create(
            language=Language.objects.get(iso_code="en"), key="english_saheeh", name="Saheeh"
        )

    def create_row(self, **overrides):
        defaults = {
            "translation_key": self.key,
            "ayah": self.ayah,
            "text": "In the name of Allah, the Entirely Merciful, the Especially Merciful.",
        }
        defaults.update(overrides)
        return QuranAyahTranslation.objects.create(**defaults)

    def test_unique_per_key_and_ayah(self):
        self.create_row()
        with self.assertRaises(IntegrityError):
            self.create_row()

    def test_str_shortens_text(self):
        row = self.create_row()
        self.assertLessEqual(len(str(row)), 50)
        self.assertTrue(str(row).startswith("In the name of Allah"))

    def test_deleting_key_cascades_but_ayah_is_protected(self):
        row = self.create_row()
        with self.assertRaises(ProtectedError):
            self.ayah.delete()
        self.key.delete()
        self.assertFalse(QuranAyahTranslation.objects.filter(pk=row.pk).exists())

    def test_reverse_relations(self):
        row = self.create_row()
        self.assertEqual(list(self.key.ayah_translations.all()), [row])
        self.assertEqual(list(self.ayah.translations.all()), [row])
        self.assertEqual(self.key.language.quran_translation_key, self.key)


class ImportQuranAyatCommandTests(TestCase):
    """أمر import_quran_ayat: زرع idempotent للآيات بلا حذف."""

    SAMPLE_KEYS = [(1, 1), (1, 2)]

    def sample(self):
        return [dict(d) for d in load_ayat() if (d["surah_no"], d["ayah_no"]) in self.SAMPLE_KEYS]

    def run_with_file(self, data, **options):
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ayat.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            call_command("import_quran_ayat", file=str(path), stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_imports_the_bundled_file(self):
        out = StringIO()
        call_command("import_quran_ayat", stdout=out)
        self.assertEqual(QuranAyah.objects.count(), 6236)
        self.assertIn("6236 مضافة", out.getvalue())
        ayah = QuranAyah.objects.get(surah_no=2, ayah_no=153)
        self.assertEqual(str(ayah), "سورة البقرة — 153")
        self.assertTrue(ayah.clean_imlaei and ayah.normalized_uthmani)

    def test_is_idempotent_and_updates_only_changed_rows(self):
        data = self.sample()
        self.run_with_file(data)
        out, _ = self.run_with_file(data)
        self.assertIn("0 مضافة، 0 محدَّثة، 2 بلا تغيير", out)
        data[1]["page"] = 2
        data[1]["imlaei"] = data[1]["imlaei"] + " زيادة"
        out, _ = self.run_with_file(data)
        self.assertIn("1 محدَّثة", out)
        ayah = QuranAyah.objects.get(surah_no=1, ayah_no=2)
        self.assertEqual(ayah.page, 2)
        self.assertTrue(ayah.clean_imlaei.endswith("زيادة"), "صور المطابقة تُعاد حسابها")

    def test_dry_run_writes_nothing(self):
        out, _ = self.run_with_file(self.sample(), dry_run=True)
        self.assertEqual(QuranAyah.objects.count(), 0)
        self.assertIn("[dry-run]", out)
        self.assertIn("2 مضافة", out)

    def test_does_not_delete_rows_absent_from_file(self):
        QuranAyah.objects.create(**ayah_fields(114, 6))
        self.run_with_file(self.sample())
        self.assertEqual(QuranAyah.objects.count(), 3)

    def test_skips_invalid_entries_with_warnings(self):
        good = self.sample()[0]
        data = [
            good,
            {**good, "ayah_no": 1},
            {**good, "ayah_no": 2, "surah_no": 115},
            {**good, "ayah_no": 3, "imlaei": ""},
            {**good, "ayah_no": 4, "juz": 31},
            {**good, "ayah_no": 5, "surah_name": ""},
            "ليس كائناً",
        ]
        out, err = self.run_with_file(data)
        self.assertEqual(QuranAyah.objects.count(), 1)
        self.assertIn("6 متخطّاة", out)
        self.assertEqual(err.count("تخطي"), 6)

    def test_rejects_non_list_or_broken_json(self):
        with self.assertRaises(CommandError):
            self.run_with_file({"ayat": self.sample()})
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("[not json", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("import_quran_ayat", file=str(path), verbosity=0)


class TranslateAdminTests(TestCase):
    def test_models_are_registered(self):
        for model in (QuranAyah, QuranTranslationKey, QuranAyahTranslation):
            self.assertIn(model, admin.site._registry)

    def test_admin_pages_render(self):
        boss = User.objects.create_superuser("boss@example.com", "pass-1234", full_name="م")
        self.client.force_login(boss)
        ayah = QuranAyah.objects.create(**ayah_fields(1, 1))
        key = QuranTranslationKey.objects.create(
            language=Language.objects.get(iso_code="en"), key="english_saheeh", name="Saheeh"
        )
        row = QuranAyahTranslation.objects.create(
            translation_key=key, ayah=ayah, text="In the name"
        )
        for url in (
            "/admin/translate/quranayah/",
            "/admin/translate/quranayah/add/",
            f"/admin/translate/quranayah/{ayah.pk}/change/",
            "/admin/translate/qurantranslationkey/",
            f"/admin/translate/qurantranslationkey/{key.pk}/change/",
            "/admin/translate/quranayahtranslation/",
            f"/admin/translate/quranayahtranslation/{row.pk}/change/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


def write_xlsx(path, header, rows):
    """يكتب ورقة xlsx واحدة برؤوس وصفوف للاختبارات."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


class CleanTranslationTests(SimpleTestCase):
    """تنظيف الترجمة من أرقام الحواشي."""

    def test_strips_leading_numbers_and_bracketed_markers(self):
        self.assertEqual(clean_translation("1. In the name of Allah"), "In the name of Allah")
        self.assertEqual(clean_translation("2) Praise be to Allah"), "Praise be to Allah")
        self.assertEqual(clean_translation("3 Lord of the worlds"), "Lord of the worlds")
        self.assertEqual(clean_translation("13، «ሰዎቹ እንዳመኑት»"), "«ሰዎቹ እንዳመኑት»")
        self.assertEqual(clean_translation("4: text"), "text")
        self.assertEqual(clean_translation("Allah[1] is (2) One {3} *(4)."), "Allah is One.")

    def test_normalizes_spaces_and_trailing_dot(self):
        self.assertEqual(clean_translation("  Guide  us .  "), "Guide us.")
        self.assertEqual(clean_translation(12), "")

    def test_leaves_clean_text_unchanged(self):
        text = "In the name of Allah, the Most Compassionate, the Most Merciful."
        self.assertEqual(clean_translation(text), text)


class ImportQuranKeysCommandTests(TestCase):
    """أمر import_quran_keys: مفتاح واحد لكل لغة من تصدير QuranKB."""

    HEADER = ("id", "lang", "lang_iso", "name", "key", "version", "note")

    def run_with_rows(self, rows, header=HEADER, **options):
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = write_xlsx(Path(tmp) / "QuranKB.xlsx", header, rows)
            call_command("import_quran_keys", file=str(path), stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    ROWS = [
        (
            1,
            "إنجليزي",
            "en",
            "الترجمة الإنجليزية - مركز رواد الترجمة",
            "english_rwwad",
            "1.0.19",
            "",
        ),
        (2, "فرنسي", "FR ", "الترجمة الفرنسية - رشيد معاش", " french_rashid", "1.0.3", ""),
    ]

    def test_creates_keys_and_ignores_other_columns(self):
        out, err = self.run_with_rows(self.ROWS)
        self.assertEqual(QuranTranslationKey.objects.count(), 2)
        english = Language.objects.get(iso_code="en").quran_translation_key
        self.assertEqual(english.key, "english_rwwad")
        self.assertEqual(english.name, "الترجمة الإنجليزية - مركز رواد الترجمة")
        self.assertEqual(
            Language.objects.get(iso_code="fr").quran_translation_key.key, "french_rashid"
        )
        self.assertIn("2 مضاف", out)
        self.assertEqual(err, "")

    def test_is_idempotent_and_updates_changed_rows(self):
        self.run_with_rows(self.ROWS)
        out, _ = self.run_with_rows(self.ROWS)
        self.assertIn("0 مضاف، 0 محدَّث، 2 بلا تغيير", out)
        changed = [self.ROWS[0], (2, "فرنسي", "fr", "ترجمة أخرى", "french_other", "", "")]
        out, _ = self.run_with_rows(changed)
        self.assertIn("1 محدَّث", out)
        self.assertEqual(
            Language.objects.get(iso_code="fr").quran_translation_key.key, "french_other"
        )

    def test_dry_run_writes_nothing(self):
        out, _ = self.run_with_rows(self.ROWS, dry_run=True)
        self.assertEqual(QuranTranslationKey.objects.count(), 0)
        self.assertIn("[dry-run]", out)

    def test_skips_unknown_language_empty_cells_and_duplicates(self):
        rows = [
            *self.ROWS,
            (3, "مجهول", "zzz", "لغة غير موجودة", "zzz_key", "", ""),
            (4, "", "", "بلا رمز", "no_iso", "", ""),
            (5, "إنجليزي", "en", "مكرر", "english_dup", "", ""),
        ]
        out, err = self.run_with_rows(rows)
        self.assertEqual(QuranTranslationKey.objects.count(), 2)
        self.assertIn("3 متخطّى", out)
        self.assertEqual(err.count("تخطي"), 3)

    def test_missing_columns_or_file_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self.run_with_rows([("x", "y")], header=("lang_iso", "name"))
        with self.assertRaises(CommandError):
            call_command("import_quran_keys", file="/nonexistent/QuranKB.xlsx", verbosity=0)

    def test_default_file_is_the_newest_quran_kb_export_in_the_imports_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            write_xlsx(Path(tmp) / "QuranKB_2026-01-01.xlsx", self.HEADER, [self.ROWS[1]])
            write_xlsx(Path(tmp) / "QuranKB_2026-10-04.xlsx", self.HEADER, [self.ROWS[0]])
            with override_settings(QURAN_KB_DIR=Path(tmp)):
                call_command("import_quran_keys", verbosity=0)
        self.assertEqual(
            list(QuranTranslationKey.objects.values_list("key", flat=True)), ["english_rwwad"]
        )

    def test_default_file_missing_is_a_clear_error(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
            override_settings(QURAN_KB_DIR=Path(tmp)),
            self.assertRaisesMessage(CommandError, "QuranKB*.xlsx"),
        ):
            call_command("import_quran_keys", verbosity=0)


class ImportQuranTranslationsCommandTests(TestCase):
    """أمر import_quran_translations: ترجمات الآيات من ملفات quran_<iso>.xlsx."""

    HEADER = ("sura", "aya", "arabic_text", "translation")

    @classmethod
    def setUpTestData(cls):
        cls.ayat = {
            (1, 1): QuranAyah.objects.create(**ayah_fields(1, 1)),
            (1, 2): QuranAyah.objects.create(**ayah_fields(1, 2)),
        }
        cls.english = QuranTranslationKey.objects.create(
            language=Language.objects.get(iso_code="en"), key="english_rwwad", name="Rwwad"
        )

    def rows(self, second="Praise be to Allah, Lord of the worlds."):
        return [
            ("1", "1", "بِسۡمِ", "In the name of Allah, the Most Compassionate, the Most Merciful."),
            ("1", "2", "ٱلۡحَمۡدُ", second),
        ]

    def run_dir(self, files, **options):
        """files: {اسم الملف: الصفوف}. يعيد (stdout, stderr)."""
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for name, rows in files.items():
                write_xlsx(Path(tmp) / name, self.HEADER, rows)
            call_command("import_quran_translations", dir=tmp, stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_imports_a_directory_and_cleans_text(self):
        out, err = self.run_dir({"quran_en.xlsx": self.rows("2) Praise be to Allah [1].")})
        self.assertEqual(self.english.ayah_translations.count(), 2)
        second = self.english.ayah_translations.get(ayah=self.ayat[(1, 2)])
        self.assertEqual(second.text, "Praise be to Allah.")
        self.assertEqual(second.text_raw, "2) Praise be to Allah [1].")
        first = self.english.ayah_translations.get(ayah=self.ayat[(1, 1)])
        self.assertEqual(first.text_raw, "", "الأصل لا يُحفظ إن لم يختلف عن النص النظيف")
        self.assertIn("1 من 1 ملفاً: 2 مضافة", out)
        self.assertEqual(err, "")

    def test_is_idempotent_and_updates_changed_rows(self):
        self.run_dir({"quran_en.xlsx": self.rows()})
        out, _ = self.run_dir({"quran_en.xlsx": self.rows()})
        self.assertIn("0 مضافة، 0 محدَّثة، 2 بلا تغيير", out)
        out, _ = self.run_dir({"quran_en.xlsx": self.rows("All praise is for Allah.")})
        self.assertIn("1 محدَّثة", out)
        self.assertEqual(
            self.english.ayah_translations.get(ayah=self.ayat[(1, 2)]).text,
            "All praise is for Allah.",
        )

    def test_dry_run_writes_nothing(self):
        out, _ = self.run_dir({"quran_en.xlsx": self.rows()}, dry_run=True)
        self.assertEqual(QuranAyahTranslation.objects.count(), 0)
        self.assertIn("[dry-run]", out)

    def test_skips_files_without_a_key_and_bad_rows(self):
        rows = [
            *self.rows(),
            ("1", "2", "", "duplicate"),
            ("1", "99", "", "no such ayah"),
            ("x", "1", "", "bad number"),
            ("1", "1", "", ""),
        ]
        out, err = self.run_dir(
            {"quran_en.xlsx": rows, "quran_fr.xlsx": self.rows(), "notes.xlsx": []}
        )
        self.assertEqual(QuranAyahTranslation.objects.count(), 2)
        self.assertIn("1 من 2 ملفاً", out)
        self.assertIn("لا مفتاح ترجمة للغة fr", err)
        self.assertEqual(err.count("صف"), 4)

    def test_single_file_with_language_override(self):
        out = StringIO()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = write_xlsx(Path(tmp) / "export.xlsx", self.HEADER, self.rows())
            with self.assertRaises(CommandError):
                call_command("import_quran_translations", file=str(path), verbosity=0)
            call_command("import_quran_translations", file=str(path), language="EN", stdout=out)
        self.assertEqual(self.english.ayah_translations.count(), 2)

    def test_requires_ayat_and_rejects_bad_sources(self):
        QuranAyahTranslation.objects.all().delete()
        QuranAyah.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_quran_translations", dir="/tmp", verbosity=0)
        QuranAyah.objects.create(**ayah_fields(1, 1))
        with self.assertRaises(CommandError):
            call_command("import_quran_translations", dir="/nonexistent-dir", verbosity=0)
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
            self.assertRaises(CommandError),
        ):
            call_command("import_quran_translations", dir=tmp, verbosity=0)

    def test_default_source_is_the_imports_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            write_xlsx(Path(tmp) / "quran_en.xlsx", self.HEADER, self.rows())
            with override_settings(QURAN_KB_DIR=Path(tmp)):
                call_command("import_quran_translations", verbosity=0)
        self.assertEqual(self.english.ayah_translations.count(), 2)

    def test_file_missing_columns_is_skipped_with_warning(self):
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            write_xlsx(Path(tmp) / "quran_en.xlsx", ("sura", "translation"), [("1", "x")])
            call_command("import_quran_translations", dir=tmp, stdout=out, stderr=err)
        self.assertIn("ينقصه الأعمدة", err.getvalue())
        self.assertIn("0 من 1 ملفاً", out.getvalue())


DUMMY_TASKS = {"default": {"BACKEND": "django.tasks.backends.dummy.DummyBackend"}}
IMMEDIATE_TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
DB_TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}


def seed_ayat(*surahs):
    """يزرع سوراً بعينها من ملف البيانات في قاعدة الاختبار (بصور المطابقة المحسوبة)."""
    rows = [d for d in load_ayat() if d["surah_no"] in surahs]
    QuranAyah.objects.bulk_create(
        QuranAyah(
            surah_no=d["surah_no"],
            ayah_no=d["ayah_no"],
            surah_name=d["surah_name"],
            juz=d["juz"],
            page=d["page"],
            text_uthmani=d["uthmani"],
            text_imlaei=d["imlaei"],
            **matching_forms(d["uthmani"], d["imlaei"]),
        )
        for d in rows
    )


def ayah(surah_no, ayah_no):
    return QuranAyah.objects.get(surah_no=surah_no, ayah_no=ayah_no)


class QuranMatchTests(TestCase):
    """مطابقة جملة بآية واحدة بالرسمين: كاملة أو جزءاً منها."""

    @classmethod
    def setUpTestData(cls):
        seed_ayat(1, 2, 21, 112)

    def setUp(self):
        self.index = AyahIndex()

    def test_full_ayah_in_imlaei_is_an_exact_match(self):
        match = self.index.find(ayah(1, 1).text_imlaei)
        self.assertEqual(
            (match.reference, match.method, match.exact_full), ("سورة الفاتحة — 1", "clean", True)
        )

    def test_uthmani_script_matches(self):
        match = self.index.find(ayah(1, 2).text_uthmani)
        self.assertEqual((match.ayah.surah_no, match.ayah.ayah_no, match.exact_full), (1, 2, True))

    def test_fragment_of_an_ayah_is_a_partial_match(self):
        match = self.index.find("لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ")
        self.assertEqual((match.ayah.surah_no, match.ayah.ayah_no), (2, 255))
        self.assertFalse(match.exact_full)

    def test_quoted_part_is_used_and_intro_ignored(self):
        match = self.index.find("قال تعالى: ﴿" + ayah(1, 5).text_imlaei + "﴾ الآية.")
        self.assertEqual((match.ayah.ayah_no, match.exact_full), (5, True))

    def test_trailing_ayah_number_in_ornate_brackets_is_not_a_quote(self):
        match = self.index.find(ayah(1, 2).text_uthmani + " ﴿2﴾", reference="سورة الفاتحة — 2")
        self.assertEqual(
            (match.ayah.ayah_no, match.exact_full, match.method), (2, True, "reference")
        )
        self.assertEqual(quoted_part("نص ﴿7﴾﴾."), "نص ﴿7﴾﴾.")

    def test_undiacritized_text_matches_through_normalization(self):
        match = self.index.find("يا ايها الذين امنوا استعينوا بالصبر والصلاة ان الله مع الصابرين")
        self.assertEqual(
            (match.ayah.surah_no, match.ayah.ayah_no, match.method), (2, 153, "normalized")
        )

    def test_classifier_reference_is_the_first_anchor(self):
        match = self.index.find("كُلُّ نَفْسٍ ذَائِقَةُ الْمَوْتِ", reference="سورة الأنبياء — 35")
        self.assertEqual(
            (match.ayah.surah_no, match.ayah.ayah_no, match.method), (21, 35, "reference")
        )

    def test_wrong_reference_is_ignored_when_it_does_not_cover_the_text(self):
        match = self.index.find("لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ", reference="سورة الفاتحة — 1")
        self.assertEqual((match.ayah.surah_no, match.ayah.ayah_no, match.method), (2, 255, "clean"))

    def test_short_surah(self):
        match = self.index.find("قل هو الله أحد")
        self.assertEqual((match.ayah.surah_no, match.ayah.ayah_no), (112, 1))

    def test_text_longer_than_any_single_ayah_does_not_match(self):
        text = " ".join(ayah(1, k).text_imlaei for k in (2, 3, 4))
        self.assertIsNone(self.index.find(text))

    def test_plain_text_does_not_match(self):
        self.assertIsNone(self.index.find("هذا نص عادي من خطبة الجمعة عن الصبر والاحتساب"))
        self.assertIsNone(self.index.find(""))

    def test_query_forms_strip_brackets_digits_and_diacritics(self):
        clean, norm, norm_u = query_forms("﴿بِسْمِ اللَّهِ﴾ (1).")
        self.assertEqual((clean, norm, norm_u), ("بسم الله", "بسم الله", "بسم الله"))


class TranslationFixture(TestCase):
    """مستند بعبارات من كل صنف، ولغتان: الإنجليزية بمفتاح معتمد والفرنسية بلا مفتاح."""

    @classmethod
    def setUpTestData(cls):
        seed_ayat(1)
        cls.english = Language.objects.get(iso_code="en")
        cls.french = Language.objects.get(iso_code="fr")
        cls.key = QuranTranslationKey.objects.create(
            language=cls.english, key="english_rwwad", name="Rwwad"
        )
        for n in range(1, 8):
            QuranAyahTranslation.objects.create(
                translation_key=cls.key, ayah=ayah(1, n), text=f"EN-{n}"
            )
        cls.document = Document.objects.create(title="خطبة عن الحمد", kind=Document.Kind.KHUTBAH)
        ayah_type = ContentTypeLookup.objects.get(code="ayah")
        text_type = ContentTypeLookup.objects.get(code="text")
        cls.full = cls.make_phrase(
            1, ayah(1, 1).text_imlaei, ayah_type, "quran", "سورة الفاتحة — 1"
        )
        cls.part = cls.make_phrase(2, "يَوْمِ الدِّينِ", ayah_type, "quran", "سورة الفاتحة — 4")
        cls.text = cls.make_phrase(3, "الحمد لله على نعمة الإسلام", text_type, "plain", "")
        cls.unmatched = cls.make_phrase(4, "هذا ليس آية على الإطلاق", ayah_type, "quran", "")
        cls.fixed = cls.make_phrase(5, "[البقرة: 153]", text_type, "citation", "", False)
        islam = Glossary.objects.create(
            ar="الإسلام", en="Islam", category="term", agreement_count=3, agreement_total=3
        )
        PhraseTerm.objects.create(phrase=cls.text, glossary=islam)
        cls.dt_en = DocumentTranslation.objects.create(
            document=cls.document, target_language=cls.english
        )
        cls.dt_fr = DocumentTranslation.objects.create(
            document=cls.document, target_language=cls.french
        )

    @classmethod
    def make_phrase(cls, order, text, content_type, kind, reference, translatable=True):
        phrase = Phrase.objects.create(
            document=cls.document,
            content_type=content_type,
            group_id=1,
            group_order=order,
            text=text,
            translatable=translatable,
        )
        PhraseAnalysis.objects.create(
            phrase=phrase, kind=kind, reason_code="no_evidence", confidence=90, reference=reference
        )
        return phrase

    EXAMPLES = [{"source_text": "الحمد لله", "target_text": "Praise be to Allah"}]

    @classmethod
    def mocked_models(cls, gemini='"Gemini text"', openai='"EN extracted"'):
        return (
            mock.patch.object(llm, "gemini_generate", return_value=gemini),
            mock.patch.object(llm, "openai_generate", return_value=openai),
            mock.patch.object(examples, "relevant_examples", return_value=cls.EXAMPLES),
        )

    def run_pipeline(self, dt, gemini='"Gemini text"', openai='"EN extracted"', **options):
        gem_patch, oai_patch, ex_patch = self.mocked_models(gemini, openai)
        with gem_patch as gem, oai_patch as oai, ex_patch as ex:
            summary = pipeline.translate_document(dt, **options)
        self.examples_mock = ex
        return summary, gem, oai

    def rows(self, dt):
        return {row.phrase_id: row for row in dt.phrases.all()}


class TranslationPipelineTests(TranslationFixture):
    """التوجيه والكتابة في PhraseTranslation، بنماذج لغوية مستبدَلة."""

    @override_settings(TRANSLATE_MODEL="gemini-test", QURAN_EXTRACT_MODEL="gpt-test")
    def test_routes_every_kind_of_phrase(self):
        summary, gem, oai = self.run_pipeline(self.dt_en)
        rows = self.rows(self.dt_en)
        self.assertEqual(rows[self.full.pk].translation, "EN extracted")
        self.assertEqual(rows[self.part.pk].translation, "EN extracted")
        self.assertEqual(rows[self.text.pk].translation, "Gemini text")
        self.assertEqual(rows[self.unmatched.pk].translation, "Gemini text")
        self.assertNotIn(self.fixed.pk, rows)
        self.assertTrue(all(r.status == PhraseTranslation.Status.SUGGESTED for r in rows.values()))
        self.assertTrue(all(r.ai_translation == r.translation for r in rows.values()))
        self.assertEqual(
            {k: v for k, v in summary.counts.items() if v},
            {
                "quran_extract": 2,
                "quran_fallback": 1,
                "text": 2,
                "skipped_untranslatable": 1,
            },
        )
        self.assertEqual(oai.call_count, 2)
        prompts = [c.args[0] for c in oai.call_args_list]
        self.assertTrue(any("EN-1" in p and self.full.text in p for p in prompts))
        self.assertTrue(any("EN-4" in p and "يَوْمِ الدِّينِ" in p for p in prompts))
        self.assertEqual(gem.call_count, 2)
        text_prompt = next(c.args[0] for c in gem.call_args_list if "نعمة الإسلام" in c.args[0])
        self.assertIn(
            '**Arabic:** "الحمد لله"\n**English Translation:** "Praise be to Allah"', text_prompt
        )
        self.assertIn("particularly from Arabic to English.", text_prompt)
        self.examples_mock.assert_any_call("en", self.text.text, k=5)
        self.dt_en.refresh_from_db()
        self.assertEqual(self.dt_en.status, DocumentTranslation.Status.REVIEW)
        self.assertEqual(self.dt_en.ai_model, "gemini-test; quran: gpt-test")

    def test_language_without_approved_key_translates_ayat_as_text(self):
        summary, gem, oai = self.run_pipeline(self.dt_fr)
        oai.assert_not_called()
        self.assertEqual(gem.call_count, 4)
        self.assertEqual(summary.counts["text"], 4)
        self.assertEqual(summary.counts["quran_extract"], 0)
        self.examples_mock.assert_any_call("fr", self.text.text, k=5)
        self.assertIn("Arabic text into French", gem.call_args.args[0])

    def test_skips_approved_and_suggested_unless_forced(self):
        self.run_pipeline(self.dt_en)
        row = self.dt_en.phrases.get(phrase=self.text)
        row.status = PhraseTranslation.Status.APPROVED
        row.translation = "Human approved"
        row.save()
        summary, gem, oai = self.run_pipeline(self.dt_en, gemini='"Second run"')
        gem.assert_not_called()
        self.assertEqual(summary.counts["skipped_approved"], 1)
        self.assertEqual(summary.counts["skipped_existing"], 3)
        self.run_pipeline(self.dt_en, gemini='"Second run"', force=True)
        self.assertEqual(self.dt_en.phrases.get(phrase=self.text).translation, "Human approved")
        self.assertEqual(self.dt_en.phrases.get(phrase=self.unmatched).translation, "Second run")

    def test_dry_run_calls_no_model_and_writes_nothing(self):
        summary, gem, oai = self.run_pipeline(self.dt_en, dry_run=True)
        gem.assert_not_called()
        oai.assert_not_called()
        self.assertEqual(self.dt_en.phrases.count(), 0)
        self.assertEqual(summary.counts["quran_extract"], 2)
        self.assertTrue(any("سورة الفاتحة — 4" in line for line in summary.lines))
        self.dt_en.refresh_from_db()
        self.assertEqual(self.dt_en.status, DocumentTranslation.Status.PENDING)

    def test_model_failure_is_recorded_and_the_run_continues(self):
        with (
            mock.patch.object(llm, "gemini_generate", side_effect=llm.LLMError("quota")),
            mock.patch.object(llm, "openai_generate", return_value="EN extracted"),
        ):
            summary = pipeline.translate_document(self.dt_en)
        self.assertEqual(summary.counts["failed"], 2)
        self.assertEqual([e[0] for e in summary.errors], [self.text.pk, self.unmatched.pk])
        self.assertEqual(self.dt_en.phrases.count(), 2)
        self.dt_en.refresh_from_db()
        self.assertEqual(
            self.dt_en.status, DocumentTranslation.Status.TRANSLATING, "تبقى جارية ليستأنفها الكنس"
        )

    def test_full_ayah_with_number_is_sent_to_the_model_as_written(self):
        numbered = self.make_phrase(
            6, ayah(1, 1).text_imlaei + " ﴿1﴾", self.full.content_type, "quran", "سورة الفاتحة — 1"
        )
        summary, gem, oai = self.run_pipeline(self.dt_en, phrase_ids=[numbered.pk])
        oai.assert_called_once()
        self.assertIn('"' + numbered.text + '"', oai.call_args.args[0])
        self.assertIn("EN-1", oai.call_args.args[0])

    def test_limit_bounds_the_number_of_processed_phrases(self):
        summary, _, _ = self.run_pipeline(self.dt_en, limit=2)
        self.assertEqual(self.dt_en.phrases.count(), 2)
        self.assertTrue(summary.partial)
        self.dt_en.refresh_from_db()
        self.assertEqual(
            self.dt_en.status, DocumentTranslation.Status.TRANSLATING, "جزئي فيبقى جارياً"
        )

    def test_partial_run_by_phrase_ids_keeps_translating_until_the_sweep_completes_it(self):
        self.run_pipeline(self.dt_en, phrase_ids=[self.text.pk])
        self.dt_en.refresh_from_db()
        self.assertEqual(self.dt_en.status, DocumentTranslation.Status.TRANSLATING)
        self.run_pipeline(self.dt_en)
        self.dt_en.refresh_from_db()
        self.assertEqual(self.dt_en.status, DocumentTranslation.Status.REVIEW)
        self.assertEqual(self.dt_en.phrases.count(), 4)


class PromptBuildingTests(SimpleTestCase):
    def test_text_prompt_is_turjman_default_with_examples_block(self):
        prompt = text_translate.build_prompt(
            "نص", "English", [{"source_text": "س", "target_text": "t"}]
        )
        self.assertTrue(
            prompt.startswith(
                "\nYou are an expert translator specializing in Islamic religious texts, "
                "particularly from Arabic to English.\n"
            )
        )
        self.assertIn('**Arabic:** "س"\n**English Translation:** "t"\n\n', prompt)
        self.assertIn('Text to translate:\n"نص"\n', prompt)
        self.assertTrue(prompt.rstrip().endswith("without any additional text or explanations."))
        self.assertEqual(examples.examples_block([], "Arabic", "French"), "")
        self.assertNotIn("Unified terminology", prompt)

    def test_terms_block_unifies_glossary_equivalents(self):
        prompt = text_translate.build_prompt("نص", "English", [], terms=[("تقوى", "Taqwa")])
        self.assertIn("Unified terminology", prompt)
        self.assertIn("- تقوى → Taqwa", prompt)
        self.assertLess(prompt.index("Unified terminology"), prompt.index("Text to translate:"))

    def test_quran_prompt_is_moneer_default_with_one_approved_example(self):
        match = mock.Mock(ayah=mock.Mock(text_imlaei="مَالِكِ يَوْمِ الدِّينِ"))
        row = mock.Mock(text="Master of the Day of Judgment.")
        prompt = quran_extract.build_prompt("يَوْمِ الدِّينِ", match, row, "English")
        self.assertTrue(
            prompt.startswith(
                "You are a specialized translator of Islamic texts, tasked with translating "
                "from Arabic to English.\n"
            )
        )
        self.assertIn(
            '**Arabic:** "مَالِكِ يَوْمِ الدِّينِ"\n'
            '**English Translation:** "Master of the Day of Judgment."\n\n',
            prompt,
        )
        self.assertIn('Text to translate from Arabic to English:\n"يَوْمِ الدِّينِ"\n', prompt)
        self.assertIn("used as-is wherever they appear in the input text.", prompt)

    def test_strip_quotes(self):
        self.assertEqual(llm.strip_quotes(' "Hello" '), "Hello")
        self.assertEqual(llm.strip_quotes("“Bonjour”"), "Bonjour")


class CentralDbExamplesTests(SimpleTestCase):
    """جلب الأمثلة من ICADB؛ أي فشل يعيد قائمة فارغة."""

    def fake_response(self, body):
        response = mock.MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    @override_settings(CENTRAL_DB_URL="https://central.test/")
    def test_requests_examples_for_the_target_language(self):
        body = json.dumps(
            {
                "examples": [
                    {"source_text": "س", "target_text": "t"},
                    {"source_text": "", "target_text": "x"},
                ]
            }
        ).encode()
        with mock.patch("urllib.request.urlopen", return_value=self.fake_response(body)) as urlopen:
            result = examples.relevant_examples("en", "الحمد لله", k=2)
        self.assertEqual(result, [{"source_text": "س", "target_text": "t"}])
        url = urlopen.call_args.args[0].full_url
        self.assertTrue(
            url.startswith("https://central.test/books/api/books/relevant-examples/en/?")
        )
        self.assertIn("k=2", url)

    def test_failures_return_an_empty_list(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            self.assertEqual(examples.relevant_examples("en", "نص"), [])
        with mock.patch("urllib.request.urlopen", return_value=self.fake_response(b"not json")):
            self.assertEqual(examples.relevant_examples("en", "نص"), [])


@override_settings(GEMINI_API_KEY="g", OPENAI_API_KEY="o")
class BackgroundTaskTests(TranslationFixture):
    """إضافة لغة لمستند تُدرج مهمة ترجمة بعد commit، والكنس يستأنف غير المكتمل."""

    def create_translation(self, language):
        with self.captureOnCommitCallbacks(execute=True):
            return DocumentTranslation.objects.create(
                document=self.document, target_language=language
            )

    @override_settings(TASKS=DUMMY_TASKS)
    def test_creating_a_document_translation_enqueues_its_task_after_commit(self):
        default_task_backend.clear()
        dt = self.create_translation(Language.objects.get(iso_code="tr"))
        dt.refresh_from_db()
        self.assertEqual(dt.status, DocumentTranslation.Status.TRANSLATING)
        self.assertEqual([r.args for r in default_task_backend.results], [[dt.pk]])
        self.assertIs(default_task_backend.results[0].task.func, tasks.translate_document_task.func)

    @override_settings(TASKS=DUMMY_TASKS, GEMINI_API_KEY="")
    def test_nothing_is_enqueued_without_a_model_key(self):
        default_task_backend.clear()
        dt = self.create_translation(Language.objects.get(iso_code="tr"))
        dt.refresh_from_db()
        self.assertEqual(dt.status, DocumentTranslation.Status.PENDING)
        self.assertEqual(default_task_backend.results, [])

    @override_settings(TASKS=IMMEDIATE_TASKS)
    def test_immediate_backend_translates_on_creation(self):
        gem_patch, oai_patch, ex_patch = self.mocked_models()
        with gem_patch, oai_patch, ex_patch:
            dt = self.create_translation(Language.objects.get(iso_code="tr"))
        dt.refresh_from_db()
        self.assertEqual(dt.status, DocumentTranslation.Status.REVIEW)
        self.assertEqual(dt.phrases.count(), 4)

    @override_settings(TASKS=IMMEDIATE_TASKS)
    def test_task_reports_counts_and_handles_missing_rows(self):
        gem_patch, oai_patch, ex_patch = self.mocked_models()
        with gem_patch, oai_patch, ex_patch:
            result = tasks.translate_document_task.enqueue(self.dt_en.pk)
        self.assertEqual(result.return_value["quran_extract"], 2)
        self.assertEqual(result.return_value["errors"], 0)
        missing = tasks.translate_document_task.enqueue(999999)
        self.assertTrue(missing.return_value["missing"])

    @override_settings(TASKS=DUMMY_TASKS)
    def test_pending_sweep_enqueues_only_unfinished_translations(self):
        self.dt_fr.status = DocumentTranslation.Status.REVIEW
        self.dt_fr.save(update_fields=["status"])
        default_task_backend.clear()
        tasks.translate_pending_task.func()
        self.assertEqual([r.args for r in default_task_backend.results], [[self.dt_en.pk]])

    @override_settings(TASKS=IMMEDIATE_TASKS)
    def test_translate_pending_command_runs_the_sweep(self):
        out = StringIO()
        gem_patch, oai_patch, ex_patch = self.mocked_models()
        with gem_patch, oai_patch, ex_patch:
            call_command("translate_pending", stdout=out)
        self.assertIn("عولجت 2 ترجمة مستند", out.getvalue())
        self.dt_en.refresh_from_db()
        self.assertEqual(self.dt_en.status, DocumentTranslation.Status.REVIEW)

    @override_settings(GEMINI_API_KEY="")
    def test_translate_pending_command_requires_a_key(self):
        with self.assertRaisesMessage(CommandError, "GEMINI_API_KEY"):
            call_command("translate_pending", verbosity=0)


class TranslateApiTests(TranslationFixture):
    """واجهة /api/translate/ بمرحلتيها: تصنيف أولاً ثم ترجمة ناتجه — بنماذج مستبدَلة."""

    def post_mocked(self, url, payload):
        import os

        gem_patch, oai_patch, ex_patch = self.mocked_models()
        env = mock.patch.dict(os.environ, {"LLM_REVIEW": "0", "LLM_HEADINGS": "0"})
        with env, gem_patch, oai_patch, ex_patch:
            return self.client.post(url, payload)

    def test_api_classifies_then_translates_in_two_phases(self):
        response = self.post_mocked(
            "/api/translate/",
            {
                "text": "قال الله تعالى: ﴿مَالِكِ يَوْمِ الدِّينِ﴾. والصبر خير معين للمؤمن في الشدائد كلها.",
                "target": "English",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        kinds = [s["k"] for s in data["segments"]]
        self.assertIn("aya", kinds)
        self.assertTrue(all(not s["en"] for s in data["segments"]))
        lead = next(s for s in data["segments"] if s.get("lead"))
        self.assertIn("قال الله تعالى", lead["ar"])
        self.assertEqual(lead["tagLabel"], "نص عام")

        response = self.post_mocked(
            "/api/translate/run/", {"doc_id": data["doc_id"], "target": "English"}
        )
        self.assertEqual(response.status_code, 200)
        done = response.json()
        self.assertEqual(done["failed"], 0)
        aya = next(s for s in done["segments"] if s["k"] == "aya")
        self.assertTrue(aya["locked"])
        self.assertFalse(aya["ai"])
        self.assertEqual(aya["en"], "EN extracted")
        prose = [s for s in done["segments"] if s["k"] == "text" and s.get("en")]
        self.assertTrue(any(s["en"] == "Gemini text" for s in prose))
        live = self.client.get("/api/translate/progress/").json()
        self.assertIn("Gemini text", live["rows"].values())
        aya_index = str(done["segments"].index(aya))
        self.assertEqual(live["sources"][aya_index], {"src": "الترجمة المعتمدة", "locked": True})
        document = Document.objects.get(pk=done["doc_id"])
        self.assertEqual(
            DocumentTranslation.objects.get(pk=done["translation_id"]).document, document
        )

    def test_api_rejects_an_unknown_language(self):
        response = self.post_mocked("/api/translate/", {"text": "نص قصير.", "target": "Klingon"})
        self.assertEqual(response.status_code, 400)

    def test_api_requires_input(self):
        response = self.post_mocked("/api/translate/", {"text": "", "target": "English"})
        self.assertEqual(response.status_code, 400)


class DocumentBrowsingApiTests(TranslationFixture):
    """روابط المحتوى: قائمة المستندات بمراحلها، وحالة مستند واحد لرابطه الدائم."""

    def test_documents_list_shows_stage_and_links(self):
        response = self.client.get("/api/translate/documents/")
        self.assertEqual(response.status_code, 200)
        docs = response.json()["documents"]
        row = next(d for d in docs if d["id"] == self.document.pk)
        self.assertEqual(row["title"], "خطبة عن الحمد")
        self.assertEqual(row["url"], f"/translate/documents/{self.document.pk}/")
        self.assertEqual(row["json_url"], f"/classify/documents/{self.document.pk}.json")
        self.assertEqual(row["stage"], self.dt_fr.get_status_display())
        self.assertEqual(len(row["translations"]), 2)

    def test_document_detail_returns_segments_with_latest_translation(self):
        PhraseTranslation.objects.create(
            document_translation=self.dt_fr,
            phrase=self.text,
            ai_translation="Louange",
            translation="Louange",
            status=PhraseTranslation.Status.SUGGESTED,
        )
        with mock.patch.object(llm, "gemini_generate", return_value="{}"):
            response = self.client.get(f"/api/translate/documents/{self.document.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["doc_id"], self.document.pk)
        self.assertEqual(data["target_language"], self.french.name)
        self.assertEqual(data["target_iso"], "fr")
        translated = next(s for s in data["segments"] if s["en"])
        self.assertEqual(translated["en"], "Louange")
        self.assertNotIn("terms", translated)
        citation = next(s for s in data["segments"] if "البقرة" in s["ar"])
        self.assertEqual(citation["tagLabel"], "عزو")

    def test_languages_endpoint_lists_only_approved_translation_languages(self):
        response = self.client.get("/api/translate/languages/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["languages"]
        self.assertIn({"name": self.english.name, "iso": "en"}, rows)
        self.assertNotIn("fr", [r["iso"] for r in rows])

    def test_target_is_accepted_as_iso_or_db_name(self):
        from translate.views import _language_or_error

        self.assertEqual(_language_or_error("en")[0], self.english)
        self.assertEqual(_language_or_error(self.english.name)[0], self.english)
        self.assertEqual(_language_or_error("English")[0], self.english)
        self.assertIsNone(_language_or_error("Klingon")[0])

    def test_unknown_document_is_404(self):
        self.assertEqual(self.client.get("/api/translate/documents/999999/").status_code, 404)

    def test_gemini_localizes_term_highlight_for_non_english(self):
        from translate.services import term_match

        segments = [
            {
                "en": "La confiance en Allah est la voie.",
                "terms": [{"w": "التوكل", "en": "Tawakkul", "def": "", "tr": ""}],
            },
            {"en": "Rien ici.", "terms": [{"w": "تقوى", "en": "piety", "def": "", "tr": ""}]},
        ]
        with mock.patch.object(
            llm, "gemini_generate", return_value='{"1": "La confiance en Allah", "2": "absent"}'
        ):
            term_match.localize_terms(segments, self.french)
        self.assertEqual(segments[0]["terms"][0]["en"], "La confiance en Allah")
        self.assertEqual(segments[0]["terms"][0]["tr"], "English: Tawakkul")
        self.assertEqual(segments[1]["terms"][0]["en"], "piety")
        term_match.prune_unmatched(segments)
        self.assertEqual(len(segments[0]["terms"]), 1)
        self.assertNotIn("terms", segments[1])

    def test_term_localization_failure_is_silent(self):
        from translate.services import term_match

        segments = [{"en": "Texte.", "terms": [{"w": "تقوى", "en": "piety", "def": "", "tr": ""}]}]
        with mock.patch.object(llm, "gemini_generate", side_effect=llm.LLMError("down")):
            term_match.localize_terms(segments, self.french)
        self.assertEqual(segments[0]["terms"][0]["en"], "piety")

    def test_vocalized_term_surface_is_returned_for_highlighting(self):
        text_type = ContentTypeLookup.objects.get(code="text")
        phrase = self.make_phrase(9, "فَالتَّقْوَى خَيْرُ زَادٍ ليوم المعاد.", text_type, "plain", "")
        taqwa = Glossary.objects.create(
            ar="تقوى", en="Taqwa", category="term", agreement_count=1, agreement_total=1
        )
        PhraseTerm.objects.create(phrase=phrase, glossary=taqwa)
        data = self.client.get(f"/api/translate/documents/{self.document.pk}/").json()
        row = next(s for s in data["segments"] if "خَيْرُ" in s["ar"])
        self.assertEqual(row["terms"][0]["w"], "فَالتَّقْوَى")
        self.assertIn(row["terms"][0]["w"], row["ar"])
        self.assertEqual(row["terms"][0]["en"], "Taqwa")

    def test_terms_use_stored_translation_for_target_language(self):
        from content.models import GlossaryTranslation
        from translate.services import moneer_ui

        islam = Glossary.objects.get(ar="الإسلام")
        GlossaryTranslation.objects.create(
            glossary=islam, language=self.french, title="L'islam", short_def="La religion"
        )
        segments = moneer_ui.to_ui_segments(self.document, self.dt_fr)
        row = next(s for s in segments if "نعمة" in s["ar"])
        term = row["terms"][0]
        self.assertEqual(term["w"], "الإسلام")
        self.assertEqual(term["en"], "L'islam")
        self.assertEqual(term["def"], "La religion")
        self.assertEqual(term["tr"], "English: Islam")
        self.assertEqual(pipeline._term_pairs(self.text, self.french), [("الإسلام", "L'islam")])
        self.assertEqual(pipeline._term_pairs(self.text, self.english), [("الإسلام", "Islam")])

    def test_verified_terms_are_shown_from_the_glossary(self):
        from translate.services import moneer_ui, term_match

        def unit(k, en):
            islam = {"w": "الإسلام", "en": "Islam", "def": "", "tr": ""}
            return {"k": k, "en": en, "ai": True, "terms": [islam]}

        segments = [
            unit("term", "The blessing of Islam."),
            unit("term", "A blessing."),
            unit("hadith", "Islam is built on five."),
        ]
        term_match.prune_unmatched(segments)
        moneer_ui.mark_approved_terms(segments)
        self.assertFalse(segments[0]["ai"])
        self.assertEqual(segments[0]["src"], moneer_ui.GLOSSARY_SOURCE)
        self.assertTrue(segments[1]["ai"])
        self.assertTrue(segments[2]["ai"])

    def test_live_source_marks_approved_ayat_and_terms(self):
        from translate.services.moneer_ui import GLOSSARY_SOURCE, QURAN_SOURCE, live_source

        self.assertEqual(
            live_source(self.full, "EN", "quran_extract", self.english),
            {"src": QURAN_SOURCE, "locked": True},
        )
        self.assertEqual(live_source(self.unmatched, "No ayah", "quran_fallback", self.english), {})
        self.assertEqual(
            live_source(self.text, "Praise for the blessing of Islam", "text", self.english),
            {"src": GLOSSARY_SOURCE},
        )
        self.assertEqual(live_source(self.text, "Praise for blessings", "text", self.english), {})

    def test_prefixed_term_surface_is_the_full_word(self):
        from translate.services.moneer_ui import _surface

        self.assertEqual(_surface("عليكم بالصبر والتوكل على الله.", "توكل"), "والتوكل")
        self.assertEqual(_surface("ويقترن بالتوكل والتقوى.", "تقوى"), "والتقوى")
        self.assertEqual(_surface("فَالتَّقْوَى خَيْرُ زَادٍ.", "تقوى"), "فَالتَّقْوَى")
        self.assertEqual(_surface("زكاة الفطر واجبة.", "زكاة الفطر"), "زكاة الفطر")


class ApproveApiTests(TranslationFixture):
    """زر «اعتماد» في المراجعة: يحفظ نص المراجع وحالته، ويُلغى، ويبقى بعد إعادة فتح المستند."""

    def setUp(self):
        self.row = PhraseTranslation.objects.create(
            document_translation=self.dt_fr,
            phrase=self.text,
            ai_translation="Louange",
            translation="Louange",
            status=PhraseTranslation.Status.SUGGESTED,
        )

    def approve(self, phrase_id, approved="1", text=""):
        payload = {"translation_id": self.dt_fr.pk, "phrase_id": phrase_id, "approved": approved}
        return self.client.post("/api/translate/approve/", {**payload, "text": text})

    def test_approve_saves_reviewer_text_and_who_approved(self):
        reviewer = User.objects.create_user("rev@example.com", "x", full_name="مراجع")
        self.client.force_login(reviewer)
        response = self.approve(self.text.pk, text="Louange à Allah")
        self.assertEqual(response.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, PhraseTranslation.Status.APPROVED)
        self.assertEqual(self.row.translation, "Louange à Allah")
        self.assertEqual(self.row.ai_translation, "Louange")
        self.assertEqual(self.row.approved_by, reviewer)
        self.assertEqual(self.row.edited_by, reviewer)
        self.assertIsNotNone(self.row.approved_at)

    def test_approval_survives_reopening_the_document(self):
        self.approve(self.text.pk, text="Louange à Allah")
        with mock.patch.object(llm, "gemini_generate", return_value="{}"):
            data = self.client.get(f"/api/translate/documents/{self.document.pk}/").json()
        self.assertEqual(data["translation_id"], self.dt_fr.pk)
        rows = {s["id"]: s for s in data["segments"]}
        self.assertTrue(rows[self.text.pk]["approved"])
        self.assertEqual(rows[self.text.pk]["en"], "Louange à Allah")
        self.assertFalse(rows[self.full.pk]["approved"])

    def test_unapprove_returns_the_row_to_suggested(self):
        self.approve(self.text.pk, text="Louange")
        response = self.approve(self.text.pk, approved="0")
        self.assertFalse(response.json()["approved"])
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, PhraseTranslation.Status.SUGGESTED)
        self.assertIsNone(self.row.approved_at)

    def test_empty_translation_cannot_be_approved(self):
        response = self.approve(self.full.pk)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PhraseTranslation.objects.filter(phrase=self.full).exists())

    def test_untranslatable_phrase_is_approved_as_is_and_cleared_on_unapprove(self):
        self.approve(self.fixed.pk)
        row = PhraseTranslation.objects.get(document_translation=self.dt_fr, phrase=self.fixed)
        self.assertEqual(row.translation, self.fixed.text)
        self.assertEqual(row.status, PhraseTranslation.Status.APPROVED)
        self.approve(self.fixed.pk, approved="0")
        self.assertFalse(PhraseTranslation.objects.filter(phrase=self.fixed).exists())

    def test_phrase_outside_the_translated_document_is_404(self):
        other = Document.objects.create(title="مستند آخر", kind=Document.Kind.KHUTBAH)
        stranger = Phrase.objects.create(
            document=other,
            content_type=ContentTypeLookup.objects.get(code="text"),
            group_id=1,
            group_order=1,
            text="نص من مستند آخر",
        )
        self.assertEqual(self.approve(stranger.pk, text="x").status_code, 404)
        self.assertEqual(self.approve("missing", text="x").status_code, 404)

    def test_approve_rejects_get(self):
        self.assertEqual(self.client.get("/api/translate/approve/").status_code, 405)
