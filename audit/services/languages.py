"""اللغات التي تُكتب بالحرف العربي: لا تُحاسَب فيها الحروف العربية الدخيلة (قاعدة FRM-ARB).

اسم اللغة في البرومت يأتي من ``core.Language.name`` (الاسم بالعربية)، وهذا الجدول يحدّد
فقط علم ``arabic_script`` من رمز ISO.
"""

ARABIC_SCRIPT_LANGUAGES = {
    "ur",
    "fa",
    "prs",
    "ps",
    "ug",
    "sd",
    "ks",
    "ku",
    "kmr",
    "ba",
    "bh",
    "rhg",
    "uzb_arab",
}


def is_arabic_script(iso_code):
    return (iso_code or "").strip().lower() in ARABIC_SCRIPT_LANGUAGES
