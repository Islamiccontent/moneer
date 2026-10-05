"""مطابقة الجملة بآية واحدة على الأعمدة المحسوبة في QuranAyah: مرجعاً ثم احتواءً ثم تقريباً."""

import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz

from classify.services.normalizer import expand_dagger, has_uthmani, light, normalize
from translate.models import QuranAyah

_STRIP = re.compile(r"[*\"”“{}\[\]()﴿﴾؛:\d،,.‌'\-«»!؟?]")
_QUOTED = re.compile(r"﴿(.+?)﴾", re.S)
_ARABIC_LETTER = re.compile(r"[\u0621-\u064A\u0671]")
_REFERENCE = re.compile(r"سورة\s+(?P<surah>.+?)\s+[—–-]\s+(?P<ayah>\d+)")

FUZZY_ANCHOR_MIN = 0.6
FUZZY_COVER_MIN = 90


@dataclass
class QuranMatch:
    """آية واحدة تغطّي نص الجملة."""

    ayah: QuranAyah
    method: str
    exact_full: bool

    @property
    def reference(self):
        return str(self.ayah)


def quoted_part(text):
    """ما بين ﴿ ﴾ إن وُجد وحوى حروفاً، وإلا النص كله؛ رقم الآية بين القوسين يُتجاهل."""
    quoted = [q.strip() for q in _QUOTED.findall(text) if _ARABIC_LETTER.search(q)]
    return " ".join(quoted) if quoted else text


def query_forms(text):
    """(بلا تشكيل، مطبَّع، مطبَّع بعد ردّ الرسم العثماني) لنص الجملة."""
    base = _STRIP.sub(" ", quoted_part(text))
    clean = light(base)
    norm = normalize(base)
    norm_uthmani = normalize(expand_dagger(base)) if has_uthmani(base) else norm
    return clean, norm, norm_uthmani


@lru_cache(maxsize=1)
def _classifier_matcher():
    from classify.services.matchers import QuranMatcher

    return QuranMatcher()


class AyahIndex:
    """آيات المصحف في الذاكرة لمطابقة متكررة بلا استعلام لكل جملة."""

    def __init__(self, ayat=None):
        rows = list(ayat) if ayat is not None else list(QuranAyah.objects.all())
        rows.sort(key=lambda a: (a.surah_no, a.ayah_no))
        self.rows = rows
        self.by_key = {(a.surah_no, a.ayah_no): a for a in rows}
        self.surah_by_name = {normalize(a.surah_name): a.surah_no for a in rows}

    def __len__(self):
        return len(self.rows)

    def parse_reference(self, reference):
        """آية المرجع «سورة X — N» أو None."""
        match = _REFERENCE.search(reference or "")
        if not match:
            return None
        surah_no = self.surah_by_name.get(normalize(match["surah"]))
        return self.by_key.get((surah_no, int(match["ayah"]))) if surah_no else None

    def find(self, text, reference=""):
        """الآية التي تغطّي نص الجملة، أو None."""
        clean, norm, norm_u = query_forms(text)
        if not norm:
            return None
        forms = {f for f in (norm, norm_u) if f}

        anchors = []
        referenced = self.parse_reference(reference)
        if referenced:
            anchors.append((referenced, "reference"))
        anchors += [
            (a, "clean") for a in self._containing(("clean_imlaei", "clean_uthmani"), {clean})
        ]
        anchors += [
            (a, "normalized")
            for a in self._containing(("normalized_imlaei", "normalized_uthmani"), forms)
        ]
        fuzzy = self._fuzzy_anchor(text)
        if fuzzy:
            anchors.append((fuzzy, "fuzzy"))

        seen = set()
        for ayah, method in anchors:
            if ayah.pk in seen:
                continue
            seen.add(ayah.pk)
            if self._covers(ayah, forms):
                return QuranMatch(ayah, method, self._is_exact_full(ayah, clean, forms))
        return None

    def _containing(self, fields, needles):
        needles = {n for n in needles if n}
        if not needles:
            return []
        return [
            a for a in self.rows if any(n in getattr(a, field) for field in fields for n in needles)
        ]

    def _fuzzy_anchor(self, text):
        hit = _classifier_matcher().match(quoted_part(text))
        if not hit or hit.score < FUZZY_ANCHOR_MIN:
            return None
        return self.by_key.get((hit.extra.get("surah_no"), hit.extra.get("ayah")))

    @staticmethod
    def _covers(ayah, forms):
        """هل يغطّي نص الآية الجملة؟ احتواءً حرفياً، أو تشابهاً جزئياً عالياً دون أن تكون أقصر منها."""
        for attr in ("normalized_imlaei", "normalized_uthmani"):
            text = getattr(ayah, attr)
            for form in forms:
                if form in text:
                    return True
                score = (
                    fuzz.partial_ratio(form, text)
                    if len(text) >= len(form)
                    else fuzz.ratio(form, text)
                )
                if score >= FUZZY_COVER_MIN:
                    return True
        return False

    @staticmethod
    def _is_exact_full(ayah, clean, forms):
        return clean in (ayah.clean_imlaei, ayah.clean_uthmani) or bool(
            forms & {ayah.normalized_imlaei, ayah.normalized_uthmani}
        )
