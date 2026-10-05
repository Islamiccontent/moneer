import re

DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
QURAN_MARKS = re.compile(r"[\u06DD\u06DE\u06E9\uFDFA\uFDFB\uFDFD\u06D6-\u06DC]")
PUNCT = re.compile(r"[\u060C\u061B\u061F\u066A-\u066D\u06D4.,;:!?\"'«»﴿﴾()\[\]{}\-–—…]")
SPACES = re.compile(r"\s+")

SPELLING = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"}

LEXICAL = str.maketrans(SPELLING)
ALEF = str.maketrans({**SPELLING, "ة": "ه"})

PREFIXES = (
    "وبال",
    "فبال",
    "وال",
    "فال",
    "بال",
    "كال",
    "لل",
    "ال",
    "وب",
    "فب",
    "ول",
    "فل",
    "و",
    "ف",
    "ب",
    "ل",
    "ك",
)
PRONOUNS = ("هما", "كما", "ها", "هم", "هن", "كم", "كن", "نا", "ه", "ك")
SUFFIXES = PRONOUNS + ("ا", "ات", "ون", "ين", "ان")


def normalize(text: str) -> str:
    text = QURAN_MARKS.sub("", text)
    text = DIACRITICS.sub("", text)
    text = text.translate(ALEF)
    text = PUNCT.sub(" ", text)
    return SPACES.sub(" ", text).strip()


DAGGER = "ٰ"
_DAGGER_AFTER_WY = re.compile(f"[وي]{DAGGER}")


_HAMZA_ALEF = re.compile(r"ءَ?ا")


def expand_dagger(text: str) -> str:
    """يرد الرسم العثماني إلى الإملائي (الألف الخنجرية و«ءا»)؛ يُقاس إلى جانب الصورة المجردة."""
    text = _DAGGER_AFTER_WY.sub("ا", text).replace(DAGGER, "ا")
    return _HAMZA_ALEF.sub("ا", text)


def has_uthmani(text: str) -> bool:
    return DAGGER in text or "ء" in text


_JOINED_VOCATIVE = re.compile(r"\bياا?يها\b")


def split_vocative(text: str) -> str:
    """نداء الرسم العثماني الموصول — بعد التطبيع — مفصولاً كالإملائي."""
    return _JOINED_VOCATIVE.sub("يا ايها", text)


def lexical(text: str) -> str:
    """تطبيع للبحث المعجمي: رسم فقط مع إبقاء التاء المربوطة كي لا تلتبس بهاء الضمير."""
    text = QURAN_MARKS.sub("", text)
    text = DIACRITICS.sub("", text)
    text = text.translate(LEXICAL)
    text = PUNCT.sub(" ", text)
    return SPACES.sub(" ", text).strip()


def lexical_tokens(text: str) -> list[str]:
    return lexical(text).split()


def light(text: str) -> str:
    text = QURAN_MARKS.sub("", text)
    text = DIACRITICS.sub("", text)
    return SPACES.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def strip_affixes(word: str) -> list[str]:
    """صور الكلمة بعد تقشير السوابق مرتبةً من الأقل تجريداً؛ الترتيب شرط صحة للمطابقة."""
    forms = {word}
    for p in PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= 3:
            forms.add(word[len(p) :])
    for base in list(forms):
        for s in SUFFIXES:
            if base.endswith(s) and len(base) - len(s) >= 3:
                stem = base[: -len(s)]
                forms.add(stem)
                if s in PRONOUNS and stem.endswith("ت"):
                    forms.add(stem[:-1] + "ة")
                if s in PRONOUNS and stem.endswith("ا"):
                    forms.add(stem[:-1] + "ي")
    return sorted(forms, key=lambda f: (-len(f), f))


def diacritic_density(text: str) -> float:
    letters = [c for c in text if "\u0600" <= c <= "\u06ff" and not DIACRITICS.match(c)]
    if not letters:
        return 0.0
    marks = len(DIACRITICS.findall(text))
    return marks / len(letters)
