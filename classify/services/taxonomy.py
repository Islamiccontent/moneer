"""المفردات المغلقة للمخرَج موحّدة مع ICADB: أنواع المحتوى والوسوم وأصناف التحليل في مرجع واحد."""

from enum import IntEnum, StrEnum


class ContentTypeId(IntEnum):
    """`content_type_id` في icadb. القيمةُ رقمٌ، وهو ما يُستورَد فعلاً."""

    AYAH = 1
    HADITH = 2
    ATHAR = 3
    TEXT = 4
    FOOTNOTE = 5
    HEADING = 6
    AUTHOR = 7


class ContentTypeName(StrEnum):
    """content_type_name: اسم النوع لاتينياً للآلة، والعربي يبقى في content_type_name_ar."""

    AYAH = "ayah"
    HADITH = "hadith"
    ATHAR = "athar"
    TEXT = "text"
    FOOTNOTE = "footnote"
    HEADING = "heading"
    AUTHOR = "author"


CONTENT_TYPE_NAME: dict[ContentTypeId, ContentTypeName] = {
    c: ContentTypeName[c.name] for c in ContentTypeId
}

CONTENT_TYPE_NAME_AR: dict[ContentTypeId, str] = {
    ContentTypeId.AYAH: "آية",
    ContentTypeId.HADITH: "حديث",
    ContentTypeId.ATHAR: "أثر",
    ContentTypeId.TEXT: "نص",
    ContentTypeId.FOOTNOTE: "هامش",
    ContentTypeId.HEADING: "العنوان",
    ContentTypeId.AUTHOR: "المؤلف",
}


class Tag(StrEnum):
    """`tag` — وسمُ كتلة Word. مستوياتُ العنوان خمسةٌ عند icadb لا ثلاثة."""

    PARAGRAPH = "p"
    HEADING_1 = "heading1"
    HEADING_2 = "heading2"
    HEADING_3 = "heading3"
    HEADING_4 = "heading4"
    HEADING_5 = "heading5"
    LIST_PARAGRAPH = "listparagraph"
    FOOTNOTE = "footnote"


class TextType(StrEnum):
    """`text_type` — صنفُ النصّ. أوسعُ من Tag وغيرُ مرادفٍ له."""

    PARAGRAPH = "p"
    HEADING = "h"
    LIST_PARAGRAPH = "listparagraph"
    FOOTNOTE = "footnote"
    NAQHARA = "naqhara"
    QUESTION = "question"
    ANSWER = "answer"
    ABOUT = "about"


class Align(StrEnum):
    """المحاذاة؛ أكثر مفردات ICADB وروداً، والغالبة right."""

    RIGHT = "right"
    LEFT = "left"
    CENTER = "center"
    JUSTIFY = "justify"
    BOTH = "both"


class Direction(StrEnum):
    """`direction` — واحدةٌ فقط في كلّ بيانات icadb: rtl."""

    RTL = "rtl"
    LTR = "ltr"


class SegmentKind(StrEnum):
    """صنف المقطع كما حسمه المصنّف؛ أدق من ContentTypeId ولا يُستورد."""

    QURAN = "quran"
    HADITH = "hadith"
    ATHAR = "athar"
    HEADING = "heading"
    AUTHOR = "author"
    ATTRIBUTION = "attribution"
    CITATION = "citation"
    TERM = "term"
    PLAIN = "plain"


class TermCategory(StrEnum):
    """قسمُ المدخل المعجميّ. يفيد المترجم: العَلَمُ يُنقحَر والمصطلحُ يُردّ."""

    TERM = "term"
    PERSON = "person"
    PLACE = "place"
    DIVINE_NAME = "divine_name"
    SECT = "sect"
    ATTRIBUTE = "attribute"


class ConfidenceReason(StrEnum):
    """سندُ الثقة: من أين عرفنا؟ رمزٌ للآلة، ونصُّه العربيّ يبقى للمراجع."""

    WORD_HEADING_STYLE = "word_heading_style"
    INDEX_MATCH = "index_match"
    CITATION_REF = "citation_ref"
    ATTRIBUTION_FORMULA = "attribution_formula"
    GLOSSARY_ENTRY = "glossary_entry"
    UNMATCHED_QURAN = "unmatched_quran"
    UNMATCHED_HADITH = "unmatched_hadith"
    NO_EVIDENCE = "no_evidence"


KIND_OF_INTERNAL: dict[str, SegmentKind] = {
    "quran": SegmentKind.QURAN,
    "hadith": SegmentKind.HADITH,
    "athar": SegmentKind.ATHAR,
    "title": SegmentKind.HEADING,
    "author": SegmentKind.AUTHOR,
    "attribution": SegmentKind.ATTRIBUTION,
    "citation": SegmentKind.CITATION,
    "term": SegmentKind.TERM,
    "text": SegmentKind.PLAIN,
    "uncertain": SegmentKind.PLAIN,
}

CONTENT_TYPE_OF_KIND: dict[SegmentKind, ContentTypeId] = {
    SegmentKind.QURAN: ContentTypeId.AYAH,
    SegmentKind.HADITH: ContentTypeId.HADITH,
    SegmentKind.ATHAR: ContentTypeId.ATHAR,
    SegmentKind.HEADING: ContentTypeId.TEXT,
    SegmentKind.AUTHOR: ContentTypeId.TEXT,
    SegmentKind.ATTRIBUTION: ContentTypeId.TEXT,
    SegmentKind.CITATION: ContentTypeId.TEXT,
    SegmentKind.TERM: ContentTypeId.TEXT,
    SegmentKind.PLAIN: ContentTypeId.TEXT,
}

TERM_CATEGORY_OF_DICT: dict[str, TermCategory] = {
    "terms": TermCategory.TERM,
    "alam": TermCategory.PERSON,
    "amaken": TermCategory.PLACE,
    "asmaa": TermCategory.DIVINE_NAME,
    "feraq": TermCategory.SECT,
    "sefat": TermCategory.ATTRIBUTE,
}

REASON_CODE: dict[str, ConfidenceReason] = {
    "نمط عنوان": ConfidenceReason.WORD_HEADING_STYLE,
    "إحالة مصدر": ConfidenceReason.CITATION_REF,
    "صيغة إسناد": ConfidenceReason.ATTRIBUTION_FORMULA,
    "مدخل معجم": ConfidenceReason.GLOSSARY_ENTRY,
    "لا قرينة": ConfidenceReason.NO_EVIDENCE,
}

UNTRANSLATABLE = frozenset({SegmentKind.CITATION})

DESCRIPTIONS: dict[str, dict[str, str]] = {
    "segment_kind": {
        "quran": "Qur'anic verse, matched against the muṣḥaf index",
        "hadith": "Prophetic tradition, matched against the hadith index",
        "athar": "Report or saying of a Companion or Successor, "
        "attributed by its introducing formula",
        "heading": "Section heading",
        "author": "Author or issuing body",
        "attribution": "Attribution formula introducing a quotation",
        "citation": "Bracketed source reference, e.g. [al-Baqara: 2]",
        "term": "Ordinary prose containing a glossary term",
        "plain": "Ordinary prose",
    },
    "content_type": {
        "1": "ayah",
        "2": "hadith",
        "3": "athar (report from a Companion)",
        "4": "text",
        "5": "footnote (deleted in icadb)",
        "6": "heading",
        "7": "author",
    },
    "term_category": {
        "term": "Legal or theological term; render with the agreed equivalent",
        "person": "Proper name; transliterate",
        "place": "Place name; transliterate",
        "divine_name": "Name or attribute of God",
        "sect": "Named group or school",
        "attribute": "Descriptive attribute",
    },
}

EMITTED_CONTENT_TYPES = (
    ContentTypeId.AYAH,
    ContentTypeId.HADITH,
    ContentTypeId.ATHAR,
    ContentTypeId.TEXT,
)


def enum_block() -> dict:
    """المفردات المغلقة كما تُصدَّر في JSON، مع بيان مصدر كلٍّ منها."""

    def vals(e):
        return [m.value for m in e]

    return {
        "_source": {
            "icadb": ["content_type", "tag", "text_type", "align", "direction", "translatable"],
            "ours": ["segment_kind", "term_category", "confidence_reason"],
        },
        "content_type": {
            "values": [int(c) for c in ContentTypeId],
            "names": {int(c): CONTENT_TYPE_NAME[c].value for c in ContentTypeId},
            "names_ar": {int(c): CONTENT_TYPE_NAME_AR[c] for c in ContentTypeId},
            "descriptions": DESCRIPTIONS["content_type"],
            "emitted": [int(c) for c in EMITTED_CONTENT_TYPES],
        },
        "tag": {"values": vals(Tag)},
        "text_type": {"values": vals(TextType)},
        "align": {"values": vals(Align)},
        "direction": {"values": vals(Direction)},
        "segment_kind": {"values": vals(SegmentKind), "descriptions": DESCRIPTIONS["segment_kind"]},
        "term_category": {
            "values": vals(TermCategory),
            "descriptions": DESCRIPTIONS["term_category"],
        },
        "confidence_reason": {"values": vals(ConfidenceReason)},
    }
