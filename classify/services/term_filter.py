"""فلترة المصطلحات بالسياق: Gemini يحكم أيّ مرشَّحي المعجم مقصودٌ في الجملة، والمعجم وحده المصدر.

المطابق الحتمي يجد المصطلح من صورة الكلمة («رحمكم» ← «رحم»)، فيُعرض كل مقطع مع مرشَّحيه
وتعريفاتهم على النموذج، فيعيد أرقام ما يقصده السياق فقط. لا يضيف مصطلحاً ولا يغيّر مقابلاً،
وأي فشل يُبقي نتيجة المطابق كما هي.
"""

import json
import os
import urllib.request

from . import reviewer

SYSTEM = """أنت مدقّقُ مصطلحات في نصوص إسلامية عربية. مهمتك حكمٌ لا إنشاء.

تُعطى مقاطع مرقَّمة، وتحت كل مقطع مصطلحاتٌ مرشَّحة من معجمنا، لكلٍّ منها رقمٌ بالصيغة
«رقم المقطع.رقم المصطلح» والكلمة كما وردت في المقطع، ثم المصطلح ومقابله الإنجليزي وتعريفه.

استبعد المصطلح فقط إن كانت الكلمة في المقطع كلمةً أخرى أو معنىً آخر لا صلة له بالمصطلح،
وافقته في الصورة وحدها، مثل:
- «واعلموا رحمكم الله»: دعاءٌ بالرحمة، لا «رحم» بمعنى القرابة.
- «وجلس على عين الماء»: منبع الماء، لا «عين» بمعناها الاصطلاحي.
- «كل عام»: السنة، لا «العام» مقابل الخاص.

وأبقه إن استُعملت الكلمة في معنى المصطلح العام كما يدل عليه مقابله، ولو كان التعريف
المذكور اصطلاحاً فقهياً أضيق؛ فـ«أجر الصابرين» (reward) و«الرضا بالقضاء» (contentment)
مصطلحان مقصودان وإن عُرِّف «الأجر» في المعجم بعوض الإجارة و«الرضا» بقبول العقد.

ضوابط قاطعة:
- أعد أرقاماً من المعروض فقط، بالصيغة نفسها (مثل "3.1"). لا نصّ ولا شرح.
- لا تضف مصطلحاً غير معروض ولا تقترح مقابلاً.
- إن شككت في مصطلح فأبقه.
"""

SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "string"}}},
    "required": ["keep"],
    "additionalProperties": False,
}

BATCH = 40
NOTE_CHARS = 140


def enabled() -> bool:
    return os.environ.get("LLM_TERMS") == "1" and bool(reviewer._key("gemini"))


def _listing(batch) -> str:
    blocks = []
    for n, seg in enumerate(batch, 1):
        lines = [f"{n}. {seg.content}"]
        for k, term in enumerate(seg.terms, 1):
            surface = term.get("surface") or term["arabic"]
            english = f" ({term['english']})" if term.get("english") else ""
            note = (term.get("note") or "").strip()[:NOTE_CHARS]
            lines.append(f"   {n}.{k} «{surface}» ← {term['arabic']}{english}: {note}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _ask(listing: str) -> str:
    """نص الرد (JSON) من Gemini؛ الفشل يرفع استثناءً."""
    model = reviewer._model("gemini")
    body = json.dumps(
        {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": listing}]}],
            "generationConfig": reviewer._gen_config(SCHEMA, model, 1024),
        }
    ).encode("utf-8")
    payload = reviewer._post(
        urllib.request.Request(
            reviewer.GEMINI_ENDPOINT.format(model=model),
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": reviewer._key("gemini"),
                "User-Agent": reviewer.UA,
            },
        )
    )
    return reviewer._gemini_text(payload)


def _apply(batch, keep: set[str], stats: dict) -> None:
    for n, seg in enumerate(batch, 1):
        kept = [t for k, t in enumerate(seg.terms, 1) if f"{n}.{k}" in keep]
        stats["dropped"] += len(seg.terms) - len(kept)
        seg.terms = kept
        if seg.kind == "term":
            if kept:
                seg.note = f"مصطلح: {kept[0]['arabic']}"
            else:
                seg.kind, seg.note = "text", ""


def filter_terms(segments) -> dict:
    """يُبقي من مصطلحات كل مقطع ما يقصده سياقه؛ يعدّل المقاطع موضعياً ويعيد إحصاءً."""
    stats = {"asked": 0, "dropped": 0, "failed": 0}
    if not enabled():
        return stats
    pending = [s for s in segments if s.terms]
    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        try:
            answer = _ask(_listing(batch))
            keep = {str(x).strip() for x in json.loads(answer).get("keep", [])}
        except Exception:
            stats["failed"] += len(batch)
            continue
        stats["asked"] += len(batch)
        _apply(batch, keep, stats)
    return stats
