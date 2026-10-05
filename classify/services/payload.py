"""المخرَج الأساسي للتطبيق: وثيقة وعباراتها بصيغة الواجهة البرمجية بكامل السمات."""

import hashlib
from collections import Counter
from datetime import UTC, datetime

from .exporter import CONTENT_TYPE_ID, build_rows, reason_code
from .taxonomy import (
    CONTENT_TYPE_NAME,
    CONTENT_TYPE_NAME_AR,
    KIND_OF_INTERNAL,
    TERM_CATEGORY_OF_DICT,
    UNTRANSLATABLE,
    ContentTypeId,
    SegmentKind,
    enum_block,
)

API_VERSION = "2.0"

KIND = {k: v.value for k, v in KIND_OF_INTERNAL.items()}

REVIEW_BELOW = 0.3


def phrase_id(title: str, group: int, order: int, text: str) -> str:
    """معرّف مشتق من الموضع والمحتوى بصورة UUID، ثابت عبر التشغيلات ويتغير بتغير النص أو الموضع."""
    h = hashlib.sha1(f"{title}|{group}:{order}|{text}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def build_payload(title: str, segments, source: dict | None = None) -> dict:
    rows = build_rows(segments)
    out = []
    for s, r in zip(segments, rows, strict=False):
        kind = KIND_OF_INTERNAL.get(s.kind, SegmentKind.PLAIN)
        ctype = CONTENT_TYPE_ID.get(s.kind, ContentTypeId.TEXT)
        analysis = {
            "kind": kind.value,
            "confidence": float(r["الثقة"]),
            "reason": r["سبب الثقة"],
            "reason_code": reason_code(s).value,
            "source": r["المصدر"] or None,
            "terms": [
                {
                    "ar": t.get("arabic"),
                    "en": t.get("english") or None,
                    "surface": t.get("surface"),
                    "category": TERM_CATEGORY_OF_DICT.get(
                        t.get("kind", "terms"), TERM_CATEGORY_OF_DICT["terms"]
                    ).value,
                }
                for t in (s.terms or [])
            ]
            or None,
        }
        item = {
            "phrase_id": phrase_id(title, r["رقم الفقرة"], r["الترتيب بالفقرة"], r["المحتوى"]),
            "seq": r["التسلسل"],
            "group_id": r["رقم الفقرة"],
            "group_order": r["الترتيب بالفقرة"],
            "arabic_text": r["المحتوى"],
            "content_type_id": int(ctype),
            "content_type_name": CONTENT_TYPE_NAME[ctype].value,
            "content_type_name_ar": CONTENT_TYPE_NAME_AR[ctype],
            "tag": r["التوسيم"],
            "text_type": r["نوع النص"],
            "align": r["محاذاة النص"],
            "direction": r["اتجاه النص"],
            "translatable": kind not in UNTRANSLATABLE,
            "footnote_id": None,
            "analysis": {k: v for k, v in analysis.items() if v is not None},
        }
        out.append({k: v for k, v in item.items() if v is not None})

    return {
        "api_version": API_VERSION,
        "enums": enum_block(),
        "document": {
            "title": title,
            "source": source or {"kind": "unknown"},
            "processed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "paragraphs": len({x["group_id"] for x in out}),
            "phrases": len(out),
            "by_content_type": dict(Counter(x["content_type_name"] for x in out)),
            "by_kind": dict(Counter(x["analysis"]["kind"] for x in out)),
            "needs_review": sum(1 for x in out if x["analysis"]["confidence"] < REVIEW_BELOW),
        },
        "phrases": out,
    }
