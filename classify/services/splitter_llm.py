"""تقطيع الفقرة بنموذج لغوي يعيد بدايات الوحدات فقط، مع تحقق بنيوي قاطع في النص الأصلي."""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from .normalizer import DIACRITICS
from .reviewer import GEMINI_ENDPOINT, GROQ_ENDPOINT, UA, _key, _model, _post, provider

MIN_WORDS = 12
MARKER_WORDS = 3

SYSTEM = """You segment an Arabic paragraph from Islamic da'wah literature into
TRANSLATION UNITS. A translation unit is a span of complete meaning that a
translator can render on its own, without needing the rest of the paragraph.

## What you return

You do NOT return the text. You return only the OPENING WORDS of each unit
after the first one — three words, copied from the source character for
character, including its diacritics exactly as written.

The caller locates each opening in the source and cuts the ORIGINAL text there.
Anything you write that is not found verbatim in the source, or that appears out
of order, causes your entire answer to be discarded. So:

- Copy, never retype from memory. Never fix spelling, hamza, or diacritics.
- Never return the first words of the paragraph (that is unit 1, already known).
- Never invent, summarise, explain, translate, or reorder.
- If the paragraph is a single unit, return an empty list.

## The one rule

ONE COMPLETE SENTENCE = ONE UNIT. A sentence is complete when it states a
finished thought that stands without what follows it. Cut at the end of every
such sentence, and nowhere else. If a paragraph holds several sentences, it
yields several units, in their original order.

These are complete sentences, each its own unit:
- A Qur'anic verse, the whole span inside ﴿ ﴾, from first word to last.
- A section heading or a title line.
- An attribution formula on its own — «قَالَ اللهُ تَعَالَى:», «عَنْ أَبِي
  هُرَيْرَةَ رَضِيَ اللهُ عَنْهُ قَالَ:» — the naming of who speaks or who
  narrates, ending in a colon.
- An ordinary prose sentence of the author's own words.

## Where a sentence does NOT end

- At a comma (،). Arabic coordinates heavily: most commas join one thought.
  A sentence with ten commas is one unit, not eleven.
- At a semicolon (؛). It binds two clauses that belong together.
- At a colon that introduces a title, a name, or a definition rather than a
  speaker — «اختصرته من كتابي: الذكر والدعاء» is ONE unit.
- At an abbreviation dot — «د. سعيد» is one name.
- Inside parentheses — «بهيمة الأنعام (الإبل والبقر والغنم)» stays whole.
- After a numbered step prefix — «الخطوة 6: أقول: …» keeps its number.

## Two rules that override everything above

1. A QUOTED SUPPLICATION, REMEMBRANCE OR VERSE IS ONE UNIT, however long. Text
   inside «» or ﴿﴾ is never split, even at 70 words with a dozen commas and
   several full stops. It is recited as one piece and translated as one.

2. A NARRATION KEEPS ITS EMBEDDED QUOTATION. When a narrator reports an event
   and then quotes the Prophet ﷺ, the report and the quotation form one unit:
   «… قَالُوا بَلَى. قَالَ: ذِكْرُ اللَّهِ تَعَالَى» is ONE unit, not two.

Do not classify. Naming each unit — verse, hadith, heading, attribution, term —
is done elsewhere, from the Qur'anic text, the hadith corpora and the glossary.
Your only task is where the sentences end."""

SCHEMA = {
    "type": "object",
    "properties": {"cuts": {"type": "array", "items": {"type": "string"}}},
    "required": ["cuts"],
    "additionalProperties": False,
}

GEMINI_SCHEMA = {k: v for k, v in SCHEMA.items() if k != "additionalProperties"}

EXAMPLES = [
    (
        "إِنَّ الحَمْدَ للَّهِ، نَحْمَدُهُ، وَنَسْتَعِينُهُ، وَنَسْتَغْفِرُهُ، وَنَعُوذُ بِاللَّهِ مِنْ شُرُورِ "
        "أَنْفُسِنَا، وَسَيِّئَاتِ أَعْمَالِنَا، مَنْ يَهْدِهِ اللَّهُ فَلَا مُضِلَّ لَهُ، وَمَنْ يُضْلِلْ فَلَا "
        "هَادِيَ لَهُ، وَأَشْهَدُ أَنْ لَا إِلَهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، وَأَشْهَدُ أَنَّ "
        "مُحَمَّدًا عَبْدُهُ وَرَسُولُهُ، أَمَّا بَعْدُ:",
        ["وَنَعُوذُ بِاللَّهِ مِنْ", "مَنْ يَهْدِهِ اللَّهُ", "وَمَنْ يُضْلِلْ فَلَا", "وَأَشْهَدُ أَنْ لَا", "أَمَّا بَعْدُ:"],
    ),
    (
        "«لَا إِلَهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ المُلْكُ، وَلَهُ الحَمدُ، وَهُوَ عَلَى "
        "كُلِّ شَيْءٍ قَدِيرٌ، لَا حَوْلَ وَلَا قُوَّةَ إِلَّا بِاللَّهِ».",
        [],
    ),
]


def _bare(s: str) -> str:
    """تجريدٌ للالتماس: التشكيل والمسافات لا تُعوَّل عليها في ردّ النموذج."""
    return re.sub(r"\s+", "", DIACRITICS.sub("", s))


@lru_cache(maxsize=1)
def examples() -> list[tuple[str, list[str]]]:
    """أمثلة مستخرجة من ملفات المرجع؛ SPLIT_EXAMPLES=0 يعطّلها و<عدد> يحدّها."""
    cap = os.environ.get("SPLIT_EXAMPLES", "")
    if cap == "0":
        return list(EXAMPLES)
    path = Path(__file__).resolve().parent.parent / "data" / "split_examples.json"
    if not path.exists():
        return list(EXAMPLES)
    data = json.loads(path.read_text(encoding="utf-8"))
    if cap.isdigit():
        data = data[: int(cap)]
    return [(e["text"], e["cuts"]) for e in data]


def _messages(text: str) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]
    for src, cuts in examples():
        msgs += [
            {"role": "user", "content": src},
            {"role": "assistant", "content": json.dumps({"cuts": cuts}, ensure_ascii=False)},
        ]
    msgs.append({"role": "user", "content": text})
    return msgs


def ask_cuts(text: str) -> list[str]:
    prov = provider()
    model, key = _model(prov), _key(prov)
    if prov == "groq":
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 1024,
            "messages": _messages(text),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "cuts", "strict": True, "schema": SCHEMA},
            },
        }
        payload = _post_json(GROQ_ENDPOINT, body, {"Authorization": f"Bearer {key}"})
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    else:
        contents = []
        for src, cuts in examples():
            contents += [
                {"role": "user", "parts": [{"text": src}]},
                {
                    "role": "model",
                    "parts": [{"text": json.dumps({"cuts": cuts}, ensure_ascii=False)}],
                },
            ]
        contents.append({"role": "user", "parts": [{"text": text}]})
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_SCHEMA,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        payload = _post_json(GEMINI_ENDPOINT.format(model=model), body, {"x-goog-api-key": key})
        parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        content = parts[0]["text"] if parts else None
    if not content:
        return []
    return [c for c in json.loads(content).get("cuts", []) if isinstance(c, str) and c.strip()]


def _post_json(url, body, headers):
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA, **headers},
    )
    return _post(req)


def apply_cuts(text: str, cuts: list[str]) -> list[str] | None:
    """قطعُ النص الأصلي عند البدايات. يرجع None إن لم تتحقق البنية."""
    bare, idx = "", []
    for i, ch in enumerate(text):
        if ch.isspace() or DIACRITICS.match(ch):
            continue
        bare += ch
        idx.append(i)

    at, points = 0, []
    for c in cuts:
        needle = _bare(c)
        if not needle:
            return None
        pos = bare.find(needle, at)
        if pos < 0 or pos == 0:
            return None
        points.append(idx[pos])
        at = pos + 1
    if points != sorted(points):
        return None

    out, prev = [], 0
    for p in points + [len(text)]:
        piece = text[prev:p].strip()
        if piece:
            out.append(piece)
        prev = p
    if _bare("".join(out)) != _bare(text):
        return None
    return out or None


def split(text: str) -> list[str] | None:
    """يرجع القطع، أو None ليتولّاها المقطّع الآليّ."""
    if os.environ.get("LLM_SPLIT") != "1" or len(text.split()) < MIN_WORDS:
        return None
    try:
        cuts = ask_cuts(text)
    except Exception:
        return None
    return apply_cuts(text, cuts) if cuts else None
