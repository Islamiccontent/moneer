"""ترجمة النصوص غير القرآنية بنموذج Gemini مع أمثلة من القاعدة المركزية؛ المصدر عربي دائماً."""

from django.conf import settings

from . import examples, llm

SOURCE_LANG = "Arabic"
TEMPERATURE = 1.0

PROMPT = """
You are an expert translator specializing in Islamic religious texts, particularly from {source_lang} to {target_lang}.

The following are carefully selected examples of similar translations. Study these examples closely as they demonstrate the preferred translation style, word choices, and handling of religious terminology:

{examples}

Instructions for translation:
1. First analyze the word choices and translation patterns in the above examples
2. When translating religious terms, strictly prefer the same translations used in the examples if they appear
3. Match the level of formality and scholarly tone shown in the examples
4. Maintain consistency with how the examples handle:
   - Religious honorifics and titles
   - Scriptural references
   - Cultural and theological concepts
   - Traditional expressions and invocations

Please translate the following {source_lang} text into {target_lang}, ensuring you:
- Preserve the religious and cultural context
- Avoid literal translations that don't capture the essence
- Use formal scholarly language
- Follow the patterns and word choices established in the examples above
- Maintain parallel structure with similar phrases from the examples

Text to translate:
"{input}"

Before providing the translation, verify that your word choices align with the examples where applicable.
IMPORTANT: Respond ONLY with the {target_lang} translation, without any additional text or explanations.
"""

TERMS_BLOCK = """
Unified terminology (authoritative glossary): every occurrence of the following Arabic terms MUST be rendered using the exact approved equivalent, spelled exactly as given:
{pairs}
"""


def build_prompt(text, target_lang, relevant, terms=None):
    prompt = PROMPT.format(
        source_lang=SOURCE_LANG,
        target_lang=target_lang,
        examples=examples.examples_block(relevant, SOURCE_LANG, target_lang),
        input=text,
    )
    if terms:
        pairs = "\n".join(f"- {ar} → {equivalent}" for ar, equivalent in terms)
        prompt = prompt.replace(
            "Text to translate:", TERMS_BLOCK.format(pairs=pairs) + "\nText to translate:"
        )
    return prompt


def translate_text(text, language, terms=None):
    relevant = examples.relevant_examples(language.iso_code, text, k=examples.EXAMPLES_K)
    prompt = build_prompt(text, language.name_en, relevant, terms=terms)
    result = llm.gemini_generate(
        prompt,
        model=settings.TRANSLATE_MODEL,
        api_key=settings.GEMINI_API_KEY,
        temperature=TEMPERATURE,
    )
    return llm.strip_quotes(result)
