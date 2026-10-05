"""طبقة BERT: تقترح آيات وأحاديث داخل ما صُنّف نصاً، ولا يُقبل اقتراح إلا بمطابقة المصحف."""

from __future__ import annotations

import dataclasses
import os
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BERT_DIR = ROOT / "Bert test"

FROZEN_KINDS = frozenset({"title", "quran", "hadith", "citation"})
UPGRADABLE_KINDS = frozenset({"text", "term", "attribution"})
PROPOSABLE = ("aya", "hadith", "athar")

_LOCK = threading.Lock()
_STATE: dict = {}


def bert_dir() -> Path:
    return Path(os.environ.get("BERT_DIR", str(DEFAULT_BERT_DIR)))


def model_dir() -> Path:
    return bert_dir() / "dist" / "segmenter-v1"


def enabled() -> bool:
    return os.environ.get("BERT_LAYER") == "1" and (model_dir() / "train_config.json").exists()


def _load() -> dict:
    """تحميلٌ كسولٌ مرّةً واحدة. يُرفع الاستثناءُ ليُمسكه `enrich` ويعدَّه فشلاً."""
    with _LOCK:
        if "model" in _STATE:
            return _STATE
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        bd = str(bert_dir())
        if bd not in sys.path:
            sys.path.insert(0, bd)
        from moneer_bert.infer import load_token_model

        from .matchers import HadithMatcher, QuranMatcher

        _STATE["model"] = load_token_model(str(model_dir()), "cpu")
        _STATE["quran"] = QuranMatcher()
        _STATE["hadith"] = HadithMatcher() if os.environ.get("HADITH_MATCH") == "1" else None
        return _STATE


def reset() -> None:
    """للاختبارات: إسقاطُ ما حُمِّل."""
    with _LOCK:
        _STATE.clear()


def _tag_words(segments, st) -> list[tuple[list[str], list[str]]]:
    """يعيد لكل مقطع (كلماته، وسوم BIO لكل كلمة) بتمرير المستند كله تياراً واحداً على النموذج."""
    from moneer_bert.infer import segment as bert_segment
    from moneer_bert.normalization import word_tokenize

    model, tok, cfg = st["model"]
    per_seg = [word_tokenize(s.content) for s in segments]
    words = [w for ws in per_seg for w in ws]
    if not words:
        return [(ws, []) for ws in per_seg]
    tags, _confs, _cuts = bert_segment(words, model, tok, cfg, "cpu")
    out, pos = [], 0
    for ws in per_seg:
        n = len(ws)
        out.append((ws, tags[pos : pos + n]))
        pos += n
    return out


def _spans(tags: list[str]) -> list[tuple[int, int, str]]:
    """مدياتٌ متّصلةٌ غيرُ «نص» من وسومِ BIO → [(بداية، نهايةٌ حصريّة، نوع)]."""
    spans, start, cur = [], None, None
    for i, t in enumerate(tags):
        typ = t[2:] if len(t) > 2 else "text"
        begins = t.startswith("B-")
        if typ in PROPOSABLE and not begins and typ == cur:
            continue
        if cur is not None:
            spans.append((start, i, cur))
            start, cur = None, None
        if typ in PROPOSABLE:
            start, cur = i, typ
    if cur is not None:
        spans.append((start, len(tags), cur))
    return spans


def _note_variant(v: dict) -> str:
    d = v.get("diff") or {}
    extra = "، ".join(d.get("extra") or [])
    missing = "، ".join(d.get("missing") or [])
    parts = ["⚠ يخالف رسم المصحف"]
    if extra:
        parts.append(f"زائد: {extra}")
    if missing:
        parts.append(f"ناقص: {missing}")
    return " — ".join(parts)


_SEAT_LETTERS = frozenset("اويء")


def _cosmetic_pair(a: str, b: str) -> bool:
    """هل تستوي الكلمتان لولا حرفُ مقعدِ همزةٍ واحد؟"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    da, db = a[i : len(a) - j], b[i : len(b) - j]
    if len(da) > 1 or len(db) > 1:
        return False
    if da and db:
        return da in _SEAT_LETTERS and db in _SEAT_LETTERS
    ch = da or db
    if ch == "ء":
        return True
    if ch in "وي":
        longer = a if da else b
        return "ا" in longer[max(0, i - 1) : i] + longer[i + 1 : i + 2]
    return False


def _canon_words(v: dict, st) -> list[str]:
    """كلمات المصحف المرجعية مجردة من فهرس ICADB أو نص المحقق، لفحص نظير الزائد المنفرد."""
    from moneer_bert.quran_verify import parse_ref, skeleton

    text = v.get("canonical") or v.get("canonical_text") or ""
    if not text and st is not None:
        ref = parse_ref(v.get("quran_ref") or "")
        if ref:
            surah_no, ayah = ref
            text = " ".join(
                r["text"]
                for r in st["quran"].index.records
                if int(r["surah_no"]) == surah_no and ayah - 2 <= int(r["ayah"]) <= ayah + 3
            )
    return skeleton(text, True)


def _real_diff(v: dict, quoted: str, st=None) -> dict:
    """فرق المخالفة بعد إسقاط خلاف صور الهمزة؛ خلوّه يعني مطابقة فعلية."""
    from moneer_bert.quran_verify import skeleton

    d = v.get("diff") or {}
    extra, missing = list(d.get("extra") or []), list(d.get("missing") or [])
    if not (extra or missing):
        return d
    canon = (d.get("window") or "").split() + _canon_words(v, st)
    rem_missing = list(missing)
    real_extra = []
    for t in extra:
        mate = next((x for x in rem_missing if _cosmetic_pair(t, x)), None)
        if mate is not None:
            rem_missing.remove(mate)
            continue
        if any(_cosmetic_pair(t, w) for w in canon):
            continue
        real_extra.append(t)
    quoted_words = skeleton(quoted, True)
    real_missing = [t for t in rem_missing if not any(_cosmetic_pair(t, w) for w in quoted_words)]
    return {"extra": real_extra, "missing": real_missing, "window": d.get("window", "")}


def _confirm(text: str, proposed: str, st) -> dict | None:
    """يسأل المطابِقَ والمصحفَ عن مدًى اقترحه النموذج. None = لم يتأكّد."""
    from moneer_bert.hybrid import verify_segment

    v = verify_segment({"text": text, "content_type": proposed}, st["quran"], st["hadith"])
    kind = v["content_type"]
    if kind == "aya" and v.get("quran_ref"):
        return {
            "kind": "quran",
            "source": v["quran_ref"],
            "score": v.get("match_score"),
            "note": "اقترحه النموذج وطابق المصحفَ نصّاً",
            "stat": "upgraded_quran",
        }
    if kind == "aya_variant" and v.get("quran_ref"):
        real = _real_diff(v, text, st)
        if not (real["extra"] or real["missing"]):
            return {
                "kind": "quran",
                "source": v["quran_ref"],
                "score": v.get("match_score"),
                "note": "اقترحه النموذج وطابق المصحفَ نصّاً",
                "stat": "upgraded_quran",
            }
        return {
            "kind": "quran",
            "source": v["quran_ref"],
            "score": v.get("match_score"),
            "note": _note_variant({"diff": real}),
            "stat": "variant_flagged",
        }
    if kind == "hadith" and v.get("hadith_ref"):
        return {
            "kind": "hadith",
            "source": v["hadith_ref"],
            "score": v.get("match_score"),
            "note": "اقترحه النموذج وأكّده فهرسُ الحديث",
            "stat": "upgraded_hadith",
        }
    return None


def _upgrade_text(seg, words: list[str], tags: list[str], st, stats: dict) -> list:
    """مقطعٌ «نص» وفيه مدياتٌ اقترحها النموذج. يُرجع ما يحلّ محلَّه (مقطعاً أو أكثر)."""
    if "﴿" in seg.content:
        br = _bracket_split(seg, st, stats)
        if br:
            stats["upgraded_quran"] += 1
            return br
    spans = _spans(tags)
    if not spans:
        stats["skipped"] += 1
        return [seg]
    stats["proposed"] += 1

    confirmed = []
    for s, e, typ in spans:
        c = _confirm(" ".join(words[s:e]), typ, st)
        if c:
            confirmed.append((s, e, c))
    if not confirmed:
        stats["rejected"] += 1
        return [seg]

    if len(confirmed) == 1 and confirmed[0][0] == 0 and confirmed[0][1] >= len(words):
        c = confirmed[0][2]
        seg.kind, seg.source, seg.score, seg.note = c["kind"], c["source"], c["score"], c["note"]
        seg.reviewed = True
        stats[c["stat"]] += 1
        return [seg]

    out, pos = [], 0
    for s, e, c in confirmed:
        if s > pos:
            out.append(
                dataclasses.replace(
                    seg,
                    content=" ".join(words[pos:s]),
                    source="",
                    score=None,
                    note="",
                    reviewed=False,
                )
            )
        out.append(
            dataclasses.replace(
                seg,
                kind=c["kind"],
                content=" ".join(words[s:e]),
                source=c["source"],
                score=c["score"],
                note=c["note"],
                reviewed=True,
            )
        )
        stats[c["stat"]] += 1
        pos = e
    if pos < len(words):
        tail_kind = "text" if seg.kind == "attribution" else seg.kind
        out.append(
            dataclasses.replace(
                seg,
                kind=tail_kind,
                content=" ".join(words[pos:]),
                source="",
                score=None,
                note="",
                reviewed=False,
            )
        )
    stats["split"] += 1
    return out


_BRACKETED = re.compile(r"﴿[^﴾]+﴾")


def _fix_ayah(source: str, m, start: int) -> str:
    """«سورة النور — 37» ← «سورة النور — 36» إذا طابق النصُّ آيةً غيرَ المُحالِ إليها."""
    if not start or start == m.extra.get("ayah"):
        return source
    head = source.rsplit("—", 1)[0].rstrip() if "—" in source else source
    return f"{head} — {start}"


def _recent_refs(out: list, st, window: int = 8, keep: int = 3) -> list:
    """آخرُ الآياتِ المقتبَسةِ قريباً: [(سورة، آية، المصدرُ كما كُتب)]، الأحدثُ أوّلاً."""
    from moneer_bert.quran_verify import parse_ref

    refs = []
    for s in reversed(out[-window:]):
        if s.kind == "quran" and s.source:
            r = parse_ref(s.source)
            if r and (r[0], r[1], s.source) not in refs:
                refs.append((r[0], r[1], s.source))
            if len(refs) >= keep:
                break
    return refs


def _side_part(seg, content: str):
    """يصنّف ما يُفصل حول الآية المقوّسة: إسناداً بقاعدة المصنّف إن كان صيغة إسناد، وإلا نصاً."""
    from .classifier import ATTRIBUTION
    from .normalizer import light

    if ATTRIBUTION.search(light(content)):
        kind, note = "attribution", "صيغة الإسناد"
    else:
        kind, note = "text", ""
    return dataclasses.replace(
        seg, kind=kind, content=content, source="", score=None, note=note, reviewed=False
    )


def _bracket_split(seg, st, stats: dict) -> list | None:
    """يقابل ما بين ﴿﴾ بالمصحف بمدى ممتد على آيات؛ يعيد القائمة البديلة أو None إن لم يطابق."""
    from moneer_bert.quran_verify import verify_against_mushaf

    brackets = _BRACKETED.findall(seg.content)
    if len(brackets) != 1:
        return None
    inner = brackets[0]
    m = st["quran"].match(inner, short=True)
    if m is None:
        return None
    v = verify_against_mushaf(inner, m.extra.get("surah_no", 0), m.extra.get("ayah", 0))
    if v["status"] != "exact":
        return None
    i = seg.content.index(inner)
    before, after = seg.content[:i].strip(), seg.content[i + len(inner) :].strip().lstrip("،, ")
    source = _fix_ayah(m.source, m, v.get("start_ayah"))
    spanned = v.get("ayahs_spanned", 1)
    note = "القوسان حدُّ الآية؛ طابقت المصحف" + (f" ({spanned} آيات متتالية)" if spanned > 1 else "")
    out = []
    if before:
        out.append(_side_part(seg, before))
    out.append(
        dataclasses.replace(
            seg,
            kind="quran",
            content=inner,
            source=source,
            score=1.0 if spanned > 1 else m.score,
            note=note,
            reviewed=True,
        )
    )
    if after:
        out.append(_side_part(seg, after))
    stats["verified_quran"] += 1
    if before or after:
        stats["split"] += 1
    return out


def _verify_quran(seg, st, stats: dict, recent: list = ()) -> list:
    """يفحص نص الآية بالمصحف دون رفع وسمها، ويفصل كلام المؤلف حول القوسين إن طابق ما بينهما."""
    from moneer_bert.quran_verify import verify_against_mushaf

    outside = _BRACKETED.sub(" ", seg.content).split()
    if len(outside) >= 2:
        br = _bracket_split(seg, st, stats)
        if br:
            return br

    m = st["quran"].match(seg.content, short=True)
    if m is None:
        stats["skipped"] += 1
        return [seg]
    for r_surah, r_ayah, r_source in recent:
        if (r_surah, r_ayah) == (m.extra.get("surah_no"), m.extra.get("ayah")):
            break
        rv = verify_against_mushaf(seg.content, r_surah, r_ayah, back=0)
        if rv["status"] == "exact" and rv.get("start_ayah") == r_ayah:
            seg.source = r_source
            seg.note = (f"{seg.note} | " if seg.note else "") + "رُجّحت الآيةُ بسياقِ الاقتباسِ السابق"
            seg.reviewed = True
            stats["verified_quran"] += 1
            return [seg]
    v = verify_against_mushaf(seg.content, m.extra.get("surah_no", 0), m.extra.get("ayah", 0))
    if v["status"] == "variant":
        real = _real_diff(v, seg.content, st)
        if real["extra"] or real["missing"]:
            tag = _note_variant({"diff": real})
            seg.note = f"{seg.note} | {tag}" if seg.note else tag
            seg.reviewed = True
            stats["variant_flagged"] += 1
        else:
            seg.reviewed = True
            stats["verified_quran"] += 1
    elif v["status"] == "exact":
        fixed = _fix_ayah(seg.source or m.source, m, v.get("start_ayah"))
        if fixed != seg.source:
            seg.note = (
                f"{seg.note} | " if seg.note else ""
            ) + f"صُحّح رقمُ الآية من المصحف ({seg.source} ← {fixed})"
            seg.source = fixed
            seg.reviewed = True
        stats["verified_quran"] += 1
    else:
        stats["skipped"] += 1
    return [seg]


def enrich(segments) -> dict:
    """المرحلة المعزِّزة: تعدّل القائمة موضعياً وقد تقطع مقطعاً، وتعيد إحصاءً ولا ترفع استثناءً."""
    stats = {
        "proposed": 0,
        "upgraded_quran": 0,
        "upgraded_hadith": 0,
        "variant_flagged": 0,
        "verified_quran": 0,
        "split": 0,
        "rejected": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not enabled():
        stats["skipped"] = len(segments)
        return stats
    try:
        st = _load()
        tagged = _tag_words(segments, st)
    except Exception:
        stats["failed"] = len(segments)
        return stats

    out, recent = [], []
    for seg, (words, tags) in zip(segments, tagged, strict=False):
        try:
            if seg.kind == "quran":
                out.extend(_verify_quran(seg, st, stats, recent))
                recent = _recent_refs(out, st)
            elif seg.kind in UPGRADABLE_KINDS and tags:
                out.extend(_upgrade_text(seg, words, tags, st, stats))
            else:
                stats["skipped"] += 1
                out.append(seg)
        except Exception:
            stats["failed"] += 1
            out.append(seg)
    segments[:] = out
    return stats
