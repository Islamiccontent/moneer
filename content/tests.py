import csv
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from core.models import ContentTypeLookup, Language
from users.models import User

from .models import (
    Document,
    DocumentTranslation,
    Glossary,
    GlossaryTranslation,
    Phrase,
    PhraseAnalysis,
    PhraseTerm,
    PhraseTranslation,
    derive_phrase_id,
)


def create_document(**overrides):
    """ينشئ مستنداً صالحاً بقيم افتراضية قابلة للتخصيص."""
    defaults = {
        "title": "خطبة عن الصبر",
        "kind": Document.Kind.KHUTBAH,
        "created_by": User.objects.first(),
    }
    defaults.update(overrides)
    return Document.objects.create(**defaults)


class ContentTestCase(TestCase):
    """أساس مشترك: مستخدم تجريبي واحد."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="translator@example.com", password="x", full_name="مترجم تجريبي"
        )


class DerivePhraseIdTests(TestCase):
    """قاعدة اشتقاق المعرّف الحتمي للعبارة."""

    def test_matches_the_spec_worked_example(self):
        self.assertEqual(
            derive_phrase_id("C3", 1, 1, "خطبة: الإخلاص وخطر الرياء"),
            "0bbedb5c-c7b8-6927-caf4-257742f1a8b4",
        )

    def test_is_deterministic_and_sensitive_to_every_input(self):
        base = derive_phrase_id("C3", 1, 1, "نص")
        self.assertEqual(base, derive_phrase_id("C3", 1, 1, "نص"))
        self.assertNotEqual(base, derive_phrase_id("C4", 1, 1, "نص"))
        self.assertNotEqual(base, derive_phrase_id("C3", 2, 1, "نص"))
        self.assertNotEqual(base, derive_phrase_id("C3", 1, 2, "نص"))
        self.assertNotEqual(base, derive_phrase_id("C3", 1, 1, "نص آخر"))


class DocumentModelTests(ContentTestCase):
    def test_str_is_title(self):
        self.assertEqual(str(create_document(title="مقال تجريبي")), "مقال تجريبي")

    def test_title_is_stripped_on_save(self):
        document = create_document(title="  منشور  ")
        document.refresh_from_db()
        self.assertEqual(document.title, "منشور")

    def test_ordering_is_newest_first(self):
        self.assertEqual(Document._meta.ordering, ["-created_at"])

    def test_invalid_kind_fails_validation(self):
        document = create_document()
        document.kind = "poem"
        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_document_can_be_created_without_a_user(self):
        document = create_document(created_by=None)
        document.full_clean()
        self.assertIsNone(document.created_by)

    def test_deleting_creator_keeps_document_and_sets_null(self):
        document = create_document()
        self.user.delete()
        document.refresh_from_db()
        self.assertIsNone(document.created_by)

    def test_source_file_name_is_optional(self):
        self.assertEqual(create_document().source_file_name, "")


class PhraseModelTests(ContentTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.document = create_document(title="C3")
        cls.text_type = ContentTypeLookup.objects.get(code="text")

    def create_phrase(self, **overrides):
        defaults = {
            "document": self.document,
            "content_type": self.text_type,
            "group_id": 1,
            "group_order": 1,
            "text": "خطبة: الإخلاص وخطر الرياء",
        }
        defaults.update(overrides)
        return Phrase.objects.create(**defaults)

    def test_phrase_id_is_derived_on_save(self):
        phrase = self.create_phrase()
        self.assertEqual(phrase.phrase_id, "0bbedb5c-c7b8-6927-caf4-257742f1a8b4")

    def test_reprocessing_the_same_phrase_collides_on_the_key(self):
        self.create_phrase()
        with self.assertRaises(IntegrityError):
            self.create_phrase()

    def test_explicit_phrase_id_is_kept(self):
        phrase = self.create_phrase(phrase_id="12345678-1234-1234-1234-123456789abc")
        self.assertEqual(phrase.phrase_id, "12345678-1234-1234-1234-123456789abc")

    def test_duplicate_slot_in_same_document_is_rejected(self):
        self.create_phrase()
        with self.assertRaises(IntegrityError):
            self.create_phrase(text="نص آخر في الموضع نفسه")

    def test_same_slot_in_different_documents_is_allowed(self):
        self.create_phrase()
        other = create_document(title="مستند آخر")
        phrase = self.create_phrase(document=other)
        self.assertEqual((phrase.group_id, phrase.group_order), (1, 1))

    def test_phrase_attributes_default_to_the_common_values(self):
        phrase = self.create_phrase()
        self.assertEqual(
            (phrase.tag, phrase.text_type, phrase.align, phrase.translatable),
            (Phrase.Tag.P, Phrase.TextType.P, Phrase.Align.RIGHT, True),
        )

    def test_invalid_tag_fails_validation(self):
        phrase = self.create_phrase(tag="div")
        with self.assertRaises(ValidationError):
            phrase.full_clean()

    def test_ordering_is_by_document_then_group_then_order(self):
        self.assertEqual(Phrase._meta.ordering, ["document", "group_id", "group_order"])

    def test_deleting_document_deletes_phrases(self):
        self.create_phrase()
        self.document.delete()
        self.assertEqual(Phrase.objects.count(), 0)

    def test_deleting_content_type_in_use_is_protected(self):
        self.create_phrase()
        with self.assertRaises(ProtectedError):
            self.text_type.delete()

    def test_str_truncates_long_text(self):
        phrase = self.create_phrase(text="كلمة " * 30)
        self.assertLessEqual(len(str(phrase)), 50)
        self.assertTrue(str(phrase).endswith("…"))


class PhraseAnalysisModelTests(ContentTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.phrase = Phrase.objects.create(
            document=create_document(),
            content_type=ContentTypeLookup.objects.get(code="text"),
            group_id=1,
            group_order=1,
            text="الحمد لله رب العالمين",
        )

    def create_analysis(self, **overrides):
        defaults = {
            "phrase": self.phrase,
            "kind": PhraseAnalysis.Kind.PLAIN,
            "reason_code": PhraseAnalysis.ReasonCode.NO_EVIDENCE,
            "confidence": 97,
        }
        defaults.update(overrides)
        return PhraseAnalysis.objects.create(**defaults)

    def test_phrase_can_have_only_one_analysis(self):
        self.create_analysis()
        with self.assertRaises(IntegrityError):
            self.create_analysis()

    def test_deleting_phrase_deletes_analysis(self):
        self.create_analysis()
        self.phrase.delete()
        self.assertEqual(PhraseAnalysis.objects.count(), 0)

    def test_confidence_is_required(self):
        analysis = PhraseAnalysis(
            phrase=self.phrase,
            kind=PhraseAnalysis.Kind.PLAIN,
            reason_code=PhraseAnalysis.ReasonCode.NO_EVIDENCE,
        )
        with self.assertRaises(ValidationError):
            analysis.full_clean()

    def test_confidence_above_100_fails_validation(self):
        analysis = self.create_analysis(confidence=101)
        with self.assertRaises(ValidationError):
            analysis.full_clean()

    def test_invalid_kind_or_reason_fails_validation(self):
        analysis = self.create_analysis(kind="verse", reason_code="guess")
        with self.assertRaises(ValidationError):
            analysis.full_clean()

    def test_kind_vocabulary_matches_the_spec(self):
        self.assertEqual(
            set(PhraseAnalysis.Kind.values),
            {
                "quran",
                "hadith",
                "athar",
                "heading",
                "author",
                "attribution",
                "citation",
                "term",
                "plain",
            },
        )

    def test_reason_code_vocabulary_matches_the_spec(self):
        self.assertEqual(
            set(PhraseAnalysis.ReasonCode.values),
            {
                "word_heading_style",
                "index_match",
                "citation_ref",
                "attribution_formula",
                "glossary_entry",
                "unmatched_quran",
                "unmatched_hadith",
                "no_evidence",
            },
        )


class GlossaryModelTests(ContentTestCase):
    def test_ar_is_stripped_and_unique(self):
        Glossary.objects.create(
            ar=" الصبر ",
            en="patience",
            category="attribute",
            agreement_count=64,
            agreement_total=84,
        )
        self.assertTrue(Glossary.objects.filter(ar="الصبر").exists())
        with self.assertRaises(IntegrityError):
            Glossary.objects.create(
                ar="الصبر",
                en="patience",
                category="attribute",
                agreement_count=1,
                agreement_total=1,
            )

    def test_invalid_category_fails_validation(self):
        entry = Glossary(
            ar="تجربة", en="test", category="noun", agreement_count=1, agreement_total=1
        )
        with self.assertRaises(ValidationError):
            entry.full_clean()

    def test_str_is_arabic_entry_and_ordering_is_by_it(self):
        self.assertEqual(str(Glossary(ar="توحيد", en="Tawhīd", category="term")), "توحيد")
        self.assertEqual(Glossary._meta.ordering, ["ar"])


class PhraseTermModelTests(ContentTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.phrase = Phrase.objects.create(
            document=create_document(),
            content_type=ContentTypeLookup.objects.get(code="text"),
            group_id=1,
            group_order=1,
            text="اصبروا واحتسبوا الأجر عند الله",
        )
        cls.entry = Glossary.objects.create(
            ar="الصبر", en="patience", category="attribute", agreement_count=64, agreement_total=84
        )

    def test_duplicate_occurrence_in_same_phrase_is_rejected(self):
        PhraseTerm.objects.create(phrase=self.phrase, glossary=self.entry)
        with self.assertRaises(IntegrityError):
            PhraseTerm.objects.create(phrase=self.phrase, glossary=self.entry)

    def test_deleting_phrase_deletes_occurrences(self):
        PhraseTerm.objects.create(phrase=self.phrase, glossary=self.entry)
        self.phrase.delete()
        self.assertEqual(PhraseTerm.objects.count(), 0)

    def test_deleting_glossary_entry_in_use_is_protected(self):
        PhraseTerm.objects.create(phrase=self.phrase, glossary=self.entry)
        with self.assertRaises(ProtectedError):
            self.entry.delete()

    def test_str_is_the_glossary_entry(self):
        occurrence = PhraseTerm.objects.create(phrase=self.phrase, glossary=self.entry)
        self.assertEqual(str(occurrence), "الصبر")


class ImportGlossaryCommandTests(ContentTestCase):
    """أمر import_glossary: استيراد idempotent من ملف JSON، بلا حذف."""

    SAMPLE = {
        "entries": [
            {
                "ar": "الصبر",
                "en": "patience",
                "category": "attribute",
                "en_agreement": {"count": 64, "total": 84, "strong": True},
            },
            {
                "ar": " توحيد ",
                "en": "Tawhīd",
                "category": "term",
                "en_agreement": {"count": 42, "total": 87, "strong": False},
            },
        ]
    }

    def run_with_file(self, data, **options):
        """يكتب البيانات في ملف مؤقت ويشغّل الأمر عليه، ويعيد (stdout, stderr)."""
        out, err = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "glossary.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            call_command("import_glossary", file=str(path), stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_creates_entries_and_strips_ar(self):
        out, err = self.run_with_file(self.SAMPLE)
        self.assertEqual(err, "")
        self.assertEqual(Glossary.objects.count(), 2)
        entry = Glossary.objects.get(ar="توحيد")
        self.assertEqual((entry.en, entry.category, entry.strong), ("Tawhīd", "term", False))
        self.assertIn("2 مضاف", out)

    def test_updates_changed_fields_only(self):
        Glossary.objects.create(
            ar="الصبر", en="old", category="term", agreement_count=1, agreement_total=1
        )
        out, _ = self.run_with_file(self.SAMPLE)
        entry = Glossary.objects.get(ar="الصبر")
        self.assertEqual((entry.en, entry.category, entry.strong), ("patience", "attribute", True))
        self.assertIn("1 محدَّث", out)

    def test_is_idempotent(self):
        self.run_with_file(self.SAMPLE)
        out, _ = self.run_with_file(self.SAMPLE)
        self.assertEqual(Glossary.objects.count(), 2)
        self.assertIn("0 مضاف، 0 محدَّث، 2 بلا تغيير", out)

    def test_dry_run_writes_nothing(self):
        out, _ = self.run_with_file(self.SAMPLE, dry_run=True)
        self.assertEqual(Glossary.objects.count(), 0)
        self.assertIn("[dry-run]", out)

    def test_skips_invalid_or_duplicate_entries_with_warnings(self):
        data = {
            "entries": [
                {"ar": "", "en": "x", "category": "term", "en_agreement": {"count": 1, "total": 1}},
                {
                    "ar": "فئة",
                    "en": "x",
                    "category": "noun",
                    "en_agreement": {"count": 1, "total": 1},
                },
                {"ar": "بلا إجماع", "en": "x", "category": "term", "en_agreement": {}},
                {
                    "ar": "سليم",
                    "en": "ok",
                    "category": "term",
                    "en_agreement": {"count": 1, "total": 2},
                },
                {
                    "ar": "سليم",
                    "en": "dup",
                    "category": "term",
                    "en_agreement": {"count": 1, "total": 2},
                },
                "ليس كائناً",
            ]
        }
        out, err = self.run_with_file(data)
        self.assertEqual(Glossary.objects.count(), 1)
        self.assertEqual(Glossary.objects.get(ar="سليم").en, "ok")
        self.assertIn("5 متخطّى", out)
        self.assertEqual(err.count("تخطي"), 5)

    def test_rejects_payload_without_entries_list(self):
        with self.assertRaises(CommandError):
            self.run_with_file({"rows": []})

    def test_import_term_translations_fills_glossary_translations(self):
        index = json.loads(
            (Path(settings.BASE_DIR) / "classify" / "data" / "glossary.json").read_text(
                encoding="utf-8"
            )
        )
        alam_id = next(
            t["id"] for t in index if t.get("id") and t.get("dict") not in (None, "terms")
        )
        Glossary.objects.create(
            ar="تقوى", en="piety", category="term", agreement_count=1, agreement_total=1
        )
        header = (
            "term_id",
            "tr_title",
            "tr_brief_ling_def",
            "tr_idio_def",
            "tr_brief_expl",
            "tr_ling_def",
            "tr_fawaed",
            "lang",
            "last_mod",
        )
        rows = [
            ("10399", "Taqwa (fr)", "-", "déf courte", "explication", "", "", "fr", "0"),
            ("900001", "Tevekkul", "", "tanım", "", "", "", "tr", "0"),
            (alam_id, "ليست مصطلحاً", "", "", "", "", "", "fr", "0"),
            ("10399", "Taqwa", "", "", "", "", "", "xx", "0"),
        ]

        def run():
            out = StringIO()
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                path = Path(tmp) / "terms.csv"
                with open(path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                    writer.writerow(header)
                    writer.writerows(rows)
                call_command("import_term_translations", file=str(path), stdout=out)
            return out.getvalue()

        out = run()
        taqwa_fr = GlossaryTranslation.objects.get(glossary__ar="تقوى", language__iso_code="fr")
        self.assertEqual(
            (taqwa_fr.title, taqwa_fr.ling_def, taqwa_fr.short_def),
            ("Taqwa (fr)", "", "déf courte"),
        )
        created = Glossary.objects.get(ar="توكل")
        self.assertEqual(created.en, "Tawakkul")
        self.assertEqual(created.translations.get(language__iso_code="tr").title, "Tevekkul")
        self.assertEqual(GlossaryTranslation.objects.count(), 2)
        self.assertIn("2 ترجمة مضافة", out)
        out = run()
        self.assertIn("0 ترجمة مضافة", out)
        self.assertEqual(GlossaryTranslation.objects.count(), 2)

    def test_import_term_translations_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "terms.csv"
            path.write_text('"term_id","lang"\n"1","fr"\n', encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "ينقصه الأعمدة"):
                call_command("import_term_translations", file=str(path), stdout=StringIO())

    def test_default_file_is_the_bundled_handoff_and_matches_its_counts(self):
        out = StringIO()
        call_command("import_glossary", stdout=out, stderr=StringIO())
        self.assertEqual(Glossary.objects.count(), 481)
        self.assertEqual(Glossary.objects.filter(strong=True).count(), 169)
        self.assertEqual(Glossary.objects.get(ar="توكل").en, "Tawakkul")

    def test_does_not_delete_entries_absent_from_source(self):
        Glossary.objects.create(
            ar="محلي", en="local", category="term", agreement_count=1, agreement_total=1
        )
        self.run_with_file(self.SAMPLE)
        self.assertTrue(Glossary.objects.filter(ar="محلي").exists())


class ContentAdminTests(ContentTestCase):
    def test_main_models_are_registered_in_admin(self):
        for model in (Document, Phrase, Glossary):
            self.assertIn(model, admin.site._registry)

    def test_analysis_and_terms_are_managed_via_inlines_only(self):
        self.assertNotIn(PhraseAnalysis, admin.site._registry)
        self.assertNotIn(PhraseTerm, admin.site._registry)
        inline_models = {inline.model for inline in admin.site._registry[Phrase].inlines}
        self.assertEqual(inline_models, {PhraseAnalysis, PhraseTerm})

    def test_translation_models_are_registered_in_admin(self):
        for model in (DocumentTranslation, PhraseTranslation):
            self.assertIn(model, admin.site._registry)

    def test_translation_inlines(self):
        document_inlines = {inline.model for inline in admin.site._registry[Document].inlines}
        self.assertIn(DocumentTranslation, document_inlines)
        translation_inlines = {
            inline.model for inline in admin.site._registry[DocumentTranslation].inlines
        }
        self.assertEqual(translation_inlines, {PhraseTranslation})

    def test_translation_admin_pages_render(self):
        boss = User.objects.create_superuser("boss@example.com", "pass-1234", full_name="م")
        self.client.force_login(boss)
        document = create_document()
        project = DocumentTranslation.objects.create(
            document=document, target_language=Language.objects.get(iso_code="en")
        )
        phrase = Phrase.objects.create(
            document=document,
            content_type=ContentTypeLookup.objects.get(code="text"),
            group_id=1,
            group_order=1,
            text="اصبروا واحتسبوا الأجر عند الله",
        )
        row = PhraseTranslation.objects.create(
            document_translation=project, phrase=phrase, ai_translation="Be patient"
        )
        for url in (
            "/admin/content/documenttranslation/",
            "/admin/content/documenttranslation/add/",
            f"/admin/content/documenttranslation/{project.pk}/change/",
            "/admin/content/phrasetranslation/",
            "/admin/content/phrasetranslation/add/",
            f"/admin/content/phrasetranslation/{row.pk}/change/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class DocumentTranslationModelTests(ContentTestCase):
    """ترجمة مستند إلى لغة هدف: واحدة لكل زوج، وتحمي اللغة وتتبع المستند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.document = create_document()
        cls.english = Language.objects.get(iso_code="en")
        cls.french = Language.objects.get(iso_code="fr")

    def create_translation(self, **overrides):
        defaults = {
            "document": self.document,
            "target_language": self.english,
            "created_by": self.user,
        }
        defaults.update(overrides)
        return DocumentTranslation.objects.create(**defaults)

    def test_defaults_and_str(self):
        translation = self.create_translation()
        self.assertEqual(translation.status, DocumentTranslation.Status.PENDING)
        self.assertEqual(translation.ai_model, "")
        self.assertIsNone(translation.reviewer)
        self.assertIsNone(translation.approved_by)
        self.assertIsNone(translation.approved_at)
        self.assertEqual(str(translation), f"{self.document.title} إلى {self.english.name}")

    def test_one_translation_per_document_and_language(self):
        self.create_translation()
        with self.assertRaises(IntegrityError):
            self.create_translation()

    def test_same_document_can_target_several_languages(self):
        self.create_translation()
        self.create_translation(target_language=self.french)
        self.assertEqual(self.document.translations.count(), 2)

    def test_invalid_status_fails_validation(self):
        translation = DocumentTranslation(
            document=self.document, target_language=self.english, status="done"
        )
        with self.assertRaises(ValidationError):
            translation.full_clean()

    def test_language_in_use_is_protected(self):
        language = Language.objects.create(iso_code="tt", name="تجريبية", name_en="Test")
        self.create_translation(target_language=language)
        with self.assertRaises(ProtectedError):
            language.delete()

    def test_deleting_document_cascades(self):
        translation = self.create_translation()
        self.document.delete()
        self.assertFalse(DocumentTranslation.objects.filter(pk=translation.pk).exists())

    def test_deleting_users_sets_null(self):
        someone = User.objects.create_user("r@example.com", "x", full_name="مراجع")
        translation = self.create_translation(
            reviewer=someone, approved_by=someone, created_by=someone
        )
        someone.delete()
        translation.refresh_from_db()
        self.assertIsNone(translation.reviewer)
        self.assertIsNone(translation.approved_by)
        self.assertIsNone(translation.created_by)

    def test_ordering_is_newest_first(self):
        self.assertEqual(DocumentTranslation._meta.ordering, ["-created_at"])


class PhraseTranslationModelTests(ContentTestCase):
    """ترجمة جملة داخل ترجمة مستند: فرادة، انتماء، اعتماد غير فارغ، ترتيب بموضع العبارة."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.document = create_document()
        cls.project = DocumentTranslation.objects.create(
            document=cls.document, target_language=Language.objects.get(iso_code="en")
        )
        cls.first = cls.make_phrase(cls.document, 1, 1, "اصبروا واحتسبوا الأجر عند الله")
        cls.second = cls.make_phrase(cls.document, 1, 2, "فإن الصبر مفتاح الفرج")

    @staticmethod
    def make_phrase(document, group_id, group_order, text):
        return Phrase.objects.create(
            document=document,
            content_type=ContentTypeLookup.objects.get(code="text"),
            group_id=group_id,
            group_order=group_order,
            text=text,
        )

    def create_row(self, phrase=None, **overrides):
        defaults = {"document_translation": self.project, "phrase": phrase or self.first}
        defaults.update(overrides)
        return PhraseTranslation.objects.create(**defaults)

    def test_defaults(self):
        row = self.create_row()
        self.assertEqual(row.status, PhraseTranslation.Status.PENDING)
        self.assertEqual((row.ai_translation, row.translation), ("", ""))
        self.assertIsNone(row.edited_by)
        self.assertIsNone(row.approved_by)
        self.assertIsNone(row.approved_at)

    def test_str_prefers_translation_then_ai_suggestion_then_placeholder(self):
        row = self.create_row()
        self.assertEqual(str(row), "(بلا ترجمة بعد)")
        row.ai_translation = "Be patient and seek reward from Allah"
        self.assertEqual(str(row), "Be patient and seek reward from Allah")
        row.translation = "word " * 20
        self.assertLessEqual(len(str(row)), 50)
        self.assertTrue(str(row).endswith("…"))

    def test_unique_per_document_translation_and_phrase(self):
        self.create_row()
        with self.assertRaises(IntegrityError):
            self.create_row()

    def test_same_phrase_can_be_translated_into_another_language(self):
        french = DocumentTranslation.objects.create(
            document=self.document, target_language=Language.objects.get(iso_code="fr")
        )
        self.create_row()
        self.create_row(document_translation=french)
        self.assertEqual(self.first.translations.count(), 2)

    def test_rejects_phrase_from_another_document(self):
        stranger = self.make_phrase(create_document(title="مقال آخر"), 1, 1, "نص غريب")
        row = PhraseTranslation(document_translation=self.project, phrase=stranger)
        with self.assertRaises(ValidationError) as caught:
            row.full_clean()
        self.assertIn("phrase", caught.exception.message_dict)

    def test_rejects_approving_without_text(self):
        for text in ("", "   "):
            with self.subTest(translation=repr(text)):
                row = PhraseTranslation(
                    document_translation=self.project,
                    phrase=self.first,
                    status=PhraseTranslation.Status.APPROVED,
                    translation=text,
                )
                with self.assertRaises(ValidationError) as caught:
                    row.full_clean()
                self.assertIn("translation", caught.exception.message_dict)

    def test_approved_with_text_is_valid(self):
        row = PhraseTranslation(
            document_translation=self.project,
            phrase=self.first,
            status=PhraseTranslation.Status.APPROVED,
            ai_translation="Be patient",
            translation="Be patient and seek the reward with Allah",
            approved_by=self.user,
        )
        row.full_clean()
        row.save()
        self.assertEqual(self.project.phrases.get().status, PhraseTranslation.Status.APPROVED)

    def test_invalid_status_fails_validation(self):
        row = PhraseTranslation(
            document_translation=self.project, phrase=self.first, status="rejected"
        )
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_ordering_follows_phrase_position(self):
        later = self.create_row(phrase=self.second)
        earlier = self.create_row(phrase=self.first)
        self.assertEqual(list(self.project.phrases.all()), [earlier, later])

    def test_deleting_document_translation_cascades(self):
        row = self.create_row()
        self.project.delete()
        self.assertFalse(PhraseTranslation.objects.filter(pk=row.pk).exists())

    def test_deleting_phrase_cascades(self):
        row = self.create_row()
        self.first.delete()
        self.assertFalse(PhraseTranslation.objects.filter(pk=row.pk).exists())

    def test_deleting_users_sets_null(self):
        someone = User.objects.create_user("e@example.com", "x", full_name="محرر")
        row = self.create_row(edited_by=someone, approved_by=someone)
        someone.delete()
        row.refresh_from_db()
        self.assertIsNone(row.edited_by)
        self.assertIsNone(row.approved_by)

    def test_reverse_relations(self):
        row = self.create_row()
        self.assertEqual(list(self.document.translations.all()), [self.project])
        self.assertEqual(list(self.project.phrases.all()), [row])
        self.assertEqual(list(self.first.translations.all()), [row])
