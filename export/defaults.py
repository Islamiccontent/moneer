"""القيم الافتراضية لخيارات تنسيق التصدير بمفاتيح نموذج Format، بحسب اتجاه اللغة الهدف."""

RTL_DIR = "من اليمين إلى اليسار RTL"
LTR_DIR = "من اليسار إلى اليمين LTR"

ALIGNMENTS = ("اليمين", "اليسار", "التوسيط", "الضبط")
POSITIONS = ("الأسفل", "الأعلى")
COLORS = (
    "Black",
    "Red",
    "Blue",
    "Dark Blue",
    "Green",
    "Dark Green",
    "Brown",
    "Light Blue",
    "Light Gray",
)
HIGHLIGHTS = ("لا لون", *COLORS)
PAGE_SIZES = ("A3", "A4", "A5", "A6", "B4", "B5", "B6")
LINE_SPACING_RULES = ("Exactly", "Multiple")
FOOTNOTE_RESTART_RULES = ("إعادة ترقيم كل صفحة", "مستمر")
WEIGHTS = ("Regular", "Bold")
STYLES = ("Normal", "Italic")

ARABIC_FONT = "KFGQPC HAFS Uthmanic Script"
ARABIC_TITLE_FONT = "KFGQPC Uthman Taha Naskh"


def _font(prefix, font, size, weight="Regular", color="Black", style=None, rgb=("0", "0", "0")):
    block = {
        f"{prefix}_fonts": font,
        f"{prefix}_font_size": str(size),
        f"{prefix}_font_weight": weight,
        f"{prefix}_font_color": color,
        f"{prefix}_custom_color": color == "custom",
        f"{prefix}_font_r_rgb": rgb[0],
        f"{prefix}_font_g_rgb": rgb[1],
        f"{prefix}_font_b_rgb": rgb[2],
    }
    if style is not None:
        block[f"{prefix}_font_style"] = style
    if color == "custom":
        block[f"{prefix}_font_color"] = "Black"
    return block


def defaults_for(direction):
    """افتراضيات تنسيق كامل للغة باتجاه ``rtl`` أو ``ltr``."""
    rtl = direction == "rtl"
    text_font = "Traditional Arabic" if rtl else "Arial"
    start = "اليمين" if rtl else "اليسار"
    options = {
        # الصفحة
        "PageSizes": "A5",
        "page_custom_size": False,
        "pagesize_height": "",
        "pagesize_width": "",
        "right_page_margin": "2",
        "left_page_margin": "2",
        "top_page_margin": "2",
        "bottom_page_margin": "2",
        "main_text_dir": RTL_DIR if rtl else LTR_DIR,
        "columns_number": 1,
        "columns_between_spacing": "0",
        "include_index": True,
        "include_date_first_page": True,
        "include_untranslatable": True,
        "index_title": "",
        # الخلفية
        "background_custom_color": False,
        "background_r_rgb": "255",
        "background_g_rgb": "255",
        "background_b_rgb": "255",
        # الرأس والتذييل والترقيم
        "no_header_checkbox": False,
        "header_line_spacing": "1",
        "header_distance_up": "0.5",
        "footer_distance_down": "0.5",
        "add_header_title": False,
        "add_odd_even_header": False,
        "numbering_alignment": "التوسيط",
        "numbering_position": "الأسفل",
        **_font("numbering", text_font, 10),
        # العنوان بلغة الهدف والعنوان العربي
        **_font("title", text_font, 18, "Bold"),
        "title_line_spacing": "1",
        "title_alignment": "التوسيط",
        "title_uppercase": False,
        **_font("arabic_title", ARABIC_TITLE_FONT, 22, "Bold"),
        "arabic_title_spacing_before": "0",
        "arabic_title_spacing_after": "0",
        # الفهرس
        **_font("index", text_font, 10),
        "index_line_spacing_rule": "Exactly",
        "index_line_spacing": "12",
        "index_spacing_before": "0",
        "index_spacing_after": "0",
        # الفقرة
        **_font("paragraph", text_font, 11),
        "paragraph_line_spacing_rule": "Multiple",
        "paragraph_line_spacing": "1",
        "paragraph_alignment": "الضبط",
        "paragraph_spacing_before": "0",
        "paragraph_spacing_after": "6",
        "paragraph_first_line_indentation": "0",
        "paragraph_indentation_before": "0",
        "paragraph_indentation_after": "0",
        "paragraph_hanging_indentation": "0",
        "paragraph_word_wrap": False,
        # الحاشية
        "footnote_restart_rule": "إعادة ترقيم كل صفحة",
        **_font("footnote", text_font, 10, color="Dark Blue"),
        "footnote_number_font_color": "Dark Green",
        "footnote_number_custom_color": False,
        "footnote_number_font_r_rgb": "0",
        "footnote_number_font_g_rgb": "0",
        "footnote_number_font_b_rgb": "0",
        "footnote_alignment": start,
        "footnote_line_spacing_rule": "Exactly",
        "footnote_line_spacing": "12",
        "footnote_indentation_before": "0",
        "footnote_indentation_after": "0",
        "footnote_hanging_indentation": "0",
        # الآية وترجمتها
        **_font("aya", ARABIC_FONT, 12, color="Dark Green"),
        "aya_line_spacing_rule": "Multiple",
        "aya_line_spacing": "1",
        "aya_alignment": "الضبط",
        "aya_spacing_before": "0",
        "aya_spacing_after": "0",
        "aya_indentation_before": "0",
        "aya_indentation_after": "0",
        "aya_linespacing_split": False,
        "exclude_arabic_aya": False,
        "split_arabic_aya": False,
        **_font("trans_aya", text_font, 11, color="Blue", style="Italic"),
        # الحديث والأثر
        **_font("hadith", text_font, 11, style="Italic"),
        "hadith_line_spacing_rule": "Multiple",
        "hadith_line_spacing": "1",
        "include_arabic_hadith": False,
        **_font("arabic_hadith", ARABIC_FONT, 10, color="Green"),
        "arabic_hadith_alignment": "الضبط",
        "split_arabic_hadith": False,
        **_font("athar", text_font, 11, color="Brown", style="Italic"),
        "athar_line_spacing_rule": "Multiple",
        "athar_line_spacing": "1",
        # النقحرة
        "include_naqhara": False,
        **_font("naqhara", text_font, 12, color="custom", style="Normal", rgb=("24", "118", "0")),
        "naqhara_alignment": "الضبط",
        "naqhara_line_spacing_rule": "Exactly",
        "naqhara_line_spacing": "12",
        "include_arabic_naqhara": False,
        **_font("arabic_naqhara", ARABIC_FONT, 11, "Bold", color="custom", rgb=("24", "118", "0")),
        "arabic_naqhara_alignment": "الضبط",
        # النص العربي قبل ترجمة الفقرات والعناوين والآثار (التخطيط الثنائي المتتابع)
        "include_arabic_paragraph": False,
        **_font("arabic_paragraph", "Traditional Arabic", 12),
        "arabic_paragraph_alignment": "الضبط",
    }
    for level, size in ((1, 16), (2, 14), (3, 12)):
        options.update(_font(f"heading_{level}", text_font, size, "Bold", style="Normal"))
        options.update(
            {
                f"heading_{level}_line_spacing": "1",
                f"heading_{level}_alignment": start,
                f"heading_{level}_spacing_before": "12" if level == 1 else "6",
                f"heading_{level}_spacing_after": "6",
                f"heading_{level}_indentation_before": "0",
                f"heading_{level}_indentation_after": "0",
                f"heading_{level}_highlight_color": "لا لون",
            }
        )
    return options


OPTION_KEYS = frozenset(defaults_for("ltr"))
_BOOL_KEYS = frozenset(k for k, v in defaults_for("ltr").items() if isinstance(v, bool))


def validate_options(options):
    """يعيد قائمة أخطاء (فارغة إن صحّت): مفاتيح مجهولة، أو قيم منطقية بغير نوعها."""
    if not isinstance(options, dict):
        return ["الخيارات يجب أن تكون كائن JSON (قاموساً)."]
    errors = []
    unknown = sorted(set(options) - OPTION_KEYS)
    if unknown:
        errors.append(f"مفاتيح غير معروفة: {', '.join(unknown)}")
    for key in sorted(_BOOL_KEYS & set(options)):
        if not isinstance(options[key], bool):
            errors.append(f"{key} يجب أن يكون true أو false.")
    return errors
