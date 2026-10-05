"""تحويل جمل ترجمة المستند إلى صفوف بالشكل الذي يقرؤه مولّد Word (type وtag وsub_type وsplitted)."""

HEADING_TAGS = {
    "heading1": "h1",
    "heading2": "h2",
    "heading3": "h3",
    "heading4": "h3",
    "heading5": "h3",
}
SUB_TYPES = {"ayah": "aya", "hadith": "hadith", "athar": "athar"}


def row_type(phrase):
    if phrase.tag in HEADING_TAGS:
        return "title"
    if phrase.tag == "footnote":
        return "footnote"
    if phrase.text_type == "naqhara":
        return "naqhara"
    if phrase.tag == "listparagraph":
        return "listparagraph"
    return "paragraph"


def build_rows(document_translation, *, include_untranslatable=True):
    """``(rows, missing)``: الصفوف بترتيب المستند، ومعرّفات الجمل القابلة للترجمة بلا ترجمة."""
    language = document_translation.target_language
    translations = {
        row.phrase_id: row.translation.strip()
        for row in document_translation.phrases.all()
        if row.translation.strip()
    }
    rows, missing, previous_group = [], [], None
    phrases = document_translation.document.phrases.select_related("content_type").order_by(
        "group_id", "group_order"
    )
    for phrase in phrases:
        text = translations.get(phrase.pk)
        if text is None:
            if phrase.translatable:
                missing.append(phrase.pk)
                continue
            if not include_untranslatable:
                continue
            text = phrase.text
        rows.append(
            {
                "id": phrase.pk,
                "type": row_type(phrase),
                "tag": HEADING_TAGS.get(phrase.tag, "p"),
                "sub_type": SUB_TYPES.get(phrase.content_type.code, "normal"),
                "splitted": 0 if phrase.group_id != previous_group else 1,
                "split_group": phrase.group_id,
                "translation": text,
                "original_text": phrase.text,
                "align": phrase.align,
                "direction": language.direction,
            }
        )
        previous_group = phrase.group_id
    return rows, missing
