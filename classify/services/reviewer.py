"""مراجعة بنموذج لغوي لما لم يحسمه المطابق الحتمي، بمخرج مغلق ومرشّحين من فهرسنا وحده."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from .matchers import get_matchers
from .normalizer import normalize

LABELS = ["آية", "حديث", "نص"]
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULTS = {"gemini": "gemini-3.1-flash-lite", "groq": "qwen/qwen3.8-27b"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) textsegmenter/1.0"

SYSTEM = """أنت مراجعٌ لتصنيف مقاطع نصوص إسلامية. مهمتك حكمٌ لا إنشاء.

تُعطى مقطعاً، وقد تُعطى معه مرشَّحين مرقَّمين من فهرسنا. عليك:
1. تحديد صنف المقطع: «آية» أو «حديث» أو «نص».
2. إن طابق المقطعُ أحدَ المرشَّحين، أعد **رقمه فقط** (مثل "2").
   وإن لم يطابق أحدٌ منهم، أعد سلسلة فارغة "".

ضوابط قاطعة:
- candidate_id رقمٌ مجرّد من القائمة أو سلسلة فارغة. لا نصّ ولا شرح معه.
- لا تكتب نص آية ولا نص حديث ولا جزءاً منهما.
- لا تذكر سورة ولا رقم آية ولا راوياً ولا كتاباً ولا رقم حديث.
- إن شككت فأعد «نص» ورقماً فارغاً.

تعريف الأصناف:
- «آية»: المقطع نصُّ قرآن منقولٌ بلفظه.
- «حديث»: المقطع كلامُ النبي ﷺ أو دعاءٌ مأثور عنه، منقولٌ بلفظه.
- «نص»: كلام المؤلف أو الخطيب، أو عنوان، أو صيغة إسناد مثل «قال الله تعالى:».
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": LABELS},
        "candidate_id": {"type": "string"},
    },
    "required": ["label", "candidate_id"],
    "additionalProperties": False,
}


def provider() -> str:
    return (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()


def _key(prov: str) -> str:
    return os.environ.get("GROQ_API_KEY" if prov == "groq" else "GEMINI_API_KEY", "")


def _model(prov: str) -> str:
    return os.environ.get("GROQ_MODEL" if prov == "groq" else "GEMINI_MODEL") or DEFAULTS[prov]


def _prompt(text: str, cands: list[dict]) -> str:
    listing = "\n".join(f"{n}. {c['text']}" for n, c in enumerate(cands, 1)) or "(لا مرشَّحين)"
    return f"المقطع:\n{text}\n\nالمرشَّحون من الفهرس:\n{listing}"


@lru_cache(maxsize=1)
def examples() -> list[dict]:
    """أمثلة few-shot موسومة بشرياً؛ تُستبعد من القياس."""
    if os.environ.get("LLM_FEWSHOT") == "0":
        return []
    path = Path(__file__).resolve().parent.parent / "data" / "fewshot.json"
    if not path.exists():
        return []
    shots = json.loads(path.read_text(encoding="utf-8"))
    cap = int(os.environ.get("LLM_FEWSHOT_N", "6"))
    by_label: dict[str, list] = {}
    for e in shots:
        by_label.setdefault(e["label"], []).append(e)
    out, i = [], 0
    while len(out) < cap and any(v[i:] for v in by_label.values()):
        for lab in ("حديث", "نص", "آية"):
            if len(out) < cap and i < len(by_label.get(lab, [])):
                out.append(by_label[lab][i])
        i += 1
    return out


def example_texts() -> set[str]:
    return {e["content"].strip() for e in examples()}


def _shots() -> list[tuple[str, str]]:
    """أزواج (سؤال، جواب) تُقدَّم أدوار محادثة سابقة لتثبيت الحكم على الصنف."""
    out = []
    for e in examples():
        out.append(
            (
                _prompt(e["content"], []),
                json.dumps({"label": e["label"], "candidate_id": ""}, ensure_ascii=False),
            )
        )
    return out


class Throttle:
    """مباعدة الطلبات عبر الخيوط كلها احتراماً لحدود معدل الخدمة."""

    def __init__(self, rpm: int = 0):
        self.interval = 60.0 / rpm if rpm else 0.0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            sleep_for = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval
        if sleep_for:
            time.sleep(sleep_for)


THROTTLE = Throttle(int(os.environ.get("GEMINI_RPM", "0")))


def enabled() -> bool:
    return os.environ.get("LLM_REVIEW") == "1" and bool(_key(provider()))


def retry_delay(raw: str, attempt: int) -> float:
    """احترام retryDelay الذي ترسله الخدمة، وإلا تضاعفٌ أُسّي."""
    try:
        for d in json.loads(raw)["error"].get("details", []):
            if "retryDelay" in d:
                return float(str(d["retryDelay"]).rstrip("s")) + 1
    except Exception:
        pass
    return 2.0**attempt


def candidates_for(text: str, k: int = 4) -> list[dict]:
    """أعلى المرشَّحين من فهرسنا — هذه وحدها ما يُسمح للنموذج بالاختيار منه."""
    quran, hadith, _ = get_matchers()
    out, q = [], normalize(text)
    for tag, m in (("Q", quran), ("H", hadith)):
        idx = m.index
        for i in idx.candidates(text)[:k]:
            r = idx.records[i]
            out.append(
                {
                    "id": (
                        f"Q:{r['surah_no']}:{r['ayah']}"
                        if tag == "Q"
                        else f"H:{r['source']}:{r['number']}"
                    ),
                    "text": idx.norm[i][:160],
                    "score": fuzz.partial_ratio(q, idx.norm[i]) / 100,
                    "record": r,
                    "kind": "quran" if tag == "Q" else "hadith",
                }
            )
    out.sort(key=lambda c: -c["score"])
    return out[:k]


def _post(req: urllib.request.Request) -> dict:
    """إرسالٌ مع احترام حدود المعدّل. يرفع RuntimeError عند الفشل النهائي."""
    last = None
    for attempt in range(6):
        THROTTLE.wait()
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            last = f"{e.code}: {raw[:200]}"
            if e.code in (429, 500, 502, 503) and attempt < 5:
                wait = e.headers.get("retry-after")
                time.sleep(min(float(wait) + 1 if wait else retry_delay(raw, attempt), 70))
                continue
            raise RuntimeError(last) from None
        except (urllib.error.URLError, OSError) as e:
            last = f"شبكة: {getattr(e, 'reason', e)}"
            if attempt < 5:
                time.sleep(min(2.0**attempt, 30))
                continue
            raise RuntimeError(last) from None
    raise RuntimeError(last or "تعذّر الاتصال")


def _gen_config(schema: dict, model: str, max_tokens: int) -> dict:
    """إعدادات التوليد بحسب عائلة النموذج: بلا تفكير لعائلة flash، وبتفكير وسقف أوسع لعائلة Pro."""
    cfg = {
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseSchema": {k: v for k, v in schema.items() if k != "additionalProperties"},
        "maxOutputTokens": max_tokens,
    }
    if "pro" in model:
        cfg["maxOutputTokens"] = max(max_tokens, 4096)
    else:
        cfg["thinkingConfig"] = {"thinkingBudget": 0}
    return cfg


def _gemini_text(payload: dict) -> str:
    """نصّ الردّ النهائي — أجزاء التفكير (thought) ليست جواباً."""
    cand = (payload.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _ask_gemini(text, cands, model, key) -> tuple[str, str]:
    body = json.dumps(
        {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": (
                [
                    t
                    for q, a in _shots()
                    for t in (
                        {"role": "user", "parts": [{"text": q}]},
                        {"role": "model", "parts": [{"text": a}]},
                    )
                ]
                + [{"role": "user", "parts": [{"text": _prompt(text, cands)}]}]
            ),
            "generationConfig": _gen_config(SCHEMA, model, 256),
        }
    ).encode("utf-8")
    payload = _post(
        urllib.request.Request(
            GEMINI_ENDPOINT.format(model=model),
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key, "User-Agent": UA},
        )
    )
    answer = _gemini_text(payload)
    if not answer:
        return "", ""
    return _parse(answer)


def _ask_groq(text, cands, model, key) -> tuple[str, str]:
    """Groq متوافق مع واجهة OpenAI. المخطَّط الصارم يقوم مقام responseSchema."""
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 2048,
        "messages": (
            [{"role": "system", "content": SYSTEM}]
            + [
                m
                for q, a in _shots()
                for m in ({"role": "user", "content": q}, {"role": "assistant", "content": a})
            ]
            + [{"role": "user", "content": _prompt(text, cands)}]
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verdict", "strict": True, "schema": SCHEMA},
        },
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    body = json.dumps(body).encode("utf-8")
    payload = _post(
        urllib.request.Request(
            GROQ_ENDPOINT,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": UA,
            },
        )
    )
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    return _parse(content) if content else ("", "")


def _parse(txt: str) -> tuple[str, str]:
    got = json.loads(txt)
    return got.get("label", ""), (got.get("candidate_id") or "").strip()


def ask(
    text: str, cands: list[dict], model: str = "", key: str = "", prov: str = ""
) -> tuple[str, str]:
    """يعيد (label, candidate_id)؛ الفشل يرفع استثناءً، والتحقق من الرد موحّد بين المزودين."""
    prov = (prov or provider()).lower()
    model = model or _model(prov)
    key = key or _key(prov)
    if prov == "groq":
        return _ask_groq(text, cands, model, key)
    return _ask_gemini(text, cands, model, key)


HEAD_SYSTEM = """أنت تميّز عناوين الأقسام في نصٍّ عربي مُقطَّع.

العنوان: سطرٌ قصير يُسمّي ما بعده («دعاء الركوع»، «فضل الذكر»)، لا جملة خبرية
ولا دعاء ولا اسم مؤلف ولا تاريخ ولا بيانات نشر.

تُعطى مقاطع مرقَّمة. أعد أرقام العناوين فقط. وإن لم يكن فيها عنوان فأعد قائمة فارغة."""

HEAD_SCHEMA = {
    "type": "object",
    "properties": {"headings": {"type": "array", "items": {"type": "integer"}}},
    "required": ["headings"],
    "additionalProperties": False,
}
HEAD_MAX_WORDS = 10


def heading_candidates(segments) -> list[int]:
    """المقاطع التي تُعرض على النموذج عناوين محتملة: القصيرة من مصدر بلا أنماط."""
    return [
        i
        for i, s in enumerate(segments)
        if s.kind in ("text", "term", "title") and len(s.content.split()) <= HEAD_MAX_WORDS
    ]


def _headings_via_groq(listing: str) -> str | None:
    body = {
        "model": _model("groq"),
        "temperature": 0,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": HEAD_SYSTEM},
            {"role": "user", "content": listing},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "headings", "strict": True, "schema": HEAD_SCHEMA},
        },
    }
    payload = _post(
        urllib.request.Request(
            GROQ_ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": UA,
                "Authorization": f"Bearer {_key('groq')}",
            },
        )
    )
    return ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")


def _headings_via_gemini(listing: str) -> str | None:
    """السؤال نفسه عن العناوين عبر Gemini."""
    model = _model("gemini")
    body = json.dumps(
        {
            "systemInstruction": {"parts": [{"text": HEAD_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": listing}]}],
            "generationConfig": _gen_config(HEAD_SCHEMA, model, 512),
        }
    ).encode("utf-8")
    payload = _post(
        urllib.request.Request(
            GEMINI_ENDPOINT.format(model=model),
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": _key("gemini"),
                "User-Agent": UA,
            },
        )
    )
    return _gemini_text(payload) or None


def ask_headings(segments, idx: list[int]) -> set[int]:
    """يرجع أرقام ما رآه النموذج عنواناً. أي رقم خارج المعروض يُرفض."""
    if not idx:
        return set()
    listing = "\n".join(f"{n}. {segments[i].content[:120]}" for n, i in enumerate(idx, 1))
    via = _headings_via_groq if provider() == "groq" else _headings_via_gemini
    content = via(listing)
    if not content:
        return set()
    out = set()
    for n in json.loads(content).get("headings", []):
        if isinstance(n, int) and 1 <= n <= len(idx):
            out.add(idx[n - 1])
    return out


def mark_headings(segments, paragraphs) -> int:
    """المرحلة الأخيرة لتمييز العناوين في مصدرٍ بلا أنماط. يرجع عددها."""
    if os.environ.get("LLM_HEADINGS") != "1" or not _key(provider()):
        return 0
    if any(p.styled for p in paragraphs):
        return 0
    idx = heading_candidates(segments)
    try:
        found = ask_headings(segments, idx)
    except Exception:
        return 0
    for i in found:
        segments[i].kind = "title"
        segments[i].level = 2
        segments[i].terms = []
        segments[i].note = "عنوان — رجّحه النموذج من السياق"
        segments[i].reviewed = True
    return len(found)


def needs_review(seg, is_heading: bool = False) -> bool:
    """يستثني من المراجعة الحقائق البنيوية (عنوان من نمط Word) والمطابقات المحسومة وحدها."""
    from .classifier import ACCEPT

    if is_heading:
        return False
    return seg.score is None or seg.score < ACCEPT


def apply_verdict(seg, label: str, cid: str, cands: list[dict]) -> bool:
    """تطبيق حكم النموذج بعد التحقق. يرجع True إن تغيّر المقطع."""
    if label not in LABELS:
        return False
    by_id = {str(n): c for n, c in enumerate(cands, 1)}
    if cid and cid not in by_id:
        return False

    if label == "نص":
        if seg.kind in ("quran", "hadith"):
            seg.kind, seg.source, seg.score = "text", "", None
            seg.note = "النموذج رآه كلامَ المؤلف لا نصَّ وحي"
            return True
        return False

    if label == "آية":
        c = by_id.get(cid)
        if not c or c["kind"] != "quran" or seg.kind == "quran":
            return False
        r = c["record"]
        seg.kind, seg.score = "quran", c["score"]
        seg.source = f"سورة {r['surah']} — {r['ayah']}"
        seg.note = "رجّحه النموذج من مرشَّحي الفهرس"
        return True

    if label == "حديث" and seg.kind != "hadith":
        c = by_id.get(cid)
        seg.kind = "hadith"
        if c and c["kind"] == "hadith":
            r = c["record"]
            seg.source, seg.score = f"{r['source']} — {r['number']}", c["score"]
        else:
            seg.source, seg.score = "", None
            seg.note = "وسمه النموذج حديثاً — بلا تخريج، يحتاج مراجعة"
        return True
    return False


def review(segments, is_heading_by_index=None, on_progress=None) -> dict:
    """يراجع المقاطع موضعياً ويعيد إحصاءً؛ لا يُسأل النموذج إلا عمّا له مرشّح معقول من الفهرس."""
    stats = {"asked": 0, "changed": 0, "fabricated": 0, "failed": 0, "skipped": 0}
    if not enabled():
        stats["skipped"] = len(segments)
        return stats
    floor = float(os.environ.get("LLM_MIN_CAND", "0.72"))
    pending = []
    for i, seg in enumerate(segments):
        if not needs_review(seg, (is_heading_by_index or {}).get(i, False)):
            continue
        if getattr(seg, "reviewed", False):
            continue
        cands = candidates_for(seg.content)
        if not any(c["score"] >= floor for c in cands):
            continue
        pending.append((seg, cands))
    stats["skipped"] = len(segments) - len(pending)
    for done, (seg, cands) in enumerate(pending, 1):
        if on_progress:
            on_progress(done, len(pending))
        try:
            label, cid = ask(seg.content, cands)
        except Exception:
            stats["failed"] += 1
            continue
        stats["asked"] += 1
        if label in LABELS and cid and cid not in {str(n) for n in range(1, len(cands) + 1)}:
            stats["fabricated"] += 1
            continue
        if apply_verdict(seg, label, cid, cands):
            seg.reviewed = True
            stats["changed"] += 1
    return stats
