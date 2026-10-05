"""استخلاص ترجمة جملة الآية من الترجمة المعتمدة بنموذج لغوي مع رقم الآية بلغة الهدف."""

from django.conf import settings

from translate.models import QuranAyahTranslation

from . import examples, llm

SOURCE_LANG = "Arabic"
MAX_EXAMPLES = 3

PROMPT = """You are a specialized translator of Islamic texts, tasked with translating from {source_lang} to {target_lang}.

Below are carefully selected, reliable examples of translations that have translation for text wanted to be translated. Study them thoroughly and extract the translation of required arabic text:

{examples}

Translation Instructions:
1. Pay close attention to word choices and phrasing as shown in the examples.
2. Use the same religious terms that appear in the examples if they occur in the text to be translated, preserving the same expressions and formulations without modification.
3. Maintain the level of formality and scholarly tone found in the examples.
4. Ensure consistent translation of titles, invocations, and Islamic concepts in accordance with the examples.
5. Avoid literal translations that compromise the spirit or intended meaning of the text; remain mindful of cultural and religious context.

Text to translate from {source_lang} to {target_lang}:
"{input}"

Important:
- Provide the {target_lang} translation only, without any explanations or additional commentary.
- Verify that any terms and expressions appearing in the examples are used as-is wherever they appear in the input text.
"""


def approved_row(match, key):
    """ترجمة الآية المطابقة بالمفتاح، أو None."""
    return QuranAyahTranslation.objects.filter(translation_key=key, ayah=match.ayah).first()


def build_prompt(text, match, row, target_lang):
    relevant = [{"source_text": match.ayah.text_imlaei, "target_text": row.text}][:MAX_EXAMPLES]
    return PROMPT.format(
        source_lang=SOURCE_LANG,
        target_lang=target_lang,
        examples=examples.examples_block(relevant, SOURCE_LANG, target_lang),
        input=text,
    )


def translate_ayah(text, match, key):
    """(الترجمة، الطريقة) أو None إن غابت الترجمة المعتمدة للآية."""
    row = approved_row(match, key)
    if row is None:
        return None
    prompt = build_prompt(text, match, row, key.language.name_en)
    result = llm.openai_generate(
        prompt, model=settings.QURAN_EXTRACT_MODEL, api_key=settings.OPENAI_API_KEY
    )
    return llm.strip_quotes(result), "quran_extract"
