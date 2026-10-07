import contextlib
import os
import re
from dataclasses import dataclass, field

from docx import Document as DocxDocument

from . import boundary, docx_text
from .normalizer import normalize

QUOTE_PAIRS = {"﴿": "﴾", "«": "»", "(": ")", "“": "”", '"': '"'}
OPENS_UNIT = {"﴿", "«", "“", '"'}
TERMINATORS = set(".!؟?\n")
AYAH_NUM = re.compile(r"\s*\d+\s*(?=﴾)")
ONLY_PUNCT = re.compile(r"^[\s.،,؛;:!؟?]+$")
ABBREV = re.compile(r"(?:^|\s)\S\.$")
HEAD_NUM = re.compile(r"^\s*\d+\s*[.\-–—)]\s*")
LIGATURES = {"ﷺ": "ﷺ", "ﷻ": "ﷻ", "﴾": "", "﴿": ""}
_LIG = re.compile("|".join(map(re.escape, [k for k, v in LIGATURES.items() if v])))


def expand_ligatures(text: str) -> str:
    """يبسط رمز ﷺ الملتصق بما قبله مع فاصل حتى لا يخرج ملتحماً بالكلمة السابقة."""
    text = _LIG.sub(lambda m: f" {LIGATURES[m.group(0)]} ", text)
    return re.sub(r" +([،.:!؟»)\]])", r"\1", AYAH_NUM.sub("", text)).replace("  ", " ").strip()


OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class DocumentError(Exception):
    """ملف تعذّرت قراءته، برسالة عربية صالحة للعرض على المستخدم."""


@dataclass
class Paragraph:
    text: str
    heading: bool = False
    level: int = 0
    styled: bool = True
    quoted: bool = False
    cover: bool = False
    # حواشي الفقرة من Word: (مرسى علامتها، نص الحاشية) بترتيب ورودها
    footnotes: list[tuple[str, str]] = field(default_factory=list)
    # آيات الفقرة المفكوكة من خط مصحف المدينة؛ يُستبدل بها نص المصحف بعد المطابقة
    mushaf_verses: list[str] = field(default_factory=list)


def diagnose(file) -> str:
    """تشخيص الملف من بصمته لا من امتداده — فالامتداد قد يكذب."""
    try:
        file.seek(0)
        head = file.read(8)
    except Exception:
        return "تعذّرت قراءة الملف. ارفع ملفاً بصيغة .docx."
    finally:
        with contextlib.suppress(Exception):
            file.seek(0)

    if head.startswith(OLE2_MAGIC):
        return (
            "هذا مستند Word 97-2003 بالصيغة الثنائية القديمة (.doc). "
            "افتحه في Word واحفظه بصيغة .docx ثم أعد رفعه."
        )
    if not head.startswith(b"PK"):
        return "الملف ليس مستند Word. ارفع ملفاً بصيغة .docx."
    return (
        "الملف حزمة Office لكنه ليس مستند Word — قد يكون قالب سمات (.thmx) "
        "أو ملفاً أعيدت تسميته. افتحه في Word واحفظه بصيغة .docx ثم أعد رفعه."
    )


INDEX_STYLE = re.compile(r"index|toc|contents|فهرس", re.I)


HEAD_MAX_WORDS = 14


def _looks_heading(p) -> bool:
    """يستنتج العنوان من التنسيق (غِلَظ أو توسيط) حين يغيب نمط العنوان."""
    runs = [r for r in p.runs if (r.text or "").strip()]
    if not runs:
        return False
    text = p.text.strip()
    if any(c in text for c in "﴿{«»﴾"):
        return False
    if len(text.split()) > HEAD_MAX_WORDS:
        return False
    if sum(1 for r in runs if r.bold) / len(runs) >= 0.6:
        return True
    return "CENTER" in str(p.paragraph_format.alignment or "")


# مقدمة الكتاب قبل أول عنوان تُعرف بافتتاحها (البسملة أو الحمدلة أو «أما بعد»)؛ وما سواها
# (صفحة العنوان، بطاقة المكتبة، التواريخ، الوصف) يُحذف كما كان
FRONT_OPENING = re.compile(r"بسم الله الرحمن الرحيم|الحمد لله|اما بعد")


def _cover(lines: list[str]) -> list[Paragraph]:
    """الغلاف: سطره الأول عنوان المستند، وما بعده (المؤلف ونحوه) فقرة واحدة."""
    if not lines:
        return []
    out = [Paragraph(expand_ligatures(lines[0]), heading=True, level=1, cover=True)]
    if lines[1:]:
        out.append(Paragraph(expand_ligatures(" ".join(lines[1:])), cover=True))
    return out


def _clean_docx(text: str) -> str:
    return clean_noise(expand_ligatures(text).strip())


def cover_title(paragraphs: list[Paragraph]) -> str:
    """عنوان المستند من غلافه إن وُجد."""
    return next((p.text for p in paragraphs if p.cover and p.heading), "")


def extract_docx(file, drop_front: bool = True) -> list[Paragraph]:
    """فقرات المستند بعد استبعاد الفهرس وصفحة العنوان قبل أول عنوان؛ drop_front=False يُبقيها.

    ما قبل أول عنوان يُحذف (صفحة العنوان وبطاقة الكتاب) إلا إن افتُتح بالبسملة أو الحمدلة أو
    «أما بعد» فهو مقدمة تبقى. والغلاف في جدول أول الملف يُقرأ عنواناً ومؤلفاً.
    """
    try:
        doc = DocxDocument(file)
    except Exception as exc:
        raise DocumentError(diagnose(file)) from exc
    cover = _cover(docx_text.cover_lines(doc))
    notes = docx_text.read_footnotes(doc)
    out, shapes, index_heads = [], [], set()
    for p in doc.paragraphs:
        text = _clean_docx(docx_text.paragraph_text(p))
        if not text:
            continue
        style = (p.style.name or "").lower()
        if INDEX_STYLE.search(style):
            # عنوان لا يليه إلا بنود فهرس («فهرس الآيات») يُحذف معها
            if out and out[-1].heading:
                index_heads.add(id(out[-1]))
            continue
        heading = "heading" in style or style == "title"
        level = 0
        if heading:
            digits = re.findall(r"\d", style)
            level = min(int(digits[0]), 3) if digits else 1
            text = HEAD_NUM.sub("", text) or text
        footnotes = docx_text.paragraph_footnotes(p, notes, _clean_docx) if notes else []
        verses = docx_text.paragraph_verses(p)
        out.append(
            Paragraph(text, heading=heading, level=level, footnotes=footnotes, mushaf_verses=verses)
        )
        shapes.append(_looks_heading(p))
    if index_heads:
        shapes = [s for p, s in zip(out, shapes, strict=True) if id(p) not in index_heads]
        out = [p for p in out if id(p) not in index_heads]

    if not any(p.heading for p in out) and any(shapes):
        for para, is_head in zip(out, shapes, strict=False):
            if is_head:
                para.heading, para.level = True, 1
                para.text = HEAD_NUM.sub("", para.text) or para.text
    if not any(p.heading for p in out):
        for p in out:
            p.styled = False
        return cover + out
    if drop_front:
        first = next((i for i, p in enumerate(out) if p.heading), None)
        if first and not any(FRONT_OPENING.search(normalize(p.text)) for p in out[:first]):
            out = out[first:]
    return cover + out


MD_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
MD_STRONG_LINE = re.compile(r"^(?:\*\*|__)(.+?)(?:\*\*|__)[\s.:：]*$")
MD_QUOTE = re.compile(r"^>+\s?")
MD_INLINE = re.compile(r"(\*\*|__|(?<![A-Za-z0-9])\*(?!\s))")
STRONG_MAX_WORDS = 10

EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿←-⇿️‍⃣™ℹ]")
HASHTAG_LINE = re.compile(r"^(?:[#＃][^\s#＃]+[\s،,]*)+$")
RULE_LINE = re.compile(r"^[\W_]{2,}$", re.UNICODE)


def clean_noise(text: str) -> str:
    """يُجرّد الحشو من الفقرة، ويرجع «» لما كان كلُّه حشواً."""
    t = EMOJI.sub(" ", text).strip()
    t = re.sub(r"\s{2,}", " ", t)
    if not t or HASHTAG_LINE.match(t) or RULE_LINE.match(t):
        return ""
    return t


def extract_text(raw: str) -> list[Paragraph]:
    raw = expand_ligatures(raw)
    out = []
    for chunk in re.split(r"\n\s*\n|\n", raw):
        text = clean_noise(chunk.strip())
        if not text:
            continue
        quoted = bool(MD_QUOTE.match(text))
        if quoted:
            text = MD_QUOTE.sub("", text).strip()
            if not text:
                continue
        m = None if quoted else MD_HEAD.match(text)
        if m:
            body = MD_INLINE.sub("", m.group(2)).strip()
            out.append(
                Paragraph(
                    HEAD_NUM.sub("", body) or body,
                    heading=True,
                    level=min(len(m.group(1)), 3),
                    styled=False,
                )
            )
            continue
        strong = MD_STRONG_LINE.match(text)
        body = MD_INLINE.sub("", strong.group(1) if strong else text).strip()
        if not body:
            continue
        if (
            strong
            and not quoted
            and len(body.split()) <= STRONG_MAX_WORDS
            and not body.endswith(".")
        ):
            out.append(
                Paragraph(HEAD_NUM.sub("", body) or body, heading=True, level=2, styled=False)
            )
        else:
            out.append(Paragraph(body, styled=False, quoted=quoted))
    return out


TAIL_CITE = re.compile(r"(?<=\S)\s*(\[[^\]]{2,40}\]\s*[.،]?)\s*$")


def _detach_citation(units: list[str]) -> list[str]:
    out: list[str] = []
    for u in units:
        m = TAIL_CITE.search(u)
        head = u[: m.start()].strip() if m else ""
        if m and len(head.split()) >= 3:
            out += [head, m.group(1).strip()]
        else:
            out.append(u)
    return out


def _opens_quote(text: str, i: int) -> bool:
    """هل يلي الموضعَ i اقتباسٌ (أو نهاية الفقرة)؟"""
    rest = text[i + 1 :].lstrip()
    return not rest or rest[0] in QUOTE_PAIRS


def reconstructs(text: str, units: list[str]) -> bool:
    """هل يعيد ضم القطع النص حرفاً بحرف (بإهمال المسافات)؟ شرط صحة لكل تقطيع."""
    return _BARE.sub("", "".join(units)) == _BARE.sub("", text)


_BARE = re.compile(r"\s+")


def split_sentences(text: str, tag: str = "p") -> list[str]:
    """يقطّع بالمصنّف المتعلَّم إن وُجد وإلا بالقواعد اليدوية، ويرفض ناتجاً لا يعيد بناء النص."""
    if os.environ.get("BOUNDARY_MODEL", "1") == "1":
        learned = _split_after_closed_quotes(_attach_lead_commas(boundary.split(text, tag)))
        if learned and reconstructs(text, learned):
            return learned
    rules = _split_by_rules(text)
    if rules and reconstructs(text, rules):
        return rules
    return [text.strip()] if text.strip() else []


QUOTE_THEN_STOP = re.compile(r"[»”]\s*[.!؟?]+(?=\s+\S)")


def _split_after_closed_quotes(units: list[str] | None) -> list[str] | None:
    """اقتباسٌ مغلق تليه علامة وقف («…».) حدُّ جملةٍ قاطع ولو فات المصنّف المتعلَّم."""
    if not units:
        return units
    out: list[str] = []
    for u in units:
        start = 0
        for m in QUOTE_THEN_STOP.finditer(u):
            out.append(u[start : m.end()].strip())
            start = m.end()
        if u[start:].strip():
            out.append(u[start:].strip())
    return [u for u in out if u]


def _attach_lead_commas(units: list[str] | None) -> list[str] | None:
    """ينقل الفاصلة في أول الوحدة إلى آخر الوحدة السابقة حتى لا تفوت أنماط الإسناد."""
    if not units:
        return units
    out: list[str] = []
    for u in units:
        rest = u.lstrip("،, ")
        if out and rest != u.lstrip() and rest:
            out[-1] = out[-1].rstrip() + u.lstrip()[: len(u.lstrip()) - len(rest)].rstrip()
            u = rest
        out.append(u)
    return out


def _split_by_rules(text: str) -> list[str]:
    units, buf, stack = [], [], []
    for i, ch in enumerate(text):
        buf.append(ch)
        if stack and ch == stack[-1]:
            stack.pop()
            continue
        if ch in QUOTE_PAIRS and not stack:
            if ch in OPENS_UNIT:
                pre = "".join(buf[:-1]).strip()
                if pre:
                    units.append(pre)
                buf = [ch]
            stack.append(QUOTE_PAIRS[ch])
            continue
        if ch in QUOTE_PAIRS and stack:
            stack.append(QUOTE_PAIRS[ch])
            continue
        if stack:
            continue
        if ch in TERMINATORS or ch == ":":
            unit = "".join(buf).strip()
            if ch == "." and ABBREV.search(unit):
                continue
            if ch == "." and (text[i + 1 : i + 2] == "." or unit.endswith("..")):
                continue
            if ch == ":" and not _opens_quote(text, i):
                continue
            if unit:
                units.append(unit)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        units.append(tail)
    merged: list[str] = []
    for u in units:
        u = u.strip()
        if not u:
            continue
        if ONLY_PUNCT.match(u) and merged:
            merged[-1] += u
            continue
        u = u.lstrip("،, ")
        if u:
            merged.append(u)
    return _detach_citation(merged)
