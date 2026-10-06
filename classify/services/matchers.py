import json
import os
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from .normalizer import (
    expand_dagger,
    has_uthmani,
    lexical,
    lexical_tokens,
    normalize,
    split_vocative,
    strip_affixes,
    tokens,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NGRAM = 3
NGRAM_FALLBACK = 2
FALLBACK_MAX_WORDS = 8
UNIGRAM_MAX_WORDS = 3


@dataclass
class Match:
    kind: str
    source: str
    score: float
    extra: dict


COVERED = 80


class NgramIndex:
    def __init__(self, records: list[dict], fallback_all: bool = False):
        """fallback_all: يبني الفهرس الاحتياطي من كل السجلات لا القصيرة وحدها؛ للمصحف فقط."""
        self.fallback_all = fallback_all
        self._init(records)

    def _init(self, records: list[dict]):
        self.records = records
        self.norm = [normalize(r["text"]) for r in records]
        self.norm2: list[str | None] = []
        self.words = []
        self.index: dict[tuple, set[int]] = defaultdict(set)
        self.index2: dict[tuple, set[int]] = defaultdict(set)
        self.index1: dict[str, set[int]] = defaultdict(set)
        for i, r in enumerate(records):
            n1 = self.norm[i]
            n2 = normalize(expand_dagger(r["text"]))
            self.norm2.append(n2 if n2 != n1 else None)
            forms = {n1, n2, split_vocative(n1), split_vocative(n2)}
            seen: list[str] = []
            n_words = len(n1.split())
            for form in forms:
                words = form.split()
                seen.extend(w for w in words if w not in seen)
                for j in range(len(words) - NGRAM + 1):
                    self.index[tuple(words[j : j + NGRAM])].add(i)
                if self.fallback_all or n_words <= FALLBACK_MAX_WORDS:
                    for j in range(len(words) - NGRAM_FALLBACK + 1):
                        self.index2[tuple(words[j : j + NGRAM_FALLBACK])].add(i)
                if n_words <= UNIGRAM_MAX_WORDS:
                    for word in words:
                        self.index1[word].add(i)
            self.words.append(seen)

    def candidates(self, text: str, short: bool = False) -> list[int]:
        words = tokens(text)
        hits: dict[int, int] = defaultdict(int)
        for j in range(len(words) - NGRAM + 1):
            for i in self.index.get(tuple(words[j : j + NGRAM]), ()):
                hits[i] += 1
        if not hits:
            for j in range(len(words) - NGRAM_FALLBACK + 1):
                for i in self.index2.get(tuple(words[j : j + NGRAM_FALLBACK]), ()):
                    hits[i] += 1
        if not hits and short and len(words) <= UNIGRAM_MAX_WORDS:
            for word in words:
                for i in self.index1.get(word, ()):
                    hits[i] += 1
        return sorted(hits, key=hits.get, reverse=True)[:5]

    def coverage(self, qwords: list[str], i: int) -> float:
        """نسبة كلمات المقطع الواردة في المرجع بمقارنة ضبابية تتسامح مع اختلاف الرسم."""
        ref = self.words[i]
        return sum(any(fuzz.ratio(w, rw) >= COVERED for rw in ref) for w in qwords) / len(qwords)

    def best(self, text: str, short: bool = False, prefer: str = "") -> tuple[int, float] | None:
        hit = self._best(text, short, prefer)
        if has_uthmani(text):
            alt = self._best(expand_dagger(text), short, prefer)
            if alt and (hit is None or alt[1] > hit[1]):
                hit = alt
        return hit

    PREFER_MARGIN = 8.0

    def _best(self, text: str, short: bool = False, prefer: str = "") -> tuple[int, float] | None:
        query = normalize(text)
        qwords = query.split()
        if len(qwords) < (1 if short else 2):
            return None
        best_i, best_score = None, 0.0
        pref_i, pref_score = None, 0.0
        prefer = normalize(prefer) if prefer else ""
        for i in self.candidates(text, short):
            score = 0.0
            for ref in (self.norm[i], self.norm2[i]):
                if ref is None:
                    continue
                s = fuzz.partial_ratio(query, ref)
                if len(query) > len(ref) * 1.3:
                    s = fuzz.ratio(query, ref)
                else:
                    s *= self.coverage(qwords, i)
                score = max(score, s)
            if score > best_score:
                best_i, best_score = i, score
            if prefer and score > pref_score and self._surah(i) == prefer:
                pref_i, pref_score = i, score
        if pref_i is not None and pref_score >= best_score - self.PREFER_MARGIN:
            best_i, best_score = pref_i, pref_score
        if best_i is None:
            return None
        return best_i, best_score / 100

    def _surah(self, i: int) -> str:
        return normalize(str(self.records[i].get("surah", "")))


class QuranMatcher:
    def __init__(self):
        self.index = NgramIndex(
            json.loads((DATA_DIR / "quran.json").read_text(encoding="utf-8")), fallback_all=True
        )

    def match(self, text: str, short: bool = False, prefer: str = "") -> Match | None:
        """يطابق النص؛ short يأذن بالفهرس الأحادي، وprefer سورة الإحالة المرجَّحة عند التقارب."""
        hit = self.index.best(text, short, prefer)
        if not hit:
            return None
        i, score = hit
        r = self.index.records[i]
        return Match(
            "quran",
            f"سورة {r['surah']} — {r['ayah']}",
            score,
            {"surah_no": r["surah_no"], "ayah": r["ayah"]},
        )


class NullMatcher:
    """مطابِقٌ معطَّل: لا يُحمَّل فهرسه ولا يُطابق شيئاً."""

    index = NgramIndex([])

    def match(self, text: str) -> Match | None:
        return None


class HadithMatcher:
    def __init__(self):
        self.index = NgramIndex(json.loads((DATA_DIR / "hadith.json").read_text(encoding="utf-8")))

    def match(self, text: str) -> Match | None:
        hit = self.index.best(text)
        if not hit:
            return None
        i, score = hit
        r = self.index.records[i]
        return Match("hadith", f"{r['source']} — {r['number']}", score, {"number": r["number"]})


PHRASE_MAX = 8

DICT_LABEL = {
    "terms": "مصطلح",
    "alam": "عَلَم",
    "amaken": "مكان",
    "asmaa": "اسم وصفة",
    "feraq": "فرقة",
    "sefat": "صفة",
}


@lru_cache(maxsize=1)
def _common_terms() -> frozenset[str]:
    path = DATA_DIR / "term_docfreq.json"
    cap = float(os.environ.get("TERM_DF_MAX", "0.70"))
    if not path.exists() or cap >= 1.0:
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    n = max(data.get("books", 1), 1)
    return frozenset(w for w, df in data["df"].items() if df / n >= cap)


HONORIFIC = (
    ("رحمه", "الله"),
    ("رحمها", "الله"),
    ("رحمهم", "الله"),
    ("رحمهما", "الله"),
    ("رحمهن", "الله"),
    ("رحمك", "الله"),
    ("رحمكم", "الله"),
    ("رحمكما", "الله"),
    ("رحمكن", "الله"),
    ("رحمني", "الله"),
    ("رحمنا", "الله"),
    ("رضي", "الله", "عنه"),
    ("رضي", "الله", "عنها"),
    ("رضي", "الله", "عنهم"),
    ("رضي", "الله", "عنهما"),
    ("صلى", "الله", "عليه", "وسلم"),
    ("صلى", "الله", "عليه", "واله", "وسلم"),
    ("عليه", "السلام"),
    ("عليهم", "السلام"),
    ("عليهما", "السلام"),
    ("عليه", "الصلاة", "والسلام"),
    ("سبحانه", "وتعالى"),
    ("عز", "وجل"),
    ("جل", "جلاله"),
    ("تبارك", "وتعالى"),
)
_HONOR = {tuple(lexical(" ".join(f)).split()) for f in HONORIFIC}
_HONOR_MAX = max(len(f) for f in _HONOR)

FUNCTION_SURFACE = frozenset({"وهم", "هم", "وهو", "هو", "وهي", "هي"})


class GlossaryMatcher:
    def __init__(self):
        self.terms = json.loads((DATA_DIR / "glossary.json").read_text(encoding="utf-8"))
        keep = set(filter(None, os.environ.get("GLOSSARY_DICTS", "terms").split(",")))
        common = _common_terms()
        min_words = int(os.environ.get("TERM_MIN_WORDS", "1"))
        self.lookup = {}
        for t in self.terms:
            if keep and t.get("dict", "terms") not in keep:
                continue
            if t["arabic"] in common:
                continue
            key = lexical(t["arabic"])
            if len(key.split()) < min_words:
                continue
            self.lookup[key] = t
        self.span = min(PHRASE_MAX, max((len(k.split()) for k in self.lookup), default=1))

    @staticmethod
    def _tag(term: dict, surface: str) -> dict:
        kind = term.get("dict", "terms")
        return {**term, "surface": surface, "kind": kind, "label": DICT_LABEL.get(kind, "مصطلح")}

    def _phrase(self, words: list[str], i: int) -> tuple[dict, int] | None:
        """أطول عبارة تبدأ عند i، مع تسامحٍ في سوابق أول كلمة («بصلاة» ← «صلاة»)."""
        for n in range(min(self.span, len(words) - i), 1, -1):
            tail = " ".join(words[i + 1 : i + n])
            for head in strip_affixes(words[i]):
                term = self.lookup.get(f"{head} {tail}")
                if term:
                    return term, n
        return None

    @staticmethod
    def _honorific_mask(words: list[str]) -> set[int]:
        """مواضعُ كلمات صيغ الترحّم والتعظيم، تُتخطّى في البحث."""
        masked: set[int] = set()
        for i in range(len(words)):
            for n in range(min(_HONOR_MAX, len(words) - i), 1, -1):
                if tuple(words[i : i + n]) in _HONOR:
                    masked.update(range(i, i + n))
                    break
        return masked

    def find(self, text: str) -> list[dict]:
        words = lexical_tokens(text)
        masked = self._honorific_mask(words)
        found, seen, i = [], set(), 0
        while i < len(words):
            if i in masked:
                i += 1
                continue
            hit = self._phrase(words, i)
            if hit:
                term, n = hit
                if term["arabic"] not in seen:
                    seen.add(term["arabic"])
                    found.append(self._tag(term, " ".join(words[i : i + n])))
                i += n
                continue
            if words[i] in FUNCTION_SURFACE:
                i += 1
                continue
            for form in strip_affixes(words[i]):
                term = self.lookup.get(form)
                if term and term["arabic"] not in seen:
                    seen.add(term["arabic"])
                    found.append(self._tag(term, words[i]))
                    break
            i += 1
        return found


@lru_cache(maxsize=1)
def surah_name_words() -> frozenset[tuple[str, ...]]:
    """أسماء سور المصحف مطبَّعةً كلماتٍ («آل عمران» ← ("ال", "عمران"))."""
    quran = get_matchers()[0]
    return frozenset(tuple(normalize(str(r["surah"])).split()) for r in quran.index.records)


def contains_surah_name(text: str) -> bool:
    """هل في النص اسمُ سورةٍ من المصحف كلمةً تامة (أو كلماتٍ متتابعة)؟"""
    words = tuple(normalize(text).split())
    names = surah_name_words()
    spans = {len(name) for name in names}
    return any(words[i : i + n] in names for n in spans for i in range(len(words) - n + 1))


@lru_cache(maxsize=1)
def get_matchers():
    hadith = HadithMatcher() if os.environ.get("HADITH_MATCH") == "1" else NullMatcher()
    return QuranMatcher(), hadith, GlossaryMatcher()
