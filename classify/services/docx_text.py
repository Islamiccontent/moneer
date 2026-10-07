"""قراءة نص ملف Word بما لا يقرؤه python-docx: رموز الخطوط الخاصة وغلاف الجدول.

ملفات الكتب القديمة لا تحفظ بعض النص حروفاً بل رموزاً (w:sym) لا تُرى إلا بخطوطها:
- «ﷺ» و«رضي الله عنه» بخط AGA Arabesque: يُحوَّل الرمز المعروف إلى نصه.
- الآيات بخطوط مصحف المدينة HQPB1–HQPB5: كل رمز حرفٌ بشكله في الكلمة أو علامة تشكيل،
  مخزنة بترتيب الرسم من اليسار؛ فتُفكّ بجدول data/hqpb_glyphs.json حروفاً بلا تشكيل وتُعكس
  كل كلمة إلى ترتيب القراءة. فيصل نص الآية كما في الملف ويطابقه المصنّف بالمصحف.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from docx.oxml.ns import qn
from lxml import etree

# رموز AGA Arabesque المعروفة (الحرف اللاتيني الذي يُرسم عليه الرمز)
AGA_SYMBOLS = {"F072": "ﷺ", "F074": "رضي الله عنه"}
QURAN_GLYPH_FONT = re.compile(r"^hqpb[1-5]$")
GLYPHS_PATH = Path(__file__).resolve().parent.parent / "data" / "hqpb_glyphs.json"

INLINE = {qn("w:hyperlink"), qn("w:ins"), qn("w:smartTag"), qn("w:fldSimple"), qn("w:sdt")}
SDT_CONTENT = qn("w:sdtContent")

# علامة حاشية داخل نص الفقرة أثناء استخراج حواشيها: \ue011<id>\ue012
NOTE_OPEN, NOTE_CLOSE = "\ue011", "\ue012"
NOTE_MARK = re.compile(r"\ue011(\d+)\ue012")
EMPTY_BRACKETS = re.compile(r"\(\s*\)")
ANCHOR_CHARS = 16  # آخر حروف ما قبل العلامة: مرساها في المقطع بعد التقطيع

COVER_MAX_CELLS = 10
COVER_MAX_WORDS = 40
HONORIFIC_LINE = {"صلى الله عليه وسلم": "ﷺ", "ﷺ": "ﷺ"}


@lru_cache(maxsize=1)
def quran_glyphs() -> dict[tuple[str, str], str]:
    """(الخط، الرمز) ← الحرف، من مدى الجدول؛ ما ليس فيه (تشكيل، زخرفة، تطويل) لا نص له."""
    table = {}
    for font, first, last, letter in json.loads(GLYPHS_PATH.read_text(encoding="utf-8"))["ranges"]:
        for code in range(int(first, 16), int(last, 16) + 1):
            table[(font.lower(), f"F0{code:02X}")] = letter
    return table


class _Reader:
    """يجمع نص الفقرة بترتيبها، ورموز خط المصحف كلمةً كلمة حتى فاصل فيعكسها إلى ترتيب القراءة."""

    def __init__(self, marks: bool = False):
        self.out: list[str] = []
        self.word: list[str] = []
        self.marks = marks  # تُدرج علامات الحواشي في النص لاستخراج مراسيها
        # كلمات خط المصحف المتتالية (بينها فراغ فقط) نصاً واحداً: ما يُستبدل بنص المصحف بعد المطابقة
        self.verses: list[list[str]] = []
        self.in_verse = False

    def flush(self):
        if self.word:
            word = "".join(reversed(self.word))
            self.out.append(word)
            if self.in_verse:
                self.verses[-1].append(word)
            else:
                self.verses.append([word])
                self.in_verse = True
            self.word = []

    def text(self, value: str):
        self.flush()
        self.out.append(value)
        if value.strip():
            self.in_verse = False

    def run(self, run):
        for child in run:
            tag = child.tag
            if tag == qn("w:t"):
                self.text(child.text or "")
            elif tag == qn("w:tab"):
                self.text("\t")
            elif tag in (qn("w:br"), qn("w:cr")):
                self.text("\n")
            elif tag == qn("w:noBreakHyphen"):
                self.text("-")
            elif tag == qn("w:footnoteReference") and self.marks:
                self.text(f"{NOTE_OPEN}{child.get(qn('w:id'))}{NOTE_CLOSE}")
            elif tag == qn("w:sym"):
                self.symbol(
                    (child.get(qn("w:font")) or "").lower(), (child.get(qn("w:char")) or "").upper()
                )

    def symbol(self, font: str, char: str):
        if QURAN_GLYPH_FONT.match(font):
            letter = quran_glyphs().get((font, char))
            if letter:
                self.word.append(letter)
        elif font.startswith("aga arabesque") and char in AGA_SYMBOLS:
            self.text(f" {AGA_SYMBOLS[char]} ")

    def inline(self, element):
        """العناصر المباشرة للفقرة بترتيبها: الجُرَيات وما يلفّها (روابط، حقول، إدراجات)."""
        for child in element:
            if child.tag == qn("w:r"):
                self.run(child)
            elif child.tag in INLINE or child.tag == SDT_CONTENT:
                self.inline(child)

    def result(self) -> str:
        self.flush()
        return "".join(self.out)


def paragraph_text(paragraph) -> str:
    """نص الفقرة كما يقرؤه python-docx، مع فك رموز AGA Arabesque وآيات خطوط المصحف."""
    reader = _Reader()
    reader.inline(paragraph._p)
    return reader.result()


def paragraph_verses(paragraph) -> list[str]:
    """نصوص الآيات المفكوكة من خط المصحف في الفقرة، كلٌّ كما يظهر في paragraph_text."""
    reader = _Reader()
    reader.inline(paragraph._p)
    reader.flush()
    return [" ".join(words) for words in reader.verses]


def anchor_key(char: str) -> str:
    """الحرف كما يُحسب في المرسى، أو «» لما لا يُحسب (الفراغات وعلامات التنصيص التي يحذفها
    المصنّف)؛ فيُقارن المرسى بنص المقطع بعد التقطيع ولو تغيّرت فراغاته."""
    return "" if char.isspace() or char in "«»" else char


def read_footnotes(doc) -> dict[str, str]:
    """نص كل حاشية برقمها (بلا «()» علامتها في أولها)؛ فارغ إن لم يكن في الملف حواشٍ."""
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/footnotes") and not rel.is_external:
            root = etree.fromstring(rel.target_part.blob)
            notes = {}
            for note in root.iter(qn("w:footnote")):
                reader = _Reader()
                for paragraph in note.iter(qn("w:p")):
                    reader.inline(paragraph)
                    reader.text(" ")
                text = re.sub(r"\s+", " ", reader.result()).strip()
                notes[note.get(qn("w:id"))] = EMPTY_BRACKETS.sub("", text, count=1).strip()
            return notes
    return {}


def paragraph_footnotes(paragraph, notes: dict[str, str], clean) -> list[tuple[str, str]]:
    """حواشي الفقرة بترتيبها: (مرسى علامتها، نص الحاشية بعد ``clean``).

    المرسى آخر حروف ما قبل العلامة بحساب anchor_key، بلا «(» التي تسبقها؛ وما لا نص له يُترك.
    """
    reader = _Reader(marks=True)
    reader.inline(paragraph._p)
    text = reader.result()
    out = []
    for m in NOTE_MARK.finditer(text):
        body = clean(notes.get(m.group(1), ""))
        if not body:
            continue
        before = clean(NOTE_MARK.sub("", text[: m.start()])).rstrip(" (\u00a0")
        before = EMPTY_BRACKETS.sub("", before)
        out.append(("".join(anchor_key(c) for c in before)[-ANCHOR_CHARS:], body))
    return out


def cover_lines(doc) -> list[str]:
    """سطور الغلاف إن بدأ الملف بجدول قصير (اسم الكتاب والمؤلف)، وإلا قائمة فارغة."""
    body = doc.element.body
    first = next(
        (
            el
            for el in body
            if el.tag == qn("w:tbl")
            or (el.tag == qn("w:p") and "".join(t.text or "" for t in el.iter(qn("w:t"))).strip())
        ),
        None,
    )
    if first is None or first.tag != qn("w:tbl"):
        return []
    table = next((t for t in doc.tables if t._tbl is first), None)
    if table is None:
        return []
    lines, seen = [], set()
    for row in table.rows:
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.add(cell._tc)  # العنصر نفسه لا id: الخلية المدمجة تتكرر في كل صف
            text = re.sub(r"\s+", " ", " ".join(paragraph_text(p) for p in cell.paragraphs))
            if text.strip():
                lines.append(text.strip())
    if not lines or len(lines) > COVER_MAX_CELLS:
        return []
    if sum(len(line.split()) for line in lines) > COVER_MAX_WORDS:
        return []
    merged: list[str] = []
    for line in lines:
        honorific = HONORIFIC_LINE.get(line)
        if honorific and merged:
            merged[-1] = f"{merged[-1]} {honorific}"
        else:
            merged.append(line)
    return merged
