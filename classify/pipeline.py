"""ربط محرك التقطيع والتصنيف بجداول content: التشغيل والحفظ وإعادة بناء المقاطع للتصدير."""

import os
import re
from dataclasses import dataclass, field

from django.db import transaction

from classify.services import bert_layer, reviewer, speaker
from classify.services.classifier import classify_paragraphs
from classify.services.matchers import get_matchers
from classify.services.payload import build_payload
from classify.services.taxonomy import KIND_OF_INTERNAL, TERM_CATEGORY_OF_DICT
from content.models import Document, Glossary, Phrase, PhraseAnalysis, PhraseTerm


class DuplicateTitleError(Exception):
    """يوجد مستند بالعنوان نفسه ولم يُطلب الاستبدال."""


TRAILING_LEADIN = re.compile(
    r"(?:^|(?<=[.!؟»)\]]))\s*"
    r"(?P<lead>(?:\S+\s+){0,3}?(?:و|ف)?(?:قال|يقول|قوله|بقوله|لقوله|كقوله)\s+"
    r"(?:اللهُ?\s+|النبيُّ?\s+|رسولُ?\s+اللهِ?\s+)?"
    r"(?:تعالى|تعالي|سبحانه|عز\s+وجل|ﷺ|صلى\s+الله\s+عليه\s+وسلم)?\s*[:：])\s*$"
)


def split_trailing_leadins(segments) -> list:
    """يفصل صيغة تقديمٍ ختمت وحدةَ نثر («… قال الله تعالى:») وحدةَ إسنادٍ مستقلة."""
    from classify.services.classifier import Segment

    out = []
    for seg in segments:
        if seg.kind not in ("text", "term"):
            out.append(seg)
            continue
        m = TRAILING_LEADIN.search(seg.content)
        if not m:
            out.append(seg)
            continue
        lead = m.group("lead").strip()
        head = seg.content[: m.start()].strip()
        if head:
            seg.content = head
            out.append(seg)
            out.append(Segment("attribution", lead, note="صيغة الإسناد", para=seg.para))
        else:
            seg.kind, seg.content, seg.terms, seg.note = "attribution", lead, [], "صيغة الإسناد"
            out.append(seg)
    return out


QURAN_LEADIN = re.compile(
    r"^(?P<lead>(?:\S+\s+){0,4}?(?:و|ف)?(?:قوله|قولِه|بقوله|لقوله|كقوله|قال|يقول)\s+"
    r"(?:اللهُ?\s+)?(?:تعالى|تعالي|سبحانه|عز\s+وجل)\s*[:：])\s*(?P<rest>.+)$",
    re.S,
)
QURAN_CITATION = re.compile(
    r"^(?P<aya>.+?)\s*(?P<cite>[\[(]\s*(?P<surah>[^\][()\d:]{1,25}?)\s*[:：]\s*\d{1,3}\s*[\])]"
    r"\s*[.؟!]?)\s*$",
    re.S,
)
QURAN_QUOTE = re.compile(r"﴿[^﴾]{3,}﴾|\{[^{}]{3,}\}")
_ARABIC_LETTER = re.compile(r"[ء-ي]")


def peel_quran_units(segments) -> list:
    """يفصل التقديم والإحالة الملتصقين بوحدة الآية قبل مرحلة BERT ويعيد مطابقة نص الآية الصافي."""
    from classify.services.classifier import Segment

    quran = get_matchers()[0]
    out = []
    for seg in segments:
        if seg.kind != "quran":
            out.append(seg)
            continue
        content, prefer = seg.content.strip(), ""
        lead = cite = pre = None
        m = QURAN_LEADIN.match(content)
        if m:
            lead, content = m.group("lead"), m.group("rest").strip()
        m = QURAN_QUOTE.search(content)
        if m and _ARABIC_LETTER.search(content[: m.start()]):
            pre, content = content[: m.start()].strip(), content[m.start() :].strip()
        m = QURAN_CITATION.match(content)
        if m:
            content, cite, prefer = (
                m.group("aya").strip(),
                m.group("cite"),
                m.group("surah").strip(),
            )
        if lead is None and cite is None and pre is None:
            out.append(seg)
            continue
        if lead:
            out.append(
                Segment("attribution", lead, note="صيغة الإسناد", para=seg.para, level=seg.level)
            )
        if pre:
            out.append(Segment("text", pre, para=seg.para, level=seg.level))
        seg.content = content
        match = quran.match(content, prefer=prefer)
        if match:
            seg.source, seg.score, seg.note = match.source, match.score, ""
        out.append(seg)
        if cite:
            out.append(Segment("citation", cite, note="إحالة مصدر", para=seg.para))
    return out


HADITH_LEADIN = re.compile(r"^(?P<lead>[^:：]{3,160}?[:：])\s*(?P<rest>\S.*)$", re.S)
LEADIN_MAX_WORDS = 14


def peel_hadith_leadins(segments) -> list:
    """يفصل صيغة التقديم («وقال النبي ﷺ:») عن حديثٍ التصق بها بلا علامات تنصيص.

    ما بعد النقطتين يُقطَّع جملاً ويُصنَّف كلٌّ منها بسياق التقديم، ولا يُقبل التفصيل إلا إذا
    أظهر حديثاً أو آية بالفهرس؛ والحديث الذي طوبق مع تقديمه يُطابَق نصُّه وحده من جديد.
    """
    from classify.services.classifier import (
        ATTRIBUTION,
        HADITH_SIGNAL,
        Segment,
        _classify_unit,
    )
    from classify.services.normalizer import light
    from classify.services.splitter import _split_by_rules

    hadith = get_matchers()[1]
    out = []
    for seg in segments:
        m = HADITH_LEADIN.match(seg.content.strip())
        lead = m.group("lead").strip() if m else ""
        if (
            seg.kind not in ("attribution", "text", "term", "hadith")
            or not lead
            or len(lead.split()) > LEADIN_MAX_WORDS
            or not ATTRIBUTION.search(light(lead))
        ):
            out.append(seg)
            continue
        rest = m.group("rest").strip()
        lead_seg = Segment("attribution", lead, note="صيغة الإسناد", para=seg.para, level=seg.level)
        if seg.kind == "hadith":
            match = hadith.match(rest.strip('«»"“” '))
            if match and match.score >= HADITH_SIGNAL:
                score = match.score
                seg.content, seg.source, seg.score = rest, match.source, score
                seg.note = "مطابقة تامة" if score >= 0.95 else f"مطابقة {int(score * 100)}%"
                out += [lead_seg, seg]
            else:
                out.append(seg)
            continue
        units = _split_by_rules(rest) or [rest]
        pieces, prev = [], lead_seg
        for i, unit in enumerate(units):
            context = units[i - 1] if i else lead
            nxt = units[i + 1] if i + 1 < len(units) else ""
            prev = _classify_unit(unit, context, False, prev, nxt)
            prev.para, prev.level = seg.para, seg.level
            pieces.append(prev)
        if any(piece.kind in ("hadith", "quran") for piece in pieces):
            out += [lead_seg, *pieces]
        else:
            out.append(seg)
    return out


STANDALONE_CITATION = re.compile(
    r"^[\[(]\s*(?P<surah>[^\][()\d:]{1,25}?)\s*[:：]\s*(?P<ayah>\d{1,3})\s*[\])]\s*[.،؟!]?\s*$"
)


def resolve_citations(segments) -> int:
    """يصنّف وحدات الإحالة المستقلة ويرجّح بسورتها مطابقة الآية السابقة في المتشابهات."""
    from classify.services.matchers import surah_name_words
    from classify.services.normalizer import normalize

    quran = get_matchers()[0]
    changed = 0
    for i, seg in enumerate(segments):
        if seg.kind not in ("text", "term", "citation"):
            continue
        m = STANDALONE_CITATION.match(seg.content.strip())
        if not m:
            continue
        surah = m.group("surah").strip()
        name = tuple(normalize(surah).removeprefix("سورة").split())
        if name not in surah_name_words():
            continue
        if seg.kind != "citation":
            seg.kind, seg.terms, seg.note = "citation", [], "إحالة مصدر"
            changed += 1
        prev = next(
            (s for s in reversed(segments[:i]) if s.para == seg.para and s.kind != "attribution"),
            None,
        )
        if prev is not None and prev.kind == "quran" and surah not in (prev.source or ""):
            match = quran.match(prev.content, prefer=surah)
            if match and surah in match.source and match.score >= (prev.score or 0) - 0.05:
                prev.source, prev.score = match.source, match.score
                changed += 1
    return changed


def chain_quran_sequence(segments) -> list:
    """يسوّر وحدة من آيات متتابعة كاملة بلا فواصل آيةً آية، بتسامح كلمة واحدة في الآية."""
    from collections import defaultdict

    from rapidfuzz import fuzz

    from classify.services.classifier import Segment
    from classify.services.normalizer import expand_dagger, normalize

    quran = get_matchers()[0]
    records = quran.index.records
    verse_forms: list[list[set]] = []
    for i, n1 in enumerate(quran.index.norm):
        w1 = n1.split()
        n2 = quran.index.norm2[i]
        w2 = n2.split() if n2 else w1
        if len(w2) != len(w1):
            w2 = w1
        verse_forms.append([{w1[k], w2[k]} for k in range(len(w1))])
    by_first = defaultdict(list)
    for i, forms in enumerate(verse_forms):
        if forms:
            for first in forms[0]:
                by_first[first].append(i)
    ref_index = {(r["surah"], int(r["ayah"])): i for i, r in enumerate(records)}

    RUN_KINDS = ("text", "term", "quran", "hadith", "athar")
    runs: list[list] = []
    for seg in segments:
        if seg.kind in RUN_KINDS and runs and runs[-1][-1].kind in RUN_KINDS:
            runs[-1].append(seg)
        else:
            runs.append([seg])

    out = []
    for run in runs:
        tokens: list[str] = []
        tok_unit: list[int] = []
        unit_tok_start: list[int] = []
        for u, s in enumerate(run):
            unit_tok_start.append(len(tokens))
            words = s.content.split()
            tokens.extend(words)
            tok_unit.extend([u] * len(words))
        unit_tok_start.append(len(tokens))
        bracketed = any("﴿" in s.content for s in run)
        if run[0].kind not in RUN_KINDS or (len(tokens) < 6 and not bracketed):
            out.extend(run)
            continue
        pairs = []
        for idx, t in enumerate(tokens):
            for piece in _AYAH_NUMBERS.sub(" ", t).split():
                forms = {normalize(piece), normalize(expand_dagger(piece))} - {""}
                if forms:
                    pairs.append((idx, forms))

        def fit_len(i, pos, pairs=pairs):
            """عدد كلمات الوحدة التي تستهلكها الآية i بدءاً من pos مع الفرق، أو None."""
            vw = verse_forms[i]
            p, k = pos, 0
            diff = None
            while k < len(vw):
                if p >= len(pairs):
                    return None
                forms = pairs[p][1]
                if vw[k] & forms:
                    p, k = p + 1, k + 1
                    continue
                if p + 1 < len(pairs) and vw[k] & {a + b for a in forms for b in pairs[p + 1][1]}:
                    p, k = p + 2, k + 1
                    continue
                if k + 1 < len(vw) and forms & {a + b for a in vw[k] for b in vw[k + 1]}:
                    p, k = p + 1, k + 2
                    continue
                if diff is not None:
                    return None
                got, want = sorted(forms)[0], sorted(vw[k])[0]
                if max(fuzz.ratio(a, b) for a in forms for b in vw[k]) >= 65:
                    diff = {"extra": [got], "missing": [want]}
                    p, k = p + 1, k + 1
                    continue
                if p + 1 < len(pairs) and vw[k] & pairs[p + 1][1]:
                    diff = {"extra": [got], "missing": []}
                    p, k = p + 2, k + 1
                    continue
                if k + 1 < len(vw) and vw[k + 1] & forms:
                    diff = {"extra": [], "missing": [want]}
                    k += 1
                    continue
                if k + 1 == len(vw) and len(vw) >= 4:
                    diff = {"extra": [], "missing": [want]}
                    k += 1
                    continue
                return None
            return p - pos, diff

        def fit_gap(i, pos, pairs=pairs):
            """الآية التالية بالتسلسل مع كلمات ساقطة؛ تُقبل إن تابعت الوحدة كلماتها بلا دخيل."""
            vw = verse_forms[i]
            p, missing = pos, []
            for k in range(len(vw)):
                if p < len(pairs) and vw[k] & pairs[p][1]:
                    p += 1
                elif p + 1 < len(pairs) and vw[k] & {
                    a + b for a in pairs[p][1] for b in pairs[p + 1][1]
                }:
                    p += 2
                else:
                    missing.append(sorted(vw[k])[0])
            matched = len(vw) - len(missing)
            if len(missing) >= 2 and matched >= 2 and matched * 2 >= len(vw):
                return p - pos, {"extra": [], "missing": missing}
            return None

        pair_start = []
        j = 0
        for v in range(len(run) + 1):
            while j < len(pairs) and pairs[j][0] < unit_tok_start[v]:
                j += 1
            pair_start.append(j)
        boundary_unit = {p: v for v, p in enumerate(pair_start)}

        def attempt(
            u,
            pairs=pairs,
            run=run,
            fit_len=fit_len,
            fit_gap=fit_gap,
            pair_start=pair_start,
            boundary_unit=boundary_unit,
        ):
            """أطول مدى يبدأ بالوحدة u ويُسبك آيات كاملة؛ يعيد (السلسلة، وحدة النهاية)."""
            pos, chain, prev, best = pair_start[u], [], None, None

            def good(end):
                return end is not None and end > u and len(chain) >= 2

            while pos < len(pairs):
                if good(boundary_unit.get(pos)):
                    best = (list(chain), boundary_unit[pos])
                first_forms = set(pairs[pos][1])
                if pos + 1 < len(pairs):
                    first_forms |= {a + b for a in pairs[pos][1] for b in pairs[pos + 1][1]}
                candidates = set()
                for form in first_forms:
                    candidates.update(by_first.get(form, []))
                nxt = None
                if prev is not None:
                    nxt = ref_index.get((records[prev]["surah"], int(records[prev]["ayah"]) + 1))
                    if nxt is not None:
                        candidates.add(nxt)
                fitting = [(i, fit_len(i, pos)) for i in sorted(candidates)]
                fitting = [(i, hit[0], hit[1]) for i, hit in fitting if hit]
                if not fitting and nxt is not None:
                    hit = fit_gap(nxt, pos)
                    if hit:
                        fitting = [(nxt, hit[0], hit[1])]
                if not fitting:
                    break
                seq = [
                    (i, used, diff)
                    for i, used, diff in fitting
                    if prev is not None
                    and records[i]["surah"] == records[prev]["surah"]
                    and int(records[i]["ayah"]) == int(records[prev]["ayah"]) + 1
                ]
                pick = next(
                    (c for pool in (seq, fitting) for c in pool if c[2] is None),
                    (seq or fitting)[0],
                )
                chain.append((pos, pick[0], pick[2]))
                pos += pick[1]
                prev = pick[0]
            if good(boundary_unit.get(pos)):
                best = (list(chain), boundary_unit[pos])
            return best

        spans = []
        u = 0
        while u < len(run):
            hit = attempt(u)
            if hit:
                spans.append((u, hit[0], hit[1]))
                u = hit[1]
            else:
                u += 1
        if not spans:
            out.extend(run)
            continue
        cursor = 0
        for u0, chain, v0 in spans:
            out.extend(run[cursor:u0])
            for k, (start, i, diff) in enumerate(chain):
                first_tok = pairs[start][0]
                last_tok = (
                    pairs[chain[k + 1][0]][0] - 1 if k + 1 < len(chain) else unit_tok_start[v0] - 1
                )
                r = records[i]
                note, score = "آيات متتابعة أُجيزت بالمصحف", 1.0
                if diff:
                    note, score = bert_layer._note_variant({"diff": diff}), 0.9
                content = " ".join(tokens[first_tok : last_tok + 1])
                if any("﴿" in run[x].content for x in range(u0, v0)):
                    core = content.replace("﴿", "").replace("﴾", "").strip()
                    tail = _TRAILING_PUNCT.search(core)
                    cut = tail.start() if tail else len(core)
                    content = f"﴿{core[:cut].strip()}﴾{core[cut:]}"
                out.append(
                    Segment(
                        "quran",
                        content,
                        source=f"سورة {r['surah']} — {r['ayah']}",
                        score=score,
                        note=note,
                        para=run[tok_unit[first_tok]].para,
                    )
                )
            cursor = v0
        out.extend(run[cursor:])
    return out


_AYAH_NUMBERS = re.compile(r"[\s ]*[٠-٩0-9]+[\s ]*")


_TRAILING_PUNCT = re.compile(r"[\s.،؛:!؟?]+$")


def rescue_short_ayas(segments) -> int:
    """ينقذ آية قصيرة سقطت نصاً بين آيات بمطابقة تامة على المصحف مرجّحة بالسياق."""
    accept = float(os.environ.get("ACCEPT_QURAN", "0.82"))
    quran = get_matchers()[0]
    changed = 0
    for i, seg in enumerate(segments):
        if seg.kind not in ("text", "term"):
            continue
        clean = _AYAH_NUMBERS.sub(" ", seg.content).strip(" .،؛")
        if not (1 <= len(clean.split()) <= 4):
            continue
        prev = next((s for s in reversed(segments[:i]) if s.para == seg.para), None)
        nxt = next((s for s in segments[i + 1 :] if s.para == seg.para), None)
        neighbors = [s for s in (prev, nxt) if s is not None and s.kind == "quran"]
        if not neighbors:
            continue
        source, score = _exact_short_verse(quran, clean, neighbors)
        if source is None:
            match = quran.match(clean, short=True)
            if match and match.score >= accept:
                source, score = match.source, match.score
        if source:
            seg.kind, seg.source, seg.score = "quran", source, score
            seg.terms, seg.note = [], "آية قصيرة أُجيزت بسياقها القرآني"
            changed += 1
    return changed


_SOURCE_REF = re.compile(r"سورة\s+(?P<surah>.+?)\s*[—–-]\s*(?P<ayah>\d+)")


def _exact_short_verse(quran, clean, neighbors):
    """مطابقة تامة لآية كاملة؛ عند تعدد المواضع تُرجَّح سورة الجار وتسلسل الأرقام."""
    from classify.services.normalizer import normalize

    nclean = normalize(clean)
    hits = [
        quran.index.records[i]
        for i, norm_text in enumerate(quran.index.norm)
        if nclean in (norm_text, quran.index.norm2[i])
    ]
    if not hits:
        return None, None
    prev_refs = [_SOURCE_REF.search(s.source or "") for s in neighbors]
    for ref in prev_refs:
        if not ref:
            continue
        same = [h for h in hits if str(h.get("surah", "")).strip() == ref.group("surah").strip()]
        if same:
            after = [h for h in same if int(h.get("ayah", 0)) > int(ref.group("ayah"))]
            hit = min(after or same, key=lambda h: int(h.get("ayah", 0)))
            return f"سورة {hit['surah']} — {hit['ayah']}", 1.0
    hit = hits[0]
    return f"سورة {hit['surah']} — {hit['ayah']}", 1.0


def prefer_sequential_duplicates(segments) -> int:
    """يرد الآية المكررة النص في المصحف إلى تسلسل الآية التي قبلها في فقرتها."""
    from classify.services.normalizer import normalize

    quran = get_matchers()[0]
    idx = quran.index
    by_ref = {(r["surah"], int(r["ayah"])): i for i, r in enumerate(idx.records)}
    changed = 0
    last: dict = {}
    for seg in segments:
        if seg.kind != "quran" or not seg.source:
            continue
        ref = _SOURCE_REF.search(seg.source)
        if not ref:
            continue
        surah, ayah = ref.group("surah").strip(), int(ref.group("ayah"))
        prev = last.get(seg.para)
        if prev and (surah, ayah) != (prev[0], prev[1] + 1):
            i = by_ref.get((prev[0], prev[1] + 1))
            if i is not None:
                nclean = normalize(_AYAH_NUMBERS.sub(" ", seg.content)).strip(" .،؛")
                if nclean and nclean in (idx.norm[i], idx.norm2[i]):
                    record = idx.records[i]
                    surah, ayah = record["surah"], int(record["ayah"])
                    seg.source, seg.score = f"سورة {surah} — {ayah}", 1.0
                    seg.note = (f"{seg.note} | " if seg.note else "") + "رُجّحت بتسلسل سياقها"
                    changed += 1
        last[seg.para] = (surah, ayah)
    return changed


def enforce_quran_precedence(segments) -> int:
    """يعرض ما حُكم عليه حديثاً أو أثراً على فهرس القرآن أولاً ويعيد عدد ما أُعيد تصنيفه."""
    accept = float(os.environ.get("ACCEPT_QURAN", "0.82"))
    quran = get_matchers()[0]
    changed = 0
    for segment in segments:
        if segment.kind not in ("hadith", "athar"):
            continue
        match = quran.match(segment.content)
        if match and match.score >= accept:
            segment.note = f"أسبقية المصحف: كان {segment.kind} — {segment.source}"
            segment.kind, segment.source, segment.score = "quran", match.source, match.score
            changed += 1
    return changed


def run(paragraphs, progress=None):
    """خط الإنتاج كاملاً: المصنّف ثم BERT ثم المراجعة ثم نسبة القول ثم أسبقية المصحف."""

    def step(stage, pct):
        if progress:
            progress(stage, pct)

    step("التقسيم والتصنيف بالفهارس", 8)
    segments = classify_paragraphs(paragraphs)
    step("تمييز العناوين", 24)
    reviewer.mark_headings(segments, paragraphs)
    segments = split_trailing_leadins(segments)
    segments = peel_quran_units(segments)
    segments = peel_hadith_leadins(segments)
    step("طبقة BERT (تحميل النموذج عند أول طلب)", 30)
    bert_layer.enrich(segments)
    # BERT قد يفصل ما بعد الآية المقوّسة («﴾، وقال النبي: …») فيُعاد فصل التقديم عن الحديث
    segments = peel_hadith_leadins(segments)
    step("مراجعة Gemini", 60)
    reviewer.review(
        segments,
        {i: s.kind in ("title", "citation", "attribution") for i, s in enumerate(segments)},
        on_progress=lambda done, total: step(
            f"مراجعة Gemini ({done}/{total})", 60 + round(30 * done / max(total, 1))
        ),
    )
    step("قواعد التصحيح", 92)
    segments = chain_quran_sequence(segments)
    segments = split_trailing_leadins(segments)
    prefer_sequential_duplicates(segments)
    resolve_citations(segments)
    rescue_short_ayas(segments)
    speaker.reattribute(segments)
    enforce_quran_precedence(segments)
    return segments


def unique_title(title: str) -> str:
    """يعيد عنواناً غير مكرر بإلحاق رقم تسلسلي: «نص ملصق» ثم «نص ملصق (2)»."""
    title = title.strip()
    taken = set(Document.objects.filter(title__startswith=title).values_list("title", flat=True))
    if title not in taken:
        return title
    n = 2
    while f"{title} ({n})" in taken:
        n += 1
    return f"{title} ({n})"


def save_document(title, kind, source_file_name, segments, *, replace=False):
    """يبني عقد الواجهة 2.0 ويحفظه في ``content``؛ يعيد (المستند، العقد)."""
    payload = build_payload(
        title,
        segments,
        source={"kind": "file" if source_file_name else "text", "name": source_file_name},
    )
    glossary_ids = {
        entry.ar: entry.pk
        for entry in Glossary.objects.filter(
            ar__in={
                term["ar"]
                for row in payload["phrases"]
                for term in row.get("analysis", {}).get("terms") or []
                if term.get("ar")
            }
        )
    }
    with transaction.atomic():
        existing = Document.objects.filter(title=title)
        if existing.exists():
            if not replace:
                raise DuplicateTitleError(title)
            existing.delete()

        document = Document.objects.create(
            title=title, kind=kind, source_file_name=source_file_name
        )
        phrases, analyses, occurrences = [], [], []
        for row in payload["phrases"]:
            analysis = row["analysis"]
            phrases.append(
                Phrase(
                    phrase_id=row["phrase_id"],
                    document=document,
                    content_type_id=row["content_type_id"],
                    group_id=row["group_id"],
                    group_order=row["group_order"],
                    text=row["arabic_text"],
                    tag=row["tag"],
                    text_type=row["text_type"],
                    align=row["align"],
                    translatable=row["translatable"],
                )
            )
            kind_value = analysis["kind"]
            reference = "" if kind_value in ("hadith", "athar") else analysis.get("source") or ""
            analyses.append(
                PhraseAnalysis(
                    phrase_id=row["phrase_id"],
                    kind=analysis["kind"],
                    reason_code=analysis["reason_code"],
                    confidence=round(analysis["confidence"] * 100),
                    reference=reference,
                )
            )
            linked = set()
            for term in analysis.get("terms") or []:
                glossary_id = glossary_ids.get(term.get("ar"))
                if glossary_id and glossary_id not in linked:
                    linked.add(glossary_id)
                    occurrences.append(
                        PhraseTerm(phrase_id=row["phrase_id"], glossary_id=glossary_id)
                    )
        Phrase.objects.bulk_create(phrases)
        PhraseAnalysis.objects.bulk_create(analyses)
        PhraseTerm.objects.bulk_create(occurrences)
    return document, payload


INTERNAL_OF_KIND = {kind.value: internal for internal, kind in KIND_OF_INTERNAL.items()}
DICT_OF_CATEGORY = {category.value: name for name, category in TERM_CATEGORY_OF_DICT.items()}


@dataclass
class StoredSegment:
    """مقطع بعقد سمات المحرّك، مبني من صفوف ``content`` المحفوظة."""

    kind: str
    content: str
    source: str
    score: float | None
    para: int
    level: int
    note: str = ""
    reviewed: bool = False
    terms: list = field(default_factory=list)


def segments_from_document(document):
    """يعيد بناء مقاطع بعقد المحرّك من عبارات مستند محفوظ (للتصدير والعرض)."""
    phrases = (
        document.phrases.select_related("analysis")
        .prefetch_related("terms__glossary")
        .order_by("group_id", "group_order")
    )
    out = []
    for phrase in phrases:
        analysis = phrase.analysis
        kind = INTERNAL_OF_KIND.get(analysis.kind, "text")
        matched = kind in ("quran", "hadith", "athar")
        level = int(phrase.tag[-1]) if phrase.tag.startswith("heading") else 0
        out.append(
            StoredSegment(
                kind=kind,
                content=phrase.text,
                source=analysis.reference,
                score=analysis.confidence / 100 if matched else None,
                para=phrase.group_id,
                level=level or (1 if kind == "title" else 0),
                terms=[
                    {
                        "arabic": occurrence.glossary.ar,
                        "english": occurrence.glossary.en,
                        "kind": DICT_OF_CATEGORY.get(occurrence.glossary.category, "terms"),
                    }
                    for occurrence in phrase.terms.all()
                ],
            )
        )
    return out
