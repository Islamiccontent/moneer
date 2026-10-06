"""القواعد القطعية ومؤشرات الاشتباه المحلية — تعمل قبل النموذج وبلا تكلفة.

الفلسفة (من المحادثة): «يمكن للنظام كشف نسبة كبيرة من الأخطاء آليًا دون
الحاجة إلى نموذج لغوي ثقيل». ما يُكشف هنا:

قطعي (يُسجَّل خطأً مباشرة):
    FRM-EMP  ترجمة فارغة                 → يُستبعد الصف من الإرسال للنموذج
    FRM-CPY  نسخ النص الأصلي دون ترجمة    → يُستبعد الصف من الإرسال للنموذج
    FRM-ARB  حروف عربية دخيلة             → يُسجَّل ويُرسل الصف للنموذج مع ذلك
    FRM-BRK  أقواس غير مغلقة (والأصل سليم)

مؤشر اشتباه (لا يُسجَّل خطأً، بل يُمرَّر للنموذج «تنبيهًا آليًا» ليتحقق):
    FRM-LEN  طول شاذ نسبةً إلى وسيط الملف
    FRM-DUP  الترجمة نفسها لنصين أصليين مختلفين

قاعدة الحروف العربية منقولة من translation-check/engine/rules.py مع إضافة
علامة نهاية الآية ۝ (U+06DD) إلى المستثنيات لأنها رمز لا حرف.
"""

import re
import statistics
from difflib import SequenceMatcher

_ARABIC_RANGES = [
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
]
ARABIC_RE = re.compile("[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in _ARABIC_RANGES) + "]")
# ﷺ ﷻ ﷲ ﷴ ﷳ ﷰ ﷱ ﴾ ﴿ ۝ وأرقام عربية-هندية ٠-٩ وعلامات ترقيم عربية شائعة
_ALLOWED_CODEPOINTS = [
    0xFDFA,
    0xFDFB,
    0xFDF2,
    0xFDF4,
    0xFDF3,
    0xFDF0,
    0xFDF1,
    0xFD3E,
    0xFD3F,
    0x06DD,
    0x060C,
    0x061B,
    0x061F,
    0x066A,
    0x066B,
    0x066C,
]
_ALLOWED_RE = re.compile("[" + "".join(chr(c) for c in _ALLOWED_CODEPOINTS) + "٠-٩]")
_DIACRITICS_RE = re.compile("[ً-ْٰـ]")
SALLALLAHU_RE = re.compile(r"صلى\s+الله\s+عليه\s+وسلم")

_PAIRS = {"(": ")", "[": "]", "{": "}", "«": "»", "﴿": "﴾"}
_CLOSERS = set(_PAIRS.values())

# حدود المؤشرات — قابلة للتعديل من الإعدادات
DEFAULT_SHORT_RATIO = 0.40  # الترجمة أقصر من 40% من النسبة الوسيطة للملف
DEFAULT_LONG_RATIO = 3.0  # الترجمة أطول من 3 أضعاف النسبة الوسيطة
MIN_SOURCE_CHARS_FOR_LEN = 40
MIN_SOURCE_WORDS_FOR_DUP = 3
DUP_SIMILARITY_MAX = 0.55  # تشابه المصدرَين (0-1) الذي دونه تُعدّ الترجمة المتكررة مشبوهة


def arabic_letters(text):
    """الحروف العربية غير المستثناة في نص — سلسلة (فارغة إن لم توجد)."""
    if not isinstance(text, str):
        return ""
    cleaned = _DIACRITICS_RE.sub("", text)
    cleaned = _ALLOWED_RE.sub("", cleaned)
    cleaned = SALLALLAHU_RE.sub("", cleaned)
    return "".join(ARABIC_RE.findall(cleaned))


def normalize_arabic(text):
    """تطبيع للمقارنة: إزالة التشكيل والترقيم وتوحيد الألف والياء والتاء."""
    text = _DIACRITICS_RE.sub("", str(text or ""))
    text = re.sub("[إأآا]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def unbalanced_brackets(text):
    """True إن كان في النص قوس مفتوح بلا إغلاق أو إغلاق بلا فتح."""
    stack = []
    for ch in str(text or ""):
        if ch in _PAIRS:
            stack.append(_PAIRS[ch])
        elif ch in _CLOSERS:
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                return True
    return bool(stack)


def _finding(code, explanation, location="", confidence=100, detection="قطعي", severity=None):
    """يبني ملاحظة قاعدية بالشكل نفسه الذي تُحوَّل إليه ملاحظات النموذج."""
    return {
        "code": code,
        "severity": severity,  # None → الافتراضي للنوع
        "sharia_sensitive": False,
        "detection": detection,
        "confidence": confidence,
        "location": location,
        "explanation": explanation,
        "required_action": "",
        "suggested_fix": "",
        "source": "rule",
    }


def length_ratio_stats(rows):
    """وسيط نسبة طول الترجمة إلى الأصل في الملف (للصفوف ذات الأصل ≥ 20 حرفًا)."""
    ratios = []
    for r in rows:
        s = len(str(r.get("source") or "").strip())
        t = len(str(r.get("target") or "").strip())
        if s >= 20 and t > 0:
            ratios.append(t / s)
    return statistics.median(ratios) if len(ratios) >= 10 else None


def duplicate_target_map(rows):
    """{target_normalized: [row_index, ...]} للترجمات المتكررة لمصادر مختلفة
    اختلافًا معتبرًا (تشابه المصدرين < DUP_SIMILARITY_MAX)."""
    by_target = {}
    for idx, r in enumerate(rows):
        tgt = re.sub(r"\s+", " ", str(r.get("target") or "")).strip().lower()
        if len(tgt) < 3:
            continue
        by_target.setdefault(tgt, []).append(idx)

    suspicious = {}
    for indexes in by_target.values():
        if len(indexes) < 2:
            continue
        sources = [normalize_arabic(rows[i].get("source")) for i in indexes]
        if any(len(s.split()) < MIN_SOURCE_WORDS_FOR_DUP for s in sources):
            continue
        # يكفي أن يختلف مصدران اختلافًا معتبرًا لتُعدّ المجموعة مشبوهة
        flagged = set()
        for a in range(len(indexes)):
            for b in range(a + 1, len(indexes)):
                if SequenceMatcher(None, sources[a], sources[b]).ratio() < DUP_SIMILARITY_MAX:
                    flagged.add(indexes[a])
                    flagged.add(indexes[b])
        for i in flagged:
            suspicious[i] = [j for j in indexes if j != i]
    return suspicious


def apply_rules(
    rows, arabic_script=False, short_ratio=DEFAULT_SHORT_RATIO, long_ratio=DEFAULT_LONG_RATIO
):
    """يطبّق القواعد على قائمة صفوف (قواميس فيها source/target/row_type).

    يعيد قائمة بطول الصفوف؛ لكل صف قاموس:
        findings  ملاحظات قطعية تُسجَّل مباشرة
        hints     تنبيهات نصية تُمرَّر للنموذج
        skip      سبب استبعاد الصف من الإرسال (أو None)
    """
    median_ratio = length_ratio_stats(rows)
    dup_map = duplicate_target_map(rows)
    results = []

    for idx, r in enumerate(rows):
        source = str(r.get("source") or "")
        target = str(r.get("target") or "")
        findings, hints, skip = [], [], None
        stripped = re.sub(r"[\s\W_]+", "", target)

        if not stripped:
            findings.append(_finding("FRM-EMP", "خانة الترجمة فارغة."))
            results.append({"findings": findings, "hints": hints, "skip": "ترجمة فارغة"})
            continue

        if normalize_arabic(source) and normalize_arabic(source) == normalize_arabic(target):
            findings.append(
                _finding("FRM-CPY", "الترجمة نسخة من النص العربي الأصلي.", location=target[:80])
            )
            results.append({"findings": findings, "hints": hints, "skip": "نسخ النص الأصلي"})
            continue

        if not arabic_script:
            letters = arabic_letters(target)
            if letters:
                sample = letters[:20]
                findings.append(
                    _finding("FRM-ARB", f"حروف عربية داخل الترجمة: «{sample}».", location=sample)
                )

        if unbalanced_brackets(target) and not unbalanced_brackets(source):
            findings.append(
                _finding(
                    "FRM-BRK",
                    "قوس مفتوح بلا إغلاق أو مغلق بلا فتح في الترجمة، والأصل سليم.",
                    confidence=90,
                )
            )

        # مؤشرات الاشتباه → تنبيهات للنموذج لا أخطاء
        if median_ratio and len(source.strip()) >= MIN_SOURCE_CHARS_FOR_LEN:
            ratio = len(target.strip()) / max(len(source.strip()), 1)
            if ratio < median_ratio * short_ratio:
                pct = int(round((1 - ratio / median_ratio) * 100))
                hints.append(f"طول الترجمة أقل من المعتاد بنسبة {pct}% — احتمال سقوط جزء من النص")
            elif ratio > median_ratio * long_ratio and not re.search(r"[\[(].{15,}[\])]", target):
                hints.append("طول الترجمة أكبر من المعتاد بكثير — احتمال زيادة ليست في الأصل")

        if idx in dup_map:
            others = dup_map[idx][:2]
            samples = "؛ ".join(str(rows[j].get("source") or "")[:40] for j in others)
            hints.append(
                f"الترجمة نفسها وردت لنصوص أصلية مختلفة (مثل: {samples}) — "
                "تحقق من مطابقتها لهذا النص"
            )

        results.append({"findings": findings, "hints": hints, "skip": skip})
    return results
