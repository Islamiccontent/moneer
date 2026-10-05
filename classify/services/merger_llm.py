"""ضم ما أفرط المقطّع الآلي في قطعه بحكم النموذج؛ يعيد أرقام حدود تُلغى فقط ولا يكتب نصاً."""

import json
import os
from functools import lru_cache

from .reviewer import GEMINI_ENDPOINT, GROQ_ENDPOINT, UA, _key, _model, _post, provider

MIN_UNITS = 2

SYSTEM = """You review how an Arabic paragraph from Islamic da'wah literature
was split into translation units. The split was done mechanically, at
punctuation. Mechanical splitting cuts too much: it never misses a boundary,
it only invents boundaries that should not be there.

You are given the units, numbered 1..N. Between unit k and unit k+1 there is
BOUNDARY k. Return the numbers of the boundaries that should be REMOVED, so
that the two units on either side become one unit.

You cannot add a boundary, and you cannot change a single character. Removing
boundary k simply joins unit k to unit k+1.

## Remove a boundary when

- A NARRATION IS SEPARATED FROM THE WORDS IT REPORTS. When a narrator reports
  an event and then quotes the Prophet ﷺ, the report and the quotation are ONE
  unit: «خَرَجَ رَسُولُ اللَّهِ ﷺ وَنَحْنُ فِي الصُّفَّةِ، فَقَالَ:» followed
  by «أَيُّكُمْ يُحِبُّ…» — remove that boundary.
- A SUPPLICATION OR REMEMBRANCE WAS CUT IN THE MIDDLE. A du'a or dhikr is
  recited as one piece and translated as one, however long and however many
  commas and full stops it contains.
- A SENTENCE WAS CUT BEFORE IT COMPLETED — the second part cannot stand on its
  own: it begins with a relative pronoun, a conjunction completing the first,
  a parenthetical aside, or a list continuing the first.
- A SOURCE REFERENCE WAS CUT FROM NOTHING — a bare «[2]» or a fragment that is
  not a clause.

## Keep a boundary when

- The first unit is a bare ATTRIBUTION FORMULA ending in a colon — «قَالَ اللهُ
  تَعَالَى:», «وَعَنْ أَبِي هُرَيْرَةَ رَضِيَ اللهُ عَنْهُ قَالَ:» — naming the
  speaker or the narrator and nothing more. It is its own unit; keep it.
- A Qur'anic verse inside ﴿ ﴾ stands alone; keep it whole and separate.
- A source citation in brackets after a verse — «[الأحزاب: 59]» — is its own
  unit; keep it.
- Both sides are complete sentences, each standing on its own.

Most boundaries are correct. Returning an empty list is the common answer, and
is better than removing a boundary you are unsure about."""

SCHEMA = {
    "type": "object",
    "properties": {"remove": {"type": "array", "items": {"type": "integer"}}},
    "required": ["remove"],
}


def _prompt(units: list[str]) -> str:
    return "\n".join(f"{i}. {u}" for i, u in enumerate(units, 1))


def ask_merges(units: list[str]) -> list[int]:
    """أرقام الحدود المطلوب إلغاؤها، بعد تنقيتها من كل ما هو خارج المدى."""
    prov = provider()
    model, key = _model(prov), _key(prov)
    text = _prompt(units)
    if prov == "groq":
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": 512,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "merges",
                    "strict": True,
                    "schema": {**SCHEMA, "additionalProperties": False},
                },
            },
        }
        payload = _post_json(GROQ_ENDPOINT, body, {"Authorization": f"Bearer {key}"})
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    else:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 512,
                "responseMimeType": "application/json",
                "responseSchema": SCHEMA,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        payload = _post_json(GEMINI_ENDPOINT.format(model=model), body, {"x-goog-api-key": key})
        parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        content = parts[0]["text"] if parts else None
    if not content:
        return []
    raw = json.loads(content).get("remove", [])
    ok = {k for k in raw if isinstance(k, int) and 1 <= k < len(units)}
    return sorted(k for k in ok if not _vetoed(units[k - 1]))


def _vetoed(before: str) -> bool:
    """صيغة الإسناد المنتهية بنقطتين وحدة مستقلة لا تُضم إلى ما بعدها."""
    from .classifier import ATTRIBUTION
    from .normalizer import light

    return bool(before.rstrip().endswith(":") and ATTRIBUTION.search(light(before)))


def _post_json(url, body, headers):
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA, **headers},
    )
    return _post(req)


def apply_merges(units: list[str], remove: list[int]) -> list[str]:
    """ضمٌّ خالص: لا يُضاف حرف، ولا يُحذف، ولا يُعاد ترتيب."""
    out: list[str] = []
    drop = set(remove)
    for i, u in enumerate(units, 1):
        if out and (i - 1) in drop:
            out[-1] = f"{out[-1]} {u}"
        else:
            out.append(u)
    return out


@lru_cache(maxsize=1)
def enabled() -> bool:
    return os.environ.get("LLM_MERGE") == "1"


def merge(units: list[str]) -> list[str]:
    """يرجع الوحدات مضمومةً، أو كما هي عند أي تعذّر."""
    if not enabled() or len(units) < MIN_UNITS:
        return units
    try:
        return apply_merges(units, ask_merges(units))
    except Exception:
        return units
