import os
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from content.models import Document, Glossary, Phrase, PhraseAnalysis, PhraseTerm, derive_phrase_id

os.environ["LLM_REVIEW"] = "0"
os.environ["LLM_HEADINGS"] = "0"

SAMPLE_TEXT = """الإخلاص في العمل

الحمد لله رب العالمين، والصلاة والسلام على رسول الله.
قال الله تعالى: ﴿فإن مع العسر يسرا﴾.
فعليكم بالصبر والإخلاص في الأعمال كلها، والله الموفق."""


def run(**options):
    out = StringIO()
    call_command("classify_document", stdout=out, stderr=StringIO(), **options)
    return out.getvalue()


class ClassifyDocumentCommandTests(TestCase):
    """أمر classify_document: خط التقطيع والتصنيف كاملاً حتى الحفظ في content."""

    def test_text_is_classified_and_saved_into_content(self):
        out = run(text=SAMPLE_TEXT, title="نص الإخلاص")
        document = Document.objects.get(title="نص الإخلاص")
        self.assertGreater(document.phrases.count(), 0)
        self.assertEqual(
            document.phrases.count(),
            PhraseAnalysis.objects.filter(phrase__document=document).count(),
        )
        self.assertIn("حُفظ المستند", out)

    def test_phrase_ids_follow_the_deterministic_rule(self):
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        for phrase in Phrase.objects.all():
            self.assertEqual(
                phrase.phrase_id,
                derive_phrase_id(
                    phrase.document.title, phrase.group_id, phrase.group_order, phrase.text
                ),
            )

    def test_vocabularies_stay_within_the_closed_sets(self):
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        kinds = set(PhraseAnalysis.objects.values_list("kind", flat=True))
        self.assertTrue(kinds <= set(PhraseAnalysis.Kind.values))
        reasons = set(PhraseAnalysis.objects.values_list("reason_code", flat=True))
        self.assertTrue(reasons <= set(PhraseAnalysis.ReasonCode.values))
        types = set(Phrase.objects.values_list("content_type_id", flat=True))
        self.assertTrue(types <= {1, 2, 3, 4})

    def test_confidence_is_a_percent(self):
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        for value in PhraseAnalysis.objects.values_list("confidence", flat=True):
            self.assertTrue(0 <= value <= 100)

    def test_duplicate_title_is_rejected_without_replace(self):
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        with self.assertRaises(CommandError):
            run(text=SAMPLE_TEXT, title="نص الإخلاص")

    def test_replace_substitutes_the_previous_document(self):
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        run(text=SAMPLE_TEXT, title="نص الإخلاص", replace=True)
        self.assertEqual(Document.objects.filter(title="نص الإخلاص").count(), 1)

    def test_detected_terms_are_linked_to_existing_glossary_entries(self):
        entry = Glossary.objects.create(
            ar="صبر", en="patience", category="term", agreement_count=64, agreement_total=84
        )
        run(text=SAMPLE_TEXT, title="نص الإخلاص")
        self.assertTrue(PhraseTerm.objects.filter(glossary=entry).exists())

    def test_empty_text_is_rejected(self):
        with self.assertRaises(CommandError):
            run(text="   ", title="فارغ")

    def test_missing_file_is_rejected(self):
        with self.assertRaises(CommandError):
            run(file="لا-وجود-له.docx")


class ClassifyPagesTests(TestCase):
    """صفحات /classify: الواجهة كما هي، والواجهة البرمجية، والتصديران من content."""

    def test_home_serves_the_bundle_byte_for_byte(self):
        from pages.views import CLASSIFY_PAGE

        response = self.client.get("/classify/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), CLASSIFY_PAGE.read_bytes())

    def test_api_segment_classifies_saves_and_returns_ui_segments(self):
        response = self.client.post("/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(Document.objects.filter(pk=data["doc_id"], title="نص الواجهة").exists())
        self.assertGreater(len(data["segments"]), 0)
        self.assertIn("aya", {segment["k"] for segment in data["segments"]})
        self.assertTrue(data["json_url"].startswith("/classify/documents/"))

    def test_api_segment_keeps_documents_with_the_same_title(self):
        first = self.client.post("/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"})
        second = self.client.post("/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"})
        third = self.client.post("/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"})
        ids = {r.json()["doc_id"] for r in (first, second, third)}
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(Document.objects.filter(pk=pk).exists() for pk in ids))
        self.assertEqual(
            set(Document.objects.filter(pk__in=ids).values_list("title", flat=True)),
            {"نص الواجهة", "نص الواجهة (2)", "نص الواجهة (3)"},
        )

    def test_api_segment_without_input_is_rejected(self):
        response = self.client.post("/api/segment/", {})
        self.assertEqual(response.status_code, 400)

    def test_document_json_rebuilds_the_contract_from_content(self):
        doc_id = self.client.post(
            "/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"}
        ).json()["doc_id"]
        data = self.client.get(f"/classify/documents/{doc_id}.json").json()
        self.assertEqual(data["api_version"], "2.0")
        self.assertEqual(data["document"]["phrases"], len(data["phrases"]))
        saved = dict(Phrase.objects.filter(document_id=doc_id).values_list("phrase_id", "text"))
        for row in data["phrases"]:
            self.assertEqual(saved[row["phrase_id"]], row["arabic_text"])

    def test_document_xlsx_export_from_content(self):
        doc_id = self.client.post(
            "/api/segment/", {"text": SAMPLE_TEXT, "title": "نص الواجهة"}
        ).json()["doc_id"]
        response = self.client.get(f"/classify/documents/{doc_id}/export.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))

    def test_landing_page_is_untouched(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


class QuranPrecedenceTests(TestCase):
    """قاعدة أسبقية المصحف: ما قبله فهرس القرآن لا يبقى حديثاً أو أثراً."""

    def test_a_hadith_claim_matching_the_mushaf_becomes_quran(self):
        from classify.pipeline import StoredSegment, enforce_quran_precedence

        segment = StoredSegment(
            kind="hadith",
            content="إن مع العسر يسرا",
            source="سنن الترمذي — 66522",
            score=0.9,
            para=1,
            level=0,
        )
        self.assertEqual(enforce_quran_precedence([segment]), 1)
        self.assertEqual(segment.kind, "quran")
        self.assertIn("سورة الشرح", segment.source)
        self.assertIn("أسبقية المصحف", segment.note)

    def test_a_real_hadith_stays_hadith(self):
        from classify.pipeline import StoredSegment, enforce_quran_precedence

        segment = StoredSegment(
            kind="hadith",
            content="ليس الشديد بالصرعة إنما الشديد الذي يملك نفسه عند الغضب",
            source="صحيح البخاري — 6114",
            score=0.95,
            para=1,
            level=0,
        )
        self.assertEqual(enforce_quran_precedence([segment]), 0)
        self.assertEqual(segment.kind, "hadith")
        self.assertEqual(segment.source, "صحيح البخاري — 6114")

    def test_other_kinds_are_not_touched(self):
        from classify.pipeline import StoredSegment, enforce_quran_precedence

        segment = StoredSegment(
            kind="text", content="إن مع العسر يسرا", source="", score=None, para=1, level=0
        )
        self.assertEqual(enforce_quran_precedence([segment]), 0)
        self.assertEqual(segment.kind, "text")


class ReferenceStoragePolicyTests(TestCase):
    """سياسة التخزين: مرجع الآية يُحفظ، ومرجعا الحديث والأثر لا يُحفظان."""

    def _save(self, kind, source):
        from classify.pipeline import StoredSegment, save_document

        segment = StoredSegment(
            kind=kind, content="نص تجريبي للسياسة", source=source, score=0.95, para=1, level=0
        )
        document, _ = save_document("سياسة المراجع", "article", "", [segment], replace=True)
        return PhraseAnalysis.objects.get(phrase__document=document)

    def test_quran_reference_is_saved(self):
        analysis = self._save("quran", "سورة البقرة — 153")
        self.assertEqual(analysis.reference, "سورة البقرة — 153")

    def test_hadith_reference_is_not_saved(self):
        analysis = self._save("hadith", "صحيح البخاري — 6114")
        self.assertEqual(analysis.reference, "")

    def test_athar_reference_is_not_saved(self):
        analysis = self._save("athar", "مصنف ابن أبي شيبة — 123")
        self.assertEqual(analysis.reference, "")


class SpeakerAttributionTests(TestCase):
    """نسبة القول لقائله: الصحابي الراوي في «عن فلان أنَّ النبي ﷺ قال» ليس هو القائل."""

    def test_narration_formula_resolves_to_the_prophet(self):
        from classify.services.speaker import speaker_of

        self.assertEqual(
            speaker_of("عن أبي هُرَيرَة رضي الله عنه، أنَّ النبيَّ صلَّى الله عليه وسلَّم قال:"),
            "prophet",
        )
        self.assertEqual(
            speaker_of("عن عُبادةَ بنِ الصامتِ رضي الله عنه، أنَّ النبيَّ صلَّى الله عليه وسلَّم قال:"),
            "prophet",
        )

    def test_heard_the_prophet_formula_resolves_to_the_prophet(self):
        from classify.services.speaker import speaker_of

        self.assertEqual(
            speaker_of("عن أبي هريرة رضي الله عنه قال: سمعت رسول الله صلى الله عليه وسلم يقول:"),
            "prophet",
        )

    def test_narration_chain_resolves_to_the_prophet(self):
        from classify.services.speaker import speaker_of

        self.assertEqual(
            speaker_of(
                "عَنْ أَبِي سَعِيدٍ الْخُدْرِيِّ وَعَنْ أَبِي هُرَيْرَةَ رضي الله عنهما عَنِ النَّبِيِّ صلى الله عليه وسلم قَالَ:"
            ),
            "prophet",
        )

    def test_multi_narrator_isnad_is_an_attribution(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        intro = "عَنْ أَبِي سَعِيدٍ الْخُدْرِيِّ وَعَنْ أَبِي هُرَيْرَةَ رضي الله عنهما عَنِ النَّبِيِّ صلى الله عليه وسلم قَالَ:"
        segments = pipeline.run(extract_text(intro))
        self.assertEqual(segments[0].kind, "attribution")

    def test_companion_saying_still_resolves_to_the_companion(self):
        from classify.services.speaker import speaker_of

        self.assertEqual(speaker_of("فقال عمر رضي الله عنه:"), "companion")

    def test_reattribute_keeps_the_narrated_hadith(self):
        from classify.pipeline import StoredSegment
        from classify.services.speaker import reattribute

        intro = StoredSegment(
            kind="attribution",
            content="عن عُبادةَ بنِ الصامتِ رضي الله عنه، أنَّ النبيَّ صلَّى الله عليه وسلَّم قال:",
            source="",
            score=None,
            para=1,
            level=0,
        )
        hadith = StoredSegment(
            kind="hadith",
            content="لا صَلاةَ لِمَن لم يقرأْ بفاتحةِ الكِتابِ",
            source="",
            score=0.95,
            para=1,
            level=0,
        )
        stats = reattribute([intro, hadith])
        self.assertEqual(hadith.kind, "hadith")
        self.assertEqual(stats["hadith_to_athar"], 0)

    def test_reattribute_keeps_the_heard_hadith(self):
        from classify.pipeline import StoredSegment
        from classify.services.speaker import reattribute

        intro = StoredSegment(
            kind="attribution",
            content="عن أبي هريرة رضي الله عنه قال: سمعت رسول الله صلى الله عليه وسلم يقول:",
            source="",
            score=None,
            para=1,
            level=0,
        )
        hadith = StoredSegment(
            kind="hadith",
            content="حَقُّ الْمُسْلِمِ عَلَى الْمُسْلِمِ خَمْسٌ: رَدُّ السَّلَامِ، وَعِيَادَةُ الْمَرِيضِ.",
            source="",
            score=0.95,
            para=1,
            level=0,
        )
        stats = reattribute([intro, hadith])
        self.assertEqual(hadith.kind, "hadith")
        self.assertEqual(stats["hadith_to_athar"], 0)


class PeelQuranUnitsTests(TestCase):
    """تقشير التقديم والإحالة عن وحدة الآية قبل تحقق المصحف."""

    def test_leadin_and_citation_are_peeled_and_the_pure_aya_rematches(self):
        from classify.pipeline import peel_quran_units
        from classify.services.classifier import Segment

        seg = Segment(
            "quran",
            "بدليل قوله تعالى: وَلَقَدْ آتَيْنَاكَ سَبْعًا مِنَ الْمَثَانِى وَالْقُرْآنَ الْعَظِيمَ [الحجر: 87].",
            source="سورة الحجر — 87",
            score=0.83,
            note="مطابقة 83% | ⚠ يخالف رسم المصحف",
            para=1,
        )
        out = peel_quran_units([seg])
        self.assertEqual([s.kind for s in out], ["attribution", "quran", "citation"])
        self.assertEqual(out[0].content, "بدليل قوله تعالى:")
        self.assertEqual(out[2].content, "[الحجر: 87].")
        aya = out[1]
        self.assertNotIn("قوله", aya.content)
        self.assertNotIn("الحجر", aya.content)
        self.assertEqual(aya.source, "سورة الحجر — 87")
        self.assertEqual(aya.score, 1.0)
        self.assertNotIn("⚠", aya.note)

    def test_author_prose_before_a_braced_quote_is_peeled_as_text(self):
        from classify.pipeline import peel_quran_units
        from classify.services.classifier import Segment

        seg = Segment(
            "quran",
            "إثبات صفة الغضب لله -تعالى- على وجه يليق بجلاله -تعالى-: "
            "{ليس كمثله شيء وهو السميع البصير}.",
            source="سورة الشورى — 11",
            score=0.9,
            note="مطابقة تامة",
            para=1,
        )
        out = peel_quran_units([seg])
        self.assertEqual([s.kind for s in out], ["text", "quran"])
        self.assertIn("إثبات صفة الغضب", out[0].content)
        self.assertNotIn("{", out[0].content)
        aya = out[1]
        self.assertTrue(aya.content.startswith("{"))
        self.assertNotIn("إثبات", aya.content)

    def test_a_clean_aya_is_left_untouched(self):
        from classify.pipeline import peel_quran_units
        from classify.services.classifier import Segment

        seg = Segment("quran", "﴿إِنَّ مَعَ الْعُسْرِ يُسْرًا﴾", score=1.0, para=1)
        out = peel_quran_units([seg])
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], seg)

    def test_non_quran_units_pass_through(self):
        from classify.pipeline import peel_quran_units
        from classify.services.classifier import Segment

        seg = Segment("text", "بدليل قوله تعالى: كلام عادي فيه نقطتان.", para=1)
        out = peel_quran_units([seg])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "text")


class ProphetSymbolTests(TestCase):
    """رمز ﷺ يبقى رمزاً في النص المعروض، و«وقال النبي ﷺ:» إسناد."""

    def test_the_symbol_is_preserved_and_detached(self):
        from classify.services.splitter import expand_ligatures

        self.assertEqual(expand_ligatures("وَقَالَﷺ:"), "وَقَالَ ﷺ:")
        self.assertNotIn("صلى الله عليه وسلم", expand_ligatures("قال النبي ﷺ كذا"))

    def test_leadin_with_the_symbol_is_an_attribution(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        segments = pipeline.run(
            extract_text("وقال النبي ﷺ: ((لا صَلاةَ لِمَن لم يقرأْ بفاتحةِ الكِتابِ)).")
        )
        self.assertEqual(segments[0].kind, "attribution")
        self.assertIn("ﷺ", segments[0].content)


class TrailingLeadinTests(TestCase):
    """تقديم ذاب في ذيل وحدة نثر («… قال الله تعالى:») يُفصل وحدةَ إسناد."""

    def test_trailing_leadin_is_split_off(self):
        from classify.pipeline import split_trailing_leadins
        from classify.services.classifier import Segment

        seg = Segment(
            "term",
            "الحمد لله رب العالمين، والصلاة والسلام على أشرف الأنبياء والمرسلين. قال الله تعالى:",
            terms=[{"arabic": "أنبياء"}],
            para=1,
        )
        out = split_trailing_leadins([seg])
        self.assertEqual([s.kind for s in out], ["term", "attribution"])
        self.assertEqual(out[1].content, "قال الله تعالى:")
        self.assertFalse(out[0].content.endswith(":"))

    def test_plain_colon_prose_is_untouched(self):
        from classify.pipeline import split_trailing_leadins
        from classify.services.classifier import Segment

        seg = Segment("text", "وختام القول: أن نجعل نياتنا خالصة لله.", para=1)
        out = split_trailing_leadins([seg])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "text")


class ResolveCitationsTests(TestCase):
    """الإحالة المستقلة تُصنف إحالةً وتُرجّح سورتها في الآيات المتشابهة."""

    def test_standalone_citation_is_reclassified_and_resolves_mutashabih(self):
        from classify.pipeline import resolve_citations
        from classify.services.classifier import Segment

        aya = Segment(
            "quran",
            "وَإِذْ قُلْنَا لِلْمَلَائِكَةِ اسْجُدُوا لِآدَمَ فَسَجَدُوا إِلَّا إِبْلِيسَ أَبَىٰ",
            source="سورة البقرة — 34",
            score=1.0,
            para=1,
        )
        cite = Segment("term", "[طه: 116].", para=1)
        changed = resolve_citations([aya, cite])
        self.assertGreaterEqual(changed, 1)
        self.assertEqual(cite.kind, "citation")
        self.assertEqual(aya.source, "سورة طه — 116")

    def test_matching_citation_leaves_the_source_alone(self):
        from classify.pipeline import resolve_citations
        from classify.services.classifier import Segment

        aya = Segment("quran", "نص", source="سورة البقرة — 34", score=1.0, para=1)
        cite = Segment("citation", "[البقرة: 34].", para=1)
        resolve_citations([aya, cite])
        self.assertEqual(aya.source, "سورة البقرة — 34")


class UiLabelTests(TestCase):
    """تسميات العرض: التقديم والخاتمة تحت «نص عام»، والإحالة صارت «عزو»."""

    def test_quotation_leadin_is_labelled_general_text(self):
        from classify.services.moneer_ui import attribution_label

        self.assertEqual(attribution_label("قال الله تعالى:"), "نص عام")
        self.assertEqual(attribution_label("عن أبي هريرة رضي الله عنه قال:"), "نص عام")
        self.assertEqual(attribution_label("رواه الترمذي وصححه الألباني"), "تخريج")

    def test_citation_tag_is_azw(self):
        from classify.services.classifier import Segment
        from classify.services.moneer_ui import to_ui_segments

        units = to_ui_segments([Segment("citation", "[البقرة: 153].", para=1)])
        self.assertEqual(units[0]["tagLabel"], "عزو")

    def test_khatima_title_is_labelled_general_text(self):
        from classify.services.classifier import Segment
        from classify.services.moneer_ui import to_ui_segments

        units = to_ui_segments(
            [
                Segment("title", "فضل المعوذات", level=2, para=1),
                Segment("title", "الخاتمة", level=2, para=2),
                Segment("title", "خاتمة الكتاب", level=2, para=3),
            ]
        )
        self.assertEqual([u["tagLabel"] for u in units], ["عنوان", "نص عام", "نص عام"])

    def test_empty_aya_brackets_are_stripped_from_display(self):
        from classify.services.classifier import Segment
        from classify.services.moneer_ui import to_ui_segments

        seg = Segment("quran", "قُلۡ أَعُوذُ بِرَبِّ ٱلۡفَلَقِ﴿﴾", source="سورة الفلق — 1", score=1.0, para=1)
        units = to_ui_segments([seg, Segment("text", "نصٌّ فيه ﴿ ﴾ فارغان.", para=1)])
        self.assertEqual(units[0]["ar"], "قُلۡ أَعُوذُ بِرَبِّ ٱلۡفَلَقِ")
        self.assertEqual(units[1]["ar"], "نصٌّ فيه فارغان.")


class BracketedContentTests(TestCase):
    """القوسان المربعان لا يجعلان المتن إحالةً إلا بسيماء المصدر (رقم/نقطتان/تخريج)."""

    def test_bracketed_dua_tail_is_not_a_citation(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        text = "[اللَّهُمَّ لَكَ أَسْلَمتُ، وَعَلَيْكَ تَوَكَّلْتُ، وَبِكَ آمَنْتُ]\n[وَمَا أَنْتَ أَعْلَمُ بِهِ مِنِّي]"
        segments = pipeline.run(extract_text(text))
        self.assertTrue(all(s.kind != "citation" for s in segments))

    def test_citation_requires_a_real_surah_name(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        aya = "قال تعالى: ﴿كُلُّ نَفۡسٖ ذَآئِقَةُ ٱلۡمَوۡتِ﴾"
        with_surah = pipeline.run(extract_text(f"{aya}\n[آل عمران: 185]."))
        self.assertIn("citation", [s.kind for s in with_surah])
        hadith_ref = pipeline.run(extract_text(f"{aya}\n[البخاري: 6317]."))
        self.assertNotIn("citation", [s.kind for s in hadith_ref])

    def test_bracketed_aya_text_is_not_a_citation_despite_surah_word(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        segments = pipeline.run(extract_text("[قُلۡ أَعُوذُ بِرَبِّ ٱلنَّاسِ]"))
        self.assertNotIn("citation", [s.kind for s in segments])

    def test_bracketed_takhrij_becomes_attribution(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        segments = pipeline.run(extract_text("«إنما الأعمال بالنيات»\n[رواه البخاري]."))
        kinds = [s.kind for s in segments]
        self.assertNotIn("citation", kinds)
        self.assertIn("attribution", kinds)

    def test_bare_muttafaq_alayh_is_a_takhrij_not_a_term(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        segments = pipeline.run(extract_text("متفق عليه."))
        self.assertEqual(segments[0].kind, "attribution")
        self.assertEqual(segments[0].note, "تخريج المصدر")
        plain = pipeline.run(extract_text("حسن الخلق."))
        self.assertNotIn("attribution", [s.kind for s in plain])


class RescueShortAyasTests(TestCase):
    """آية قصيرة بين آيات تُنقذ بمطابقة تامة مرجحة بالسياق؛ النص الحر لا يُمس."""

    def test_fatiha_three_is_rescued_with_the_exact_ref(self):
        from classify.pipeline import rescue_short_ayas
        from classify.services.classifier import Segment

        segs = [
            Segment(
                "quran", "ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ ٢", source="سورة الفاتحة — 2", score=1.0, para=1
            ),
            Segment("text", "ٱلرَّحْمَٰنِ ٱلرَّحِيمِ ٣", para=1),
            Segment("quran", "مَٰلِكِ يَوْمِ ٱلدِّينِ ٤", source="سورة الفاتحة — 4", score=1.0, para=1),
        ]
        self.assertEqual(rescue_short_ayas(segs), 1)
        self.assertEqual(segs[1].kind, "quran")
        self.assertEqual(segs[1].source, "سورة الفاتحة — 3")

    def test_free_prose_without_quran_neighbors_is_untouched(self):
        from classify.pipeline import rescue_short_ayas
        from classify.services.classifier import Segment

        segs = [
            Segment("text", "ثم تحدث الخطيب طويلاً.", para=1),
            Segment("text", "الحمد لله رب العالمين.", para=1),
        ]
        self.assertEqual(rescue_short_ayas(segs), 0)
        self.assertEqual(segs[1].kind, "text")


def _quran_records():
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parent / "data" / "quran.json"
    return json.loads(data.read_text(encoding="utf-8"))


class UthmaniIndexTests(TestCase):
    """فهرس icadb العثماني يُدرَك بالاستعلام الإملائي عبر فهرسة الصورتين."""

    def test_imlaei_queries_hit_the_uthmani_index(self):
        from classify.services.matchers import get_matchers

        quran = get_matchers()[0]
        cases = [
            ("الحمد لله رب العالمين", "سورة الفاتحة — 2"),
            ("وأقيموا الصلاة وآتوا الزكاة واركعوا مع الراكعين", "سورة البقرة — 43"),
            ("يا أيها الذين آمنوا استعينوا بالصبر والصلاة", "سورة البقرة — 153"),
        ]
        for text, source in cases:
            match = quran.match(text)
            self.assertIsNotNone(match, text)
            self.assertEqual(match.source, source)
            self.assertGreaterEqual(match.score, 0.9)


class ChainQuranSequenceTests(TestCase):
    """الوحدة التي هي آيات متتابعة حرفياً تُسوَّر بالمصحف آيةً آية."""

    def test_unnumbered_continuous_fatiha_is_split_into_seven_ayas(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        fatiha = [r["text"] for r in _quran_records() if r["surah_no"] == 1]
        out = chain_quran_sequence([Segment("text", " ".join(fatiha), para=1)])
        self.assertEqual([s.kind for s in out], ["quran"] * 7)
        self.assertEqual([s.source for s in out], [f"سورة الفاتحة — {i}" for i in range(1, 8)])

    def test_inserted_space_inside_a_word_does_not_break_the_chain(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        ayas = [r["text"] for r in _quran_records() if r["surah_no"] == 2][2:5]
        broken = " ".join(ayas).replace("وَبِٱلۡأٓخِرَةِ", "وَبِٱلۡ أٓخِرَةِ")
        self.assertNotEqual(broken, " ".join(ayas))
        out = chain_quran_sequence([Segment("text", broken, para=1)])
        self.assertEqual([s.source for s in out], [f"سورة البقرة — {i}" for i in (3, 4, 5)])

    def test_fragmented_aya_units_are_resewn_across_lines(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        ikhlas = [r["text"] for r in _quran_records() if r["surah"] == "الإخلاص"]
        third = ikhlas[2].split()
        frag = (
            f"{ikhlas[0]}1\n{ikhlas[1]}2\n"
            + " ".join(third[:2])
            + "\n"
            + " ".join(third[2:])
            + f"3 {ikhlas[3]}4\n[الإخلاص: 1-4]."
        )
        segments = pipeline.run(extract_text(frag))
        quran = [s for s in segments if s.kind == "quran"]
        self.assertEqual([s.source for s in quran], [f"سورة الإخلاص — {i}" for i in range(1, 5)])
        self.assertTrue(all("⚠" not in (s.note or "") for s in segments))
        self.assertIn("citation", [s.kind for s in segments])

    def test_glued_ayah_numbers_are_markers_not_variants(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        falaq = [r["text"] for r in _quran_records() if r["surah"] == "الفلق"]
        glued = " ".join(f"{t}{i + 1}" for i, t in enumerate(falaq))
        out = chain_quran_sequence([Segment("text", glued, para=1)])
        self.assertEqual([s.source for s in out], [f"سورة الفلق — {i}" for i in range(1, 6)])
        self.assertTrue(all("⚠" not in (s.note or "") for s in out))

    def test_deleted_word_flags_only_its_aya(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        ayas = [r["text"] for r in _quran_records() if r["surah_no"] == 2][5:8]
        words = ayas[1].split()
        ayas[1] = " ".join(words[:-1])
        out = chain_quran_sequence([Segment("text", " ".join(ayas), para=1)])
        self.assertEqual([s.source for s in out], [f"سورة البقرة — {i}" for i in (6, 7, 8)])
        flagged = ["⚠" in (s.note or "") for s in out]
        self.assertEqual(flagged, [False, True, False])

    def test_two_deleted_words_flag_only_their_aya(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        ayas = [r["text"] for r in _quran_records() if r["surah_no"] == 2][5:8]
        words = ayas[1].split()
        ayas[1] = " ".join(words[:4] + words[5:-1])
        out = chain_quran_sequence([Segment("text", " ".join(ayas), para=1)])
        self.assertEqual([s.source for s in out], [f"سورة البقرة — {i}" for i in (6, 7, 8)])
        flagged = ["⚠" in (s.note or "") for s in out]
        self.assertEqual(flagged, [False, True, False])

    def test_free_prose_is_not_chained(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        seg = Segment(
            "text", "ثم أوصى الخطيب الناس بتقوى الله والصبر على الطاعة دائماً أبداً.", para=1
        )
        out = chain_quran_sequence([seg])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "text")

    def test_khutbah_opener_with_a_verbatim_verse_is_not_chained(self):
        from classify.pipeline import chain_quran_sequence
        from classify.services.classifier import Segment

        seg = Segment(
            "text",
            "الحمد لله رب العالمين نحمده ونستعينه ونستغفره ونعوذ بالله من شرور أنفسنا",
            para=1,
        )
        out = chain_quran_sequence([seg])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].kind, "text")


class PreferSequentialDuplicatesTests(TestCase):
    """الآية المكررة النص تُنسب إلى تسلسل جارتها لا إلى نظيرتها البعيدة."""

    def test_duplicate_verse_is_reattributed_to_the_context_sequence(self):
        from classify.pipeline import prefer_sequential_duplicates
        from classify.services.classifier import Segment

        recs = _quran_records()
        b4 = next(r["text"] for r in recs if r["surah_no"] == 2 and r["ayah"] == 4)
        b5 = next(r["text"] for r in recs if r["surah_no"] == 2 and r["ayah"] == 5)
        segs = [
            Segment("quran", b4, source="سورة البقرة — 4", score=1.0, para=1),
            Segment("quran", b5, source="سورة لقمان — 5", score=1.0, para=1),
        ]
        self.assertEqual(prefer_sequential_duplicates(segs), 1)
        self.assertEqual(segs[1].source, "سورة البقرة — 5")
        self.assertIn("رُجّحت بتسلسل سياقها", segs[1].note)

    def test_non_identical_text_is_left_alone(self):
        from classify.pipeline import prefer_sequential_duplicates
        from classify.services.classifier import Segment

        segs = [
            Segment("quran", "نص", source="سورة البقرة — 4", score=1.0, para=1),
            Segment("quran", "كلام آخر ليس آية", source="سورة لقمان — 5", score=0.9, para=1),
        ]
        self.assertEqual(prefer_sequential_duplicates(segs), 0)
        self.assertEqual(segs[1].source, "سورة لقمان — 5")


class CosmeticHamzaDiffTests(TestCase):
    """خلاف صور الهمزة بين مصحفين صحيحين لا يُعلَّم؛ التحريف الحقيقي يبقى."""

    def test_seat_differences_are_cosmetic(self):
        from classify.services.bert_layer import _cosmetic_pair

        self.assertTrue(_cosmetic_pair("ءانذرتهم", "اانذرتهم"))
        self.assertTrue(_cosmetic_pair("مستهزءون", "مستهزيون"))
        self.assertTrue(_cosmetic_pair("مستهزءون", "مستهزون"))
        self.assertTrue(_cosmetic_pair("بياياته", "باياته"))

    def test_real_differences_are_not_cosmetic(self):
        from classify.services.bert_layer import _cosmetic_pair

        self.assertFalse(_cosmetic_pair("قال", "قل"))
        self.assertFalse(_cosmetic_pair("الصالحين", "الصابرين"))
        self.assertFalse(_cosmetic_pair("تعملون", "يعملون"))
        self.assertFalse(_cosmetic_pair("فيه", "فه"))

    def test_real_diff_drops_hamza_pairs_and_keeps_alterations(self):
        import sys

        from classify.services import bert_layer

        if not bert_layer.enabled():
            self.skipTest("BERT_LAYER معطلة")
        bd = str(bert_layer.bert_dir())
        if bd not in sys.path:
            sys.path.insert(0, bd)
        v = {"diff": {"extra": ["ءانذرتهم", "دايما"], "missing": ["اانذرتهم"], "window": ""}}
        real = bert_layer._real_diff(v, "")
        self.assertEqual(real["extra"], ["دايما"])
        self.assertEqual(real["missing"], [])


class ImportQuranCommandTests(TestCase):
    """أمر import_quran: يرفض مصحفاً ناقصاً، وdry-run لا يكتب شيئاً."""

    def test_incomplete_records_are_rejected(self):
        import json
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.core.management.base import CommandError

        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp) / "partial.json"
            partial.write_text(
                json.dumps(_quran_records()[:10], ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaises(CommandError):
                call_command("import_quran", file=str(partial), verbosity=0)

    def test_dry_run_leaves_the_index_untouched(self):
        from pathlib import Path

        from django.core.management import call_command

        target = Path(__file__).resolve().parent / "data" / "quran.json"
        before = target.read_bytes()
        call_command("import_quran", file=str(target), dry_run=True, verbosity=0)
        self.assertEqual(target.read_bytes(), before)


class BracketSidePartsTests(TestCase):
    """ما يُفصل حول الآية المقوَّسة في طبقة BERT يُوسم بقاعدة الإسناد نفسها."""

    def test_attribution_after_verse_is_isnad_not_text(self):
        from classify.services.bert_layer import _side_part
        from classify.services.classifier import Segment

        seg = Segment("quran", "﴿إِنَّ اللَّهَ مَعَ الصَّابِرِينَ﴾، وقال النبي ﷺ:")
        part = _side_part(seg, "وقال النبي ﷺ:")
        self.assertEqual(part.kind, "attribution")
        self.assertEqual(part.content, "وقال النبي ﷺ:")

    def test_plain_remainder_stays_text(self):
        from classify.services.bert_layer import _side_part
        from classify.services.classifier import Segment

        part = _side_part(Segment("quran", "x"), "فالصبر عبادة قلبية.")
        self.assertEqual(part.kind, "text")

    def test_learned_split_hands_lead_comma_back(self):
        from classify.services.splitter import _attach_lead_commas

        self.assertEqual(
            _attach_lead_commas(["﴿آية﴾", "، وقال النبي ﷺ:"]), ["﴿آية﴾،", "وقال النبي ﷺ:"]
        )


class BracketedMultiVerseSplitTests(TestCase):
    def test_each_verse_in_one_bracket_becomes_its_own_unit(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        text = (
            "قال الله تعالى: ﴿وَالْعَصْرِ إِنَّ الْإِنْسَانَ لَفِي خُسْرٍ إِلَّا الَّذِينَ آمَنُوا "
            "وَعَمِلُوا الصَّالِحَاتِ وَتَوَاصَوْا بِالْحَقِّ وَتَوَاصَوْا بِالصَّبْرِ﴾."
        )
        ayas = [s for s in pipeline.run(extract_text(text)) if s.kind == "quran"]
        self.assertEqual([s.source for s in ayas], [f"سورة العصر — {n}" for n in (1, 2, 3)])
        # قوسا الأصل وحدهما: الفاتح على أول الآيات والخاتم على آخرها، بلا أقواس مضافة
        self.assertEqual(ayas[0].content, "﴿وَالْعَصْرِ")
        self.assertEqual(ayas[1].content, "إِنَّ الْإِنْسَانَ لَفِي خُسْرٍ")
        self.assertTrue(ayas[2].content.startswith("إِلَّا"))
        self.assertTrue(ayas[2].content.endswith("بِالصَّبْرِ﴾."))


class TermSurfaceTests(TestCase):
    def test_term_label_uses_the_word_as_written(self):
        from classify.services.moneer_ui import surface

        self.assertEqual(surface("ويقترن بتقوى الله.", "تقوي"), "بتقوى")
        self.assertEqual(surface("والتوكّل عليه.", "توكل"), "والتوكّل")


class ShortBracketedVersesSplitTests(TestCase):
    def test_two_short_verses_in_one_bracket_are_split(self):
        from classify import pipeline
        from classify.services.splitter import extract_text

        segs = pipeline.run(extract_text("﴿وَالْعَصْرِ إِنَّ الْإِنْسَانَ لَفِي خُسْرٍ﴾."))
        ayas = [s for s in segs if s.kind == "quran"]
        self.assertEqual([s.source for s in ayas], ["سورة العصر — 1", "سورة العصر — 2"])


class HadithLeadinTests(TestCase):
    """تقديمٌ التصق بحديثٍ بلا علامات تنصيص يُفصل عنه، ويُطابَق نصُّ الحديث وحده."""

    def setUp(self):
        from types import SimpleNamespace
        from unittest import mock

        from classify import pipeline
        from classify.services import classifier, matchers
        from classify.services.normalizer import normalize

        hadith_text = normalize("الأعمال بالنيات")

        class FakeHadith:
            index = SimpleNamespace(records=[{"text": "إنما الأعمال بالنيات"}])

            def match(self, text):
                n = normalize(text)
                if hadith_text not in n:
                    return None
                if "قال" in n:
                    return matchers.Match("hadith", "سنن أبي داود — 2201", 0.94, {})
                return matchers.Match("hadith", "صحيح البخاري — 1", 1.0, {})

        quran, _hadith, glossary = matchers.get_matchers()
        fake = (quran, FakeHadith(), glossary)
        for module in (pipeline, classifier):
            patcher = mock.patch.object(module, "get_matchers", lambda: fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def peel(self, kind, content, **fields):
        from classify import pipeline
        from classify.services.classifier import Segment

        return pipeline.peel_hadith_leadins([Segment(kind, content, para=1, **fields)])

    def test_unquoted_hadith_after_a_leadin_is_peeled_with_the_next_sentence(self):
        out = self.peel("attribution", "وقال النبي: إنما الأعمال بالنيات. فالصبر عبادة قلبية.")
        self.assertEqual([s.kind for s in out[:2]], ["attribution", "hadith"])
        self.assertEqual(out[0].content, "وقال النبي:")
        self.assertEqual(out[1].content, "إنما الأعمال بالنيات.")
        self.assertEqual(out[1].source, "صحيح البخاري — 1")
        self.assertEqual(out[2].content, "فالصبر عبادة قلبية.")
        self.assertTrue(all(s.para == 1 for s in out))

    def test_hadith_matched_with_its_leadin_is_rematched_alone(self):
        out = self.peel(
            "hadith",
            "قال رسول الله صلى الله عليه وسلم: إنما الأعمال بالنيات.",
            source="سنن أبي داود — 2201",
            score=0.94,
        )
        self.assertEqual([s.kind for s in out], ["attribution", "hadith"])
        self.assertEqual(out[0].content, "قال رسول الله صلى الله عليه وسلم:")
        self.assertEqual((out[1].source, out[1].note), ("صحيح البخاري — 1", "مطابقة تامة"))

    def test_leadin_without_scripture_after_it_is_left_whole(self):
        text = "قال ابن القيم رحمه الله: الصبر حبس النفس عن الجزع."
        out = self.peel("attribution", text)
        self.assertEqual([(s.kind, s.content) for s in out], [("attribution", text)])

    def test_bare_leadin_is_untouched(self):
        out = self.peel("attribution", "وقال النبي ﷺ:")
        self.assertEqual([(s.kind, s.content) for s in out], [("attribution", "وقال النبي ﷺ:")])


class ClosedQuoteBoundaryTests(TestCase):
    """اقتباسٌ مغلق تليه علامة وقف حدُّ جملة ولو ضمّ المصنّفُ المتعلَّم ما بعده إليه."""

    def test_closed_quote_then_stop_ends_the_sentence(self):
        from classify.services.splitter import _split_after_closed_quotes

        units = _split_after_closed_quotes(["«إنما الأعمال بالنيات وإنما». فالصبر عبادة قلبية."])
        self.assertEqual(units, ["«إنما الأعمال بالنيات وإنما».", "فالصبر عبادة قلبية."])

    def test_quote_without_stop_or_at_the_end_is_kept(self):
        from classify.services.splitter import _split_after_closed_quotes

        units = ["«إنما الأعمال بالنيات» رواه البخاري.", "وقال: «الدين النصيحة»."]
        self.assertEqual(_split_after_closed_quotes(units), units)

    def test_user_text_keeps_the_quoted_hadith_apart(self):
        from classify.services.splitter import split_sentences

        text = (
            "قال الله تعالى: ﴿إِنَّ اللَّهَ مَعَ الصَّابِرِينَ﴾، وقال النبي : «إنما الأعمال بالنيات وإنما». "
            "فالصبر عبادة قلبية تقوم على التسليم لقضاء الله."
        )
        units = split_sentences(text)
        self.assertIn("«إنما الأعمال بالنيات وإنما».", units)
        self.assertEqual(units[-1], "فالصبر عبادة قلبية تقوم على التسليم لقضاء الله.")
