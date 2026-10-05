"""تحويل مقاطع المستند إلى شكل وحدات واجهة «منصة مُنير» (index.html المجمّع)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import exporter
from .normalizer import normalize

_REF = re.compile(r"سورة\s+(.+?)\s*[—\-–]\s*(\d+)")
_EMPTY_AYA_BRACKETS = re.compile(r"\s*﴿\s*﴾")
_KHATIMA = re.compile(r"^(?:ال)?خاتمة\b")


def title_label(text: str) -> str:
    """وسم وحدة العنوان في الواجهة: القسم الختامي «نص عام» وما سواه «عنوان»."""
    return "نص عام" if _KHATIMA.match((text or "").strip()) else "عنوان"


_TAKHRIJ = re.compile(
    r"^\s*[(\[]?\s*(رواه|أخرجه|خرّجه|خرجه|متفق عليه|صححه|صحّحه|حسنه|حسّنه|ضعفه|ضعّفه|"
    r"صحيح|حسن|ضعيف|انظر|ينظر|أخرج|رواية|في صحيح|في سنن|في مسند)"
)
_ISNAD = re.compile(r"^\s*(حدثنا|حدّثنا|أخبرنا|أنبأنا|سمعت|عن\s)")


@lru_cache(maxsize=1)
def _surah_numbers() -> dict:
    p = Path(__file__).resolve().parents[1] / "data" / "quran.json"
    if not p.exists():
        return {}
    return {r["surah"]: int(r["surah_no"]) for r in json.loads(p.read_text(encoding="utf-8"))}


def _quran_ref(source: str) -> tuple[int, int] | None:
    m = _REF.search(source or "")
    if not m:
        return None
    no = _surah_numbers().get(m.group(1).strip())
    return (no, int(m.group(2))) if no else None


def _pct(conf: float) -> str:
    return f"{int(round(conf * 100))}%"


_EDGE_PUNCT = ".,،؛;:!?؟«»\"'()[]{}﴿﴾"


def surface(text: str, term: str) -> str:
    """صورة المدخل المعجمي كلماتٍ كاملة كما كُتبت في النص، بنافذة كلمات يطابق تطبيعها المدخل."""
    want = " ".join(normalize(term).split())
    words = text.split()
    size = max(1, len(want.split()))
    for i in range(len(words) - size + 1):
        window = words[i : i + size]
        if want in " ".join(normalize(w) for w in window):
            return " ".join(window).strip(_EDGE_PUNCT)
    return term


def _terms(seg) -> list[dict]:
    out = []
    for t in seg.terms or []:
        if not isinstance(t, dict):
            continue
        w = t.get("surface") or t.get("arabic")
        en = t.get("english")
        if not w or not en:
            continue
        w = surface(seg.content, w)
        out.append({"w": w, "en": en, "def": t.get("note") or t.get("label") or "", "tr": ""})
    return out


def attribution_label(text: str) -> str:
    """«تخريج» لعزو الحديث إلى مصدره، وصيغ الرواية وتمهيد الاقتباس «نص عام»."""
    if _TAKHRIJ.search(text or ""):
        return "تخريج"
    return "نص عام"


def variant_warning(note: str) -> str:
    """من ملاحظةِ المحوّل («⚠ يخالف رسم المصحف — زائد: X — ناقص: Y») إلى تنبيهٍ خفيفٍ للمحرِّر."""
    tail = (note or "").split(exporter.MUSHAF_VARIANT, 1)[-1].strip(" —-|")
    detail = f" ({tail})" if tail else ""
    return f"⚠ الآية بها خطأ{detail} — يُرجى تعديل النصّ."


def to_ui_segments(segments) -> list[dict]:
    """قائمةُ وحداتِ الواجهة من مقاطعِ المصنِّف (نماذجَ أو بُنى، كلاهما يحمل الحقولَ نفسَها)."""
    out, part, fn = [], "", 0
    for s in segments:
        conf, _reason = exporter.confidence(s)
        ar = _EMPTY_AYA_BRACKETS.sub("", s.content).strip()
        base = {"ar": ar, "conf": _pct(conf), "en": "", "meta": "", "part": part}
        if s.kind == "title":
            part = s.content.strip()
            out.append(
                {
                    **base,
                    "k": "text",
                    "lead": True,
                    "tagLabel": title_label(s.content),
                    "part": part,
                }
            )
            continue
        if s.kind == "quran":
            variant = exporter.MUSHAF_VARIANT in (s.note or "")
            out.append(
                {
                    **base,
                    "k": "aya",
                    "meta": "",
                    "link": "",
                    "en": "",
                    "src": "",
                    "warn": variant,
                    "warnText": variant_warning(s.note) if variant else "",
                }
            )
        elif s.kind == "hadith":
            fn += 1
            out.append(
                {
                    **base,
                    "k": "hadith",
                    "meta": "",
                    "link": "",
                    "en": "Hadith",
                    "src": "",
                    "fn": fn,
                    "fnText": "Hadith",
                }
            )
        elif s.kind == "athar":
            fn += 1
            out.append(
                {
                    **base,
                    "k": "athar",
                    "meta": "",
                    "link": "",
                    "en": "Athar",
                    "src": "",
                    "fn": fn,
                    "fnText": "Athar",
                }
            )
        elif s.kind == "term" and _terms(s):
            terms = _terms(s)
            out.append(
                {
                    **base,
                    "k": "term",
                    "terms": terms,
                    "meta": " · ".join(f"{t['w']} → {t['en']}" for t in terms),
                    "link": "معجم مُنير",
                    "src": "معجم المصطلحات",
                }
            )
        elif s.kind == "attribution":
            out.append(
                {**base, "k": "text", "lead": True, "tagLabel": attribution_label(s.content)}
            )
        elif s.kind == "citation":
            out.append({**base, "k": "text", "lead": True, "tagLabel": "عزو", "conf": "100%"})
        else:
            out.append({**base, "k": "text"})
    return out
