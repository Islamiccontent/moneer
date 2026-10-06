"""تحليل رد النموذج والتحقق منه وتطبيعه إلى ملاحظات مصنَّفة.

الرد المتوقع: مصفوفة JSON فيها عنصر لكل id بالشكل الموثق في prompt.py.
الفئة واسم النوع لا تُقرأ من النموذج بل تُستنتج من الرمز (taxonomy)."""

import json
import re

from .taxonomy import (
    OTHER_CODE,
    OTHER_TYPE,
    category_name,
    get_type,
    normalize_detection,
    normalize_severity,
)

MAX_ERRORS_PER_ITEM = 6


def parse_json_array(text):
    """يستخرج مصفوفة JSON من نص قد يحوي أسوار ``` أو نصًا زائدًا."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("items", "results", "data"):
                if isinstance(value.get(key), list):
                    return value[key]
    except Exception:
        pass

    depth, start = 0, None
    for index, char in enumerate(text):
        if char == "[":
            if depth == 0:
                start = index
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    value = json.loads(text[start : index + 1])
                    if isinstance(value, list):
                        return value
                except Exception:
                    start = None
    raise ValueError("لا توجد مصفوفة JSON صالحة في الرد.")


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "نعم", "صحيح"}


def _to_confidence(value, fallback=70):
    try:
        number = float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return fallback
    if 0 < number <= 1:
        number *= 100
    return int(max(0, min(100, round(number))))


def normalize_finding(raw, source="model"):
    """يحوّل ملاحظة خام (من النموذج أو من قاعدة) إلى صف موحَّد للقاعدة والتصدير."""
    raw_code = str(raw.get("code") or "").strip()
    etype = get_type(raw_code)
    unknown = etype is OTHER_TYPE
    type_code = OTHER_CODE if unknown else etype.code
    type_name = etype.name if not unknown or not raw_code else f"{etype.name} ({raw_code})"

    severity = normalize_severity(raw.get("severity"), etype.default_severity)
    sharia = _to_bool(raw.get("sharia_sensitive")) or etype.sharia_default
    detection = normalize_detection(raw.get("detection"), etype.detection_default)
    confidence = _to_confidence(raw.get("confidence"), 100 if source == "rule" else 70)
    needs_review = severity == "حرج" or sharia

    return {
        "source": source,
        "category_code": etype.category or "",
        "category": category_name(etype.category) if etype.category else "غير مصنَّف",
        "type_code": type_code,
        "type_name": type_name,
        "severity": severity,
        "sharia_sensitive": bool(sharia),
        "detection": detection,
        "confidence": confidence,
        "location": str(raw.get("location") or "").strip(),
        "explanation": str(raw.get("explanation") or "").strip(),
        "required_action": str(raw.get("required_action") or "").strip() or etype.required_action,
        "suggested_fix": str(raw.get("suggested_fix") or "").strip(),
        "needs_human_review": bool(needs_review),
    }


def validate_group_result(text, expected_ids):
    """يحلّل رد مجموعة ويعيد {id: {"summary": str, "errors": [ملاحظات موحَّدة]}}.

    يرفع ValueError إن غاب أي id متوقَّع (فتُعاد المجموعة كلها لاحقًا)."""
    values = parse_json_array(text)
    result = {}
    for value in values:
        if not isinstance(value, dict) or "id" not in value:
            continue
        try:
            row_id = int(value["id"])
        except (TypeError, ValueError):
            continue
        raw_errors = value.get("errors")
        if raw_errors is None:
            raw_errors = value.get("findings") or []
        if not isinstance(raw_errors, list):
            raw_errors = []
        errors, seen = [], set()
        for raw in raw_errors:
            if not isinstance(raw, dict):
                continue
            finding = normalize_finding(raw, source="model")
            key = (finding["type_code"], finding["location"][:40])
            if key in seen:
                continue
            seen.add(key)
            errors.append(finding)
            if len(errors) >= MAX_ERRORS_PER_ITEM:
                break
        result[row_id] = {"summary": str(value.get("summary") or "").strip(), "errors": errors}

    missing = set(expected_ids) - set(result)
    if missing:
        raise ValueError(
            f"رد ناقص: متوقَّع {len(expected_ids)} نتيجة، والمفقود {len(missing)} "
            f"(مثل id={sorted(missing)[:5]})."
        )
    return result
