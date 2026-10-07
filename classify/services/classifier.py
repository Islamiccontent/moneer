import os
import re
from dataclasses import dataclass, field

from .matchers import contains_surah_name, get_matchers
from .normalizer import light, normalize
from .splitter import Paragraph, split_sentences

ATTRIBUTION = re.compile(
    r"^(و?ف?)(قال|يقول)\s+(الله\s+)?(تعالى|عز\s+وجل|سبحانه|جل\s+جلاله|رسول\s+الله|النبي|عليه\s+الصلاة\s+والسلام|ﷺ|صلى\s+الله)"
    r"|^(و?)عن\s+(?:\S+\s+){1,8}?رضي\s+الله\s+عنه"
    r"|^(و?ف?)(قال|يقول|قالت|تقول)\s+(?:\S+\s+){1,5}?"
    r"(?:رحمه|رحمها|رحمهم|رحمهما)\s+الله"
    r"|^(و?)(روى|رواه|أخرج|أخرجه|حدثنا|حدثني|أخبرنا|أخبرني)\s+"
    r"|^(و?)في\s+الحديث"
)
QURAN_HINT = re.compile(r"(قال\s+(الله\s+)?تعالى|قوله\s+تعالى|سبحانه|عز\s+وجل|الآية|سورة)")
HADITH_HINT = re.compile(
    r"(رسول\s+الله|النبي|ﷺ|صلى\s+الله\s+عليه|رواه|أخرجه|في\s+الحديث|رضي\s+الله)"
)
OPENING = re.compile(r"^(الحمد\s+لله|بسم\s+الله|أما\s+بعد|اللهم)")
CLOSING = re.compile(r"(ختام|خاتمة|أخيراً|وفي\s+الختام|نسأل\s+الله|وصلى\s+الله)")

NARRATION = re.compile(r"^\s*(و?كَ?انَ?|فَ?كَانَ|فَ?بَدَأَ|فَ?سَأَلَ|فَ?قَامَ|فَ?خَرَجَ|فَ?دَخَلَ|ثُمَّ|و?عَنْ)\s")

SUPPLICATION = re.compile(r"(اللهم|أعوذ\s+ب|أسألك|اغفر\s+لي|سبحانك|رب\s+اغفر|بسم\s+الله)")

ACCEPT = float(os.environ.get("ACCEPT_QURAN", "0.82"))
UNCERTAIN = float(os.environ.get("QURAN_SIGNAL", "0.72"))

UNMATCHED_QURAN = "فيه قوس آية ولم تبلغ المطابقة العتبة"

_TAIL_PUNCT = re.compile(r"[\s،,.:؛!؟\]\[)(»«﴾﴿}{\d]+$")
_COMMA = re.compile(r"[،,]")
BARE_AYAH_MIN_WORDS = 5

ENDS_COLON = re.compile(r"[:：]\s*$")
UNMATCHED_HADITH = "اقتباسٌ لم تبلغ مطابقتُه العتبة"
ACCEPT_HADITH = float(os.environ.get("ACCEPT_HADITH", "0.85"))
UNMATCHED = (UNMATCHED_QURAN, UNMATCHED_HADITH)
HADITH_SIGNAL = float(os.environ.get("HADITH_SIGNAL", "0.70"))

FAMOUS_STANDALONE = re.compile(
    r"^\s*(?:بسم\s+الله\s+الرحمن\s+الرحيم"
    r"|الحمد\s+لله\s+رب\s+العالمين"
    r"|لا\s+اله\s+الا\s+الله(?:\s+محمد\s+رسول\s+الله)?"
    r"|محمد\s+رسول\s+الله"
    r"|سبحان\s+الله(?:\s+وبحمده)?"
    r"|الله\s+اكبر"
    r"|لا\s+حول\s+ولا\s+قوة\s+الا\s+بالله"
    r"|استغفر\s+الله"
    r"|صلى\s+الله\s+عليه\s+وسلم"
    r"|رضي\s+الله\s+عنه(?:م|ما|ا)?)\s*[.،:!؟]*\s*$"
)

SCRIPTURE = {"quran", "hadith"}


@dataclass
class Segment:
    kind: str
    content: str
    source: str = ""
    score: float | None = None
    note: str = ""
    terms: list[dict] = field(default_factory=list)
    para: int = 0
    level: int = 0
    reviewed: bool = False
    footnote: bool = False


AYAH_SPAN = re.compile(r"﴿([^﴾]{3,})﴾")
AYAH_BRACE = re.compile(r"\{([^}]{3,})\}")
AYAH_NUMBER = re.compile(r"^[\s\d٠-٩۰-۹]+$")
AYAH_OPEN = re.compile(r"[﴿{]([^﴿{}﴾]{3,})$")
AYAH_DIGITS = re.compile(r"[\d٠-٩۰-۹]+|[*٭]")
CITATION = re.compile(r"\s*\[[^\]]{2,40}\]\s*")
_BIDI = r"[\s‎‏‪-‮⁦-⁩﻿ ]*"
CITATION_ONLY = re.compile(r"^" + _BIDI + r"\[[^\]]{2,60}\]" + _BIDI + r"[.،:؛]?" + _BIDI + r"$")
REF_SIGN = re.compile(r"[:：\d٠-٩]")
TAKHRIJ_SIGN = re.compile(
    r"^\s*\[?\s*(?:رواه|أخرجه|خرّجه|خرجه|متفق|صححه|صحّحه|حسنه|حسّنه|ضعفه|ضعّفه|"
    r"صحيح|حسن|ضعيف|انظر|ينظر|سنن|مسند)\b"
)
TAKHRIJ_BARE = re.compile(
    r"^\s*و?(?:متفق\s+عليه|رواه|أخرجه|خرّجه|خرجه|صححه|صحّحه|حسنه|حسّنه|ضعفه|ضعّفه)\b"
)
CITE_SURAH = re.compile(r"\[\s*(?:سورة\s+)?([^\]:\d]{2,25}?)\s*[:：]\s*\d")


def _strip_quotes(s: str) -> str:
    return s.strip('﴿﴾{}«»()“”" ')


def ayah_spans(unit: str) -> list[str]:
    """نصوصُ الآيات في المقطع، بأيّ القوسين كُتبت، دون أرقام الآيات."""
    spans = [s for s in AYAH_SPAN.findall(unit) if not AYAH_NUMBER.match(s)]
    spans += [s for s in AYAH_BRACE.findall(unit) if not AYAH_NUMBER.match(s)]
    if not spans:
        spans = [s for s in AYAH_OPEN.findall(unit.rstrip(" :.،")) if not AYAH_NUMBER.match(s)]
    return [t for t in (" ".join(AYAH_DIGITS.sub(" ", s).split()) for s in spans) if t]


def _quran_text(unit: str) -> str:
    """نص الآية إن وُجد وإلا المقطع كله؛ هو ما يُطابق بالمصحف."""
    spans = ayah_spans(unit)
    if spans:
        return " ".join(spans)
    return CITATION.sub(" ", _strip_quotes(unit))


def _display(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("«", "").replace("»", "")).strip()


def _is_citation(prev: Segment | None) -> bool:
    """هل الجملة السابقة صيغة إسناد فعلاً؟ القرينة بنية الجملة لا مجرد ألفاظ التعظيم."""
    return prev is not None and prev.kind == "attribution"


def cited_surah(*texts: str) -> str:
    """اسمُ السورة المطبَّع من أول إحالةٍ تُذكر، في المقطع أو فيما يليه."""
    for t in texts:
        m = CITE_SURAH.search(t or "")
        if m:
            return normalize(m.group(1))
    return ""


def _looks_quranic(matched: str, bracketed: bool) -> bool:
    """قرينتان بنيويتان تُسقطان المطابقة مهما علت درجتها؛ القوسان يعفيان منهما."""
    if _COMMA.search(_TAIL_PUNCT.sub("", matched)):
        return False
    return bracketed or len(matched.split()) >= BARE_AYAH_MIN_WORDS


def _classify_unit(
    unit: str,
    context: str,
    is_heading: bool,
    prev: Segment | None = None,
    nxt: str = "",
    quoted: bool = False,
) -> Segment:
    """يصنّف المقطع ثم يعلّق المصطلحات على ما ليس وحياً منه؛ المصطلح تعليق لا صنف."""
    seg = _kind_of(unit, context, is_heading, prev, nxt, quoted)
    seg.content = _display(seg.content)
    if seg.kind not in SCRIPTURE and not CITATION_ONLY.match(seg.content):
        seg.terms = get_matchers()[2].find(seg.content)
        if seg.kind == "text" and seg.terms and seg.note not in UNMATCHED:
            seg.kind = "term"
            seg.note = f"مصطلح: {seg.terms[0]['arabic']}"
    return seg


def _kind_of(
    unit: str,
    context: str,
    is_heading: bool,
    prev: Segment | None = None,
    nxt: str = "",
    quoted: bool = False,
) -> Segment:
    quran, hadith, _ = get_matchers()
    inner = _strip_quotes(unit)

    if is_heading:
        return Segment("title", unit, note="عنوان من نمط Word")

    if CITATION_ONLY.match(unit):
        bare = light(unit)
        if contains_surah_name(bare) and (
            REF_SIGN.search(bare) or len(normalize(bare).split()) <= 3
        ):
            return Segment("citation", unit, note="إحالة مصدر")
        if TAKHRIJ_SIGN.search(bare):
            return Segment("attribution", unit, note="تخريج المصدر")

    if TAKHRIJ_BARE.match(light(unit)) and len(normalize(unit).split()) <= 3:
        return Segment("attribution", unit, note="تخريج المصدر")

    if ATTRIBUTION.search(light(unit)) and unit.rstrip().endswith(":"):
        return Segment("attribution", unit, note="صيغة الإسناد — صياغة مُنير")

    cited = _is_citation(prev)
    spans = ayah_spans(unit) or ([unit.strip()] if quoted else [])
    quran_bias = (
        unit.lstrip().startswith(("﴿", "{"))
        or bool(spans)
        or (cited and bool(QURAN_HINT.search(light(context))))
    )
    hadith_bias = unit.startswith("«") or (cited and bool(HADITH_HINT.search(light(context))))

    after_heading = prev is not None and prev.kind == "title" and prev.level > 0

    q = quran.match(_quran_text(unit), short=bool(spans), prefer=cited_surah(unit, nxt))
    h = hadith.match(inner)
    q_min = UNCERTAIN if quran_bias else ACCEPT
    supplication = bool(SUPPLICATION.search(light(unit)))
    h_min = HADITH_SIGNAL if (hadith_bias or after_heading or supplication) else ACCEPT_HADITH
    opener = bool(ENDS_COLON.search(unit))
    qtext = _quran_text(unit)
    q_ok = q is not None and q.score >= q_min and not opener and _looks_quranic(qtext, bool(spans))
    h_ok = (
        h is not None
        and h.score >= h_min
        and not opener
        and not NARRATION.match(light(unit))
        and not FAMOUS_STANDALONE.match(normalize(_strip_quotes(unit)))
    )
    if spans:
        h_ok = False
    if q_ok and h_ok:
        q_ok, h_ok = q.score >= h.score, h.score > q.score

    if q_ok:
        label = "مطابقة تامة" if q.score >= 0.95 else f"مطابقة {int(q.score * 100)}%"
        return Segment("quran", unit, source=q.source, score=q.score, note=label)

    if h_ok:
        label = "مطابقة تامة" if h.score >= 0.95 else f"مطابقة {int(h.score * 100)}%"
        return Segment("hadith", unit, source=h.source, score=h.score, note=label)

    if unit.lstrip().startswith(("﴿", "{")) or spans:
        return Segment("text", unit, note=UNMATCHED_QURAN, score=q.score if q else None)

    if hadith.index.records and (unit.startswith("«") or (h and h.score >= UNCERTAIN)):
        return Segment("text", unit, note=UNMATCHED_HADITH, score=h.score if h else None)

    if ATTRIBUTION.search(light(unit)):
        return Segment("attribution", unit, note="صيغة الإسناد")

    n = light(unit)
    if OPENING.search(n):
        return Segment("text", unit, note="افتتاحية — أسلوب خطابي")
    if CLOSING.search(n):
        return Segment("text", unit, note="خاتمة — دعاء وتوصية")
    return Segment("text", unit, note="شرح — يُترجم بالسياق الدعوي")


def classify_paragraphs(paragraphs: list[Paragraph]) -> list[Segment]:
    segments: list[Segment] = []
    for n, p in enumerate(paragraphs, 1):
        if p.heading:
            segments.append(
                Segment(
                    "title", _display(p.text), note="عنوان من نمط Word", para=n, level=p.level or 1
                )
            )
            continue
        units = split_sentences(p.text)
        prev: Segment | None = None
        for i, unit in enumerate(units):
            context = units[i - 1] if i > 0 else ""
            nxt = units[i + 1] if i + 1 < len(units) else ""
            prev = _classify_unit(
                unit, context, False, prev, nxt, quoted=getattr(p, "quoted", False)
            )
            prev.para = n
            segments.append(prev)
    return segments
