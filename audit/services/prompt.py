"""بناء برومت المراجعة والتصنيف.

يختلف عن برومت نظام translation-check في أمرين:
1. لا يكتفي بحكم (صحيح/خطأ) وملاحظة حرّة، بل يطلب **قائمة أخطاء مصنَّفة**
   لكل عنصر: رمز النوع، الخطورة، الحساسية الشرعية، طريقة الكشف، الثقة،
   الموضع، الشرح، المطلوب، التصحيح المقترح.
2. الفئة واسم النوع لا يُطلبان من النموذج — تُستنتج من الرمز محليًا
   (trreview.taxonomy) فيتوحّد الاسم في الإحصائيات ولا يُهدر التوكن.

كل مهمة تحفظ نسخة البرومت الفعلية (prompt_snapshot) فلا تتغيّر تحتها لو
تطوّر القالب لاحقًا.
"""

from .taxonomy import DETECTION_GUIDE, SEVERITY_GUIDE, taxonomy_table_text

PROMPT_VERSION = 1

# الاستبدال يدوي (لا str.format) لأن القالب يحوي أقواسًا حرفية (JSON و﴿﴾).
PROMPT_TEMPLATE = """أنت مراجع خبير للترجمة من العربية إلى {language}، متخصص في المحتوى الإسلامي (عقيدة، فقه، أذكار، سيرة، تفسير)، ومهمتك اكتشاف أخطاء الترجمة **وتصنيفها** تصنيفًا دقيقًا قابلًا للإحصاء.

سأعطيك عدة عناصر؛ لكل عنصر: id، ونص عربي أصلي، وترجمته إلى {language}، و«النوع المطلوب» (ترجمة معنى أو نقحرة)، وأحيانًا «تنبيهات آلية» رصدها فحص قاعديّ محلي وتحتاج منك تحقيقًا.

## المبادئ الحاكمة

1. **احكم بالمعنى**: قارن معنى الترجمة بمعنى الأصل جملةً جملة. المطلوب في «ترجمة معنى» أن ينقل النص المعنى كاملًا دون تحريف ولا زيادة ولا نقصان؛ والمطلوب في «نقحرة» أن يقرأ القارئ نطق العربي بحروف {language} لا معناه.
2. **صيغة «نقحرة + ترجمة» مقبولة**: في الأذكار والأدعية والآيات كثيرًا ما تأتي الترجمة نقحرةً يليها معنى النص بين قوسين () أو معقوفتين []. هذه الصيغة نفسها ليست خطأً؛ قيّم جزء المعنى بمعيار الترجمة، وجزء النقحرة بمعيار الاتساق الصوتي، ولا تسجّل TRM-TRL لمجرد وجود النقحرة معها.
3. **الاستثناءات المسموحة** (ليست أخطاء ولا تُكتب عنها ملاحظات): نقحرة أسماء الأعلام؛ المصطلحات الإسلامية المتعارف عليها بالنقحرة داخل الترجمة (Allah, Sunnah, Qur'an, Dhikr, Zakat, Hadith ونحوها) إن كانت متسقة؛ نقحرة أسماء السور؛ الرموز ﷺ ﷻ ﷲ ۝ وأقواس الآية ﴿ ﴾ وعلامتا الاقتباس « »؛ صيغة «صلى الله عليه وسلم» بحروفها؛ شكل علامة تحديد الآية أيًّا كان؛ غياب رقم الآية؛ الإيضاح التفسيري الموجز بين قوسين إن لم يغيّر المعنى؛ إعادة ترتيب الجمل داخل الفقرة إذا استقام المعنى وسلمت طبيعة اللغة.
{arabic_rule}
5. **لا تخترع أخطاء**: لا تسجّل تفضيلات أسلوبية شخصية خطأً، ولا تسجّل الخطأ نفسه تحت رمزَين. إن تردّدت بين رمزين فاختر الأدقّ وصفًا لطبيعة الخطأ (لا لسببه).
6. **الاتساق عبر العناصر**: يجوز لك استعمال بقية العناصر المعطاة في هذه المجموعة لرصد اختلاف ترجمة المصطلح نفسه أو نقحرة العَلَم نفسه (TRM-INC، TRM-NAM)، ولا تفترض ما هو خارجها.
7. **الحساسية الشرعية وسم مستقل**: إن كان الخطأ يمسّ عقيدةً أو حكمًا أو نصًّا شرعيًا أو اسمًا من أسماء الله أو نسبةَ قول للنبي ﷺ أو لعالم، فاجعل sharia_sensitive = true **مع إبقاء رمز النوع الأصلي** الذي يصف آلية الخطأ (مثلًا SEM-NEG مع sharia_sensitive=true بدل الاكتفاء بـSHR-AQD). استعمل رموز SHR-* حين تكون طبيعة الخطأ شرعية بذاتها (تخريج، حكم، رقم شرعي، مصطلح شرعي).
8. **النوع شيء والخطورة شيء آخر**: الجدول يذكر خطورة افتراضية لكل نوع، وأنت تحدّد الخطورة الفعلية لكل حالة — خطأ نحوي قد يقلب المعنى فيصير كبيرًا، وسقوط كلمة حشو قد يكون بسيطًا.
{extra_rules}
## جدول التصنيف (استعمل الرمز كما هو)
{taxonomy}

## درجات الخطورة
{severity_guide}

## طريقة الكشف
{detection_guide}

## التنبيهات الآلية
إن ورد مع العنصر سطر «تنبيهات آلية» فهو مؤشر اشتباه من فحص قاعدي (طول شاذ، ترجمة متكررة لنصوص مختلفة...). تحقّق منه دلاليًا: إن ثبت الخطأ فسجّله بنوعه الحقيقي (مثلًا SEM-OMI لسقوط محتوى) واكتب detection = "استدلالي"؛ وإن لم يثبت فلا تسجّل شيئًا عنه.

## العناصر
{items}

## صيغة الرد
أعِد ردك بصيغة JSON فقط دون أي نص قبلها أو بعدها: مصفوفة فيها عنصر واحد لكل id **بنفس الترتيب**، وعدد عناصرها {count} بالضبط، وكل id مرة واحدة:
[
  {
    "id": <رقم id كما هو>,
    "summary": "جملة واحدة موجزة بالعربية تلخّص حال الترجمة، أو "" إن كانت سليمة",
    "errors": [
      {
        "code": "رمز من الجدول مثل SEM-OMI (أو OTHER إن لم يناسبه شيء)",
        "severity": "حرج|كبير|متوسط|بسيط",
        "sharia_sensitive": true|false,
        "detection": "قطعي|استدلالي|مؤشر اشتباه",
        "confidence": <عدد صحيح 0-100 يعبّر عن ثقتك في وجود الخطأ>,
        "location": "الجزء المعني من الترجمة (اقتباس قصير) أو من الأصل إن كان سقوطًا",
        "explanation": "شرح المشكلة بالعربية في جملة أو جملتين",
        "required_action": "ما المطلوب فعله",
        "suggested_fix": "التصحيح المقترح بلغة {language} (نص الجزء المصحَّح فقط)"
      }
    ]
  }
]
قواعد الرد: الترجمة السليمة تُعاد بـ "errors": [] و "summary": "". رتّب أخطاء العنصر من الأخطر إلى الأخف، ولا تتجاوز 6 أخطاء للعنصر الواحد. لا تكتب أي حقل خارج المذكور."""


def _render(template, **values):
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def arabic_rule_text(language, arabic_script):
    if arabic_script:
        return (
            f"4. **الحروف العربية**: لغة {language} تُكتب أصلًا بحروف عربية، فوجودها طبيعي "
            "ولا يُعدّ خطأً؛ لا تسجّل FRM-ARB."
        )
    return (
        f"4. **الحروف العربية**: لغة {language} لا تُكتب بحروف عربية، فأي حرف عربي في الترجمة "
        "= FRM-ARB، عدا الرموز ﷺ ﷻ ﷲ ۝ وأقواس الآية ﴿ ﴾ وصيغة «صلى الله عليه وسلم» بحروفها "
        "(بتشكيل أو بدونه) — هذه وحدها مستثناة."
    )


def _kind_label(row_type):
    return "نقحرة" if row_type == "naqhara" else "ترجمة معنى"


def item_block(item, language):
    """كتلة عنصر واحد. ``item`` قاموس فيه id, source, target, row_type,
    hints (قائمة تنبيهات آلية اختيارية)."""
    lines = [
        f"--- عنصر id={item['id']} ---",
        f"النص العربي: «{item['source']}»",
        f"الترجمة ({language}): «{item['target']}»",
        f"النوع المطلوب: {_kind_label(item.get('row_type'))}",
    ]
    hints = item.get("hints") or []
    if hints:
        lines.append("تنبيهات آلية: " + " | ".join(hints))
    return "\n".join(lines)


def _guide_text(guide):
    return "\n".join(f"- **{name}**: {text}" for name, text in guide.items())


def build_prompt(items, language, arabic_script=False, extra_rules="", template=None):
    """يبني البرومت النهائي لمجموعة عناصر.

    ``extra_rules`` قواعد إضافية خاصة باللغة أو بالمشروع (اختياري) تُدرج
    بعد المبادئ الحاكمة؛ ``template`` قالب بديل (مثلًا prompt_snapshot
    لمهمة قديمة) وإلا استُخدم القالب الحالي."""
    blocks = "\n\n".join(item_block(item, language) for item in items)
    extra = ""
    if extra_rules and extra_rules.strip():
        extra = "\n## قواعد إضافية خاصة بهذه اللغة/المشروع\n" + extra_rules.strip() + "\n"
    return _render(
        template or PROMPT_TEMPLATE,
        language=language,
        arabic_rule=arabic_rule_text(language, arabic_script),
        extra_rules=extra,
        taxonomy=taxonomy_table_text(),
        severity_guide=_guide_text(SEVERITY_GUIDE),
        detection_guide=_guide_text(DETECTION_GUIDE),
        items=blocks,
        count=len(items),
    )


# مخطط JSON اختياري (Gemini responseSchema) — يُفعَّل بـ GEMINI_USE_SCHEMA=1.
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "required": ["id", "summary", "errors"],
        "properties": {
            "id": {"type": "INTEGER"},
            "summary": {"type": "STRING"},
            "errors": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "required": ["code", "severity", "explanation"],
                    "properties": {
                        "code": {"type": "STRING"},
                        "severity": {"type": "STRING"},
                        "sharia_sensitive": {"type": "BOOLEAN"},
                        "detection": {"type": "STRING"},
                        "confidence": {"type": "INTEGER"},
                        "location": {"type": "STRING"},
                        "explanation": {"type": "STRING"},
                        "required_action": {"type": "STRING"},
                        "suggested_fix": {"type": "STRING"},
                    },
                },
            },
        },
    },
}
