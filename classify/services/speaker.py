"""نسبة القول إلى قائله من صيغة التقديم: ما قاله صحابي أو تابعي أثر لا حديث."""

from __future__ import annotations

import re

_DIAC = re.compile(r"[ً-ْٰـۖ-ۭ]")

PROPHET = re.compile(
    r"(النبي|رسول الله|الرسول|المصطفى|ﷺ|صلى الله عليه وسلم|عليه الصلاة والسلام|عليه السلام)"
)
_PLACE_BEFORE_PROPHET = re.compile(
    r"(مسجد|مدينة|سنة|حديث|قبر|منبر|زمن|عهد|بيت|حجرة|أصحاب|صحابة|زوج|آل|بعثة|هجرة|سيرة)"
    r"\s+(?:ال)?(?:النبي|رسول الله|الرسول|المصطفى)"
)
COMPANION_HONORIFIC = re.compile(r"رضي الله عن(?:ه|ها|هما|هم)")
SCHOLAR = re.compile(
    r"رحمه الله|رحمها الله|رحمهم الله|الإمام|الشيخ|العلامة|الحافظ|المحدث|الفقيه|المفسر"
)

COMPANIONS = (
    "عمر بن الخطاب",
    "عمر",
    "أبو بكر",
    "أبي بكر",
    "أبا بكر",
    "عثمان",
    "علي بن أبي طالب",
    "علي",
    "ابن عباس",
    "ابن مسعود",
    "ابن عمر",
    "عائشة",
    "أبو هريرة",
    "أبي هريرة",
    "أبا هريرة",
    "أنس",
    "معاذ",
    "أبو الدرداء",
    "أبي الدرداء",
    "أبو ذر",
    "أبي ذر",
    "سلمان",
    "بلال",
    "جابر",
    "أبي بن كعب",
    "زيد بن ثابت",
    "حذيفة",
    "خالد بن الوليد",
    "سعد بن أبي وقاص",
    "طلحة",
    "الزبير",
    "عبد الرحمن بن عوف",
    "فاطمة",
    "خديجة",
    "حفصة",
    "أم سلمة",
    "أبو سعيد الخدري",
    "أبي سعيد",
    "أبو موسى الأشعري",
    "عبد الله بن عمرو",
    "عمرو بن العاص",
    "معاوية",
    "المغيرة",
    "أبو أمامة",
    "سعيد بن المسيب",
    "الحسن البصري",
    "عروة بن الزبير",
    "مجاهد",
    "عطاء",
    "طاوس",
    "قتادة",
    "عكرمة",
)
_COMP_RE = re.compile(
    r"(?<![\w])("
    + "|".join(map(re.escape, sorted(COMPANIONS, key=len, reverse=True)))
    + r")(?![\w])"
)

PROPHET_SAID = re.compile(
    r"(?:أن|انه|أنه|ان|سمعت|سمع|عن)\s+(?:النبي|رسول الله|الرسول|المصطفى)"
    r"[^.!؟]{0,60}?(?:قال|يقول|خطب|نادى)"
)

SPEECH = re.compile(
    r"(?:^|[\s،؛(«\"])(?:ف|و)?(قال|قالت|يقول|تقول|سأل|سألت|أجاب|أجابت|خطب|نادى|صاح|رد|قالا|قالوا|فقال|فقالت)"
    r"(?:\s+(?:له|لها|لهما|لهم|لي|لنا|لك))?\s*([^:،؛.!؟]{0,60})"
)
_INTRO_END = re.compile(r"[:：]\s*[«\"(]?\s*$")


def norm(t: str) -> str:
    return _DIAC.sub("", t or "")


def classify_person(text: str) -> str | None:
    """prophet / companion / scholar / None لنصٍّ قصيرٍ يسمّي شخصاً."""
    t = norm(text)
    if not t.strip():
        return None
    if PROPHET.search(t) and not _PLACE_BEFORE_PROPHET.search(t):
        return "prophet"
    if COMPANION_HONORIFIC.search(t) or _COMP_RE.search(t):
        return "companion"
    if SCHOLAR.search(t):
        return "scholar"
    return None


def protagonist(clause: str) -> str | None:
    """أوّلُ شخصٍ يُذكر في الجملة، بإهمالِ «مسجد النبيّ» ونحوِه."""
    t = norm(clause)
    hits = []
    for m in PROPHET.finditer(t):
        before = t[max(0, m.start() - 12) : m.start()]
        if _PLACE_BEFORE_PROPHET.search(before + m.group(0)):
            continue
        hits.append((m.start(), "prophet"))
    for m in COMPANION_HONORIFIC.finditer(t):
        hits.append((m.start(), "companion"))
    for m in _COMP_RE.finditer(t):
        hits.append((m.start(), "companion"))
    if not hits:
        return None
    return min(hits)[1]


def speaker_of(intro: str) -> str | None:
    """المتكلّمُ الذي تُقدِّم له صيغةُ التقديم، أو None إن لم تُفهَم."""
    t = norm(intro).strip()
    if not _INTRO_END.search(t):
        return None
    clause = re.split(r"[.!؟]", t.rstrip(' :：«"('))[-1]
    if PROPHET_SAID.search(clause):
        return "prophet"
    subj = None
    for m in SPEECH.finditer(clause):
        subj = m.group(2).strip()
    if subj:
        kind = classify_person(subj)
        if kind:
            return kind
    if subj is not None:
        return protagonist(clause)
    return None


def reattribute(segments) -> dict:
    """يعدّل القائمة موضعياً: حديث قائله صحابي ← أثر، وقول موثّق لصحابي ← أثر؛ يعيد إحصاءً."""
    stats = {"hadith_to_athar": 0, "text_to_athar": 0}
    for i, seg in enumerate(segments):
        if seg.kind not in ("hadith", "text", "term"):
            continue
        prev = [s for s in segments[:i] if s.para == seg.para]
        if not prev:
            continue
        intro = " ".join(s.content for s in prev[-2:])
        who = speaker_of(intro)
        if who != "companion":
            continue
        if seg.kind == "hadith":
            seg.kind = "athar"
            seg.note = "قول صحابيّ لا حديث — نُسب بصيغة التقديم" + (
                f" | {seg.note}" if seg.note else ""
            )
            seg.reviewed = True
            stats["hadith_to_athar"] += 1
        else:
            nxt = next((s for s in segments[i + 1 :] if s.para == seg.para), None)
            if nxt is not None and nxt.kind == "citation":
                seg.kind = "athar"
                seg.note = "قول صحابيّ — نُسب بصيغة التقديم وأُحيل إلى مصدره"
                seg.reviewed = True
                stats["text_to_athar"] += 1
    return stats
