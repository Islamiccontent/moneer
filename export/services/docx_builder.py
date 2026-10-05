"""توليد ملف Word لترجمة مستند بـ Spire.Doc، بمنطق منقول من لوحة تنسيق الكتب ومكيَّف لصفوف مُنير."""

import re
from pathlib import Path

from django.conf import settings
from spire.doc import (
    BackgroundType,
    BreakType,
    BuiltinStyle,
    Color,
    Document,
    FieldType,
    FileFormat,
    FootnoteRestartRule,
    FootnoteType,
    HorizontalAlignment,
    LineSpacingRule,
    PageSize,
    ParagraphStyle,
    SizeF,
    TextDirection,
)
from spire.doc.common import License

if getattr(settings, "SPIRE_DOC_KEY", ""):
    License.SetLicenseKey(settings.SPIRE_DOC_KEY)

PAGE_SIZES = {
    "A3": PageSize.A3,
    "A4": PageSize.A4,
    "A5": PageSize.A5,
    "A6": PageSize.A6,
    "B4": PageSize.B4,
    "B5": PageSize.B5,
    "B6": PageSize.B6,
}
RULES = {"Exactly": LineSpacingRule.Exactly, "Multiple": LineSpacingRule.Multiple}
ALIGN = {
    "اليمين": HorizontalAlignment.Right,
    "اليسار": HorizontalAlignment.Left,
    "التوسيط": HorizontalAlignment.Center,
    "الضبط": HorizontalAlignment.Justify,
}
COLORS = {
    "Black": Color.get_Black,
    "Red": Color.get_Red,
    "Blue": Color.get_Blue,
    "Dark Blue": Color.get_DarkBlue,
    "Green": Color.get_Green,
    "Dark Green": Color.get_DarkGreen,
    "Brown": Color.get_Brown,
    "Light Blue": Color.get_LightBlue,
    "Light Gray": Color.get_LightGray,
}
RESTART = {
    "إعادة ترقيم كل صفحة": FootnoteRestartRule.RestartPage,
    "مستمر": FootnoteRestartRule.DoNotRestart,
}
MARKER = re.compile(r"\[\d+\]")
ARABIC_MARKER = re.compile(r"\[[۰-۹]+\]")
HEADINGS = {"h1": BuiltinStyle.Heading1, "h2": BuiltinStyle.Heading2, "h3": BuiltinStyle.Heading3}
HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3}


def cm(value):
    return float(value) * 28.35


def guillemets(text):
    text = (text or "").strip()
    if not text:
        return text
    return ("" if text.startswith("«") else "«") + text + ("" if text.endswith("»") else "»")


class TranslationDocxBuilder:
    """يبني مستند Word من صفوف الترجمة وخيارات التنسيق ثم يحفظه DOCX أو PDF."""

    def __init__(self, rows, *, arabic_title, prefs, book_tag=""):
        self.rows = rows
        self.title = arabic_title
        self.p = prefs
        self.book_tag = book_tag
        self.rtl = "RTL" in prefs["main_text_dir"]
        self.columns = int(prefs["columns_number"])
        self.stats = {"footnotes_placed": 0, "footnotes_missed": 0}
        self.document = Document()
        self.section = None
        self.paragraph = None  # الفقرة الجارية التي تُلحق بها الجمل المقسَّمة
        self.split_group = None
        self.consumed_markers = {}

    # ------------------------------------------------------------------ أدوات
    def color(self, prefix):
        if self.p[f"{prefix}_custom_color"]:
            return Color.FromArgb(
                1,
                int(self.p[f"{prefix}_font_r_rgb"]),
                int(self.p[f"{prefix}_font_g_rgb"]),
                int(self.p[f"{prefix}_font_b_rgb"]),
            )
        return COLORS[self.p[f"{prefix}_font_color"]]()

    def font(self, run, prefix, *, style=False, bidi=None):
        fmt = run.CharacterFormat
        fmt.FontName = self.p[f"{prefix}_fonts"]
        fmt.FontSize = float(self.p[f"{prefix}_font_size"])
        fmt.Bold = self.p[f"{prefix}_font_weight"] == "Bold"
        if style:
            fmt.Italic = self.p.get(f"{prefix}_font_style") == "Italic"
        fmt.TextColor = self.color(prefix)
        if self.rtl if bidi is None else bidi:
            fmt.Bidi = True
            fmt.FontNameBidi = self.p[f"{prefix}_fonts"]
            fmt.FontSizeBidi = float(self.p[f"{prefix}_font_size"])

    def align(self, paragraph, name, *, rtl=None):
        """المحاذاة بأسمائها العربية؛ في النص RTL تُعكس اليمين واليسار كما في الأصل."""
        rtl = self.rtl if rtl is None else rtl
        alignment = ALIGN[name]
        if rtl:
            paragraph.Format.IsBidi = True
            paragraph.Format.TextDirection = TextDirection.RightToLeft
            if name == "اليمين":
                alignment = HorizontalAlignment.Left
            elif name == "اليسار":
                alignment = HorizontalAlignment.Right
        paragraph.Format.HorizontalAlignment = alignment

    def spacing(self, paragraph, prefix):
        rule = self.p[f"{prefix}_line_spacing_rule"]
        value = self.p[f"{prefix}_line_spacing"]
        paragraph.Format.LineSpacingRule = RULES[rule]
        paragraph.Format.LineSpacing = (
            float(value) * 12 if rule == "Multiple" else int(float(value))
        )

    def multiple_spacing(self, paragraph, value):
        paragraph.Format.LineSpacingRule = LineSpacingRule.Multiple
        paragraph.Format.LineSpacing = float(value) * 12

    def box(self, paragraph, prefix, *, first_line=False, hanging=False):
        fmt = paragraph.Format
        if f"{prefix}_spacing_before" in self.p:
            fmt.BeforeSpacing = float(self.p[f"{prefix}_spacing_before"])
            fmt.AfterSpacing = float(self.p[f"{prefix}_spacing_after"])
        hang = self.p.get(f"{prefix}_hanging_indentation", "0") if hanging else "0"
        if first_line:
            fmt.SetFirstLineIndent(cm(self.p[f"{prefix}_first_line_indentation"]))
        if hanging and hang != "0":
            fmt.SetFirstLineIndent(-int(cm(hang)))
        if f"{prefix}_indentation_before" in self.p:
            fmt.SetLeftIndent(cm(self.p[f"{prefix}_indentation_before"]) + cm(hang))
            fmt.SetRightIndent(cm(self.p[f"{prefix}_indentation_after"]))

    def new_section(self, *, link_to_previous=True):
        section = self.document.AddSection()
        p = self.p
        if self.rtl:
            section.PageSetup.Bidi = True
        if self.columns > 1:
            section.PageSetup.EqualColumnWidth = True
            for _ in range(self.columns):
                section.AddColumn(150.0, cm(p["columns_between_spacing"]))  # العرض يُعاد حسابه
        section.FootnoteOptions.RestartRule = RESTART[p["footnote_restart_rule"]]
        if not link_to_previous:
            section.HeadersFooters.LinkToPrevious = False
        if p["page_custom_size"]:
            section.PageSetup.PageSize = SizeF(cm(p["pagesize_width"]), cm(p["pagesize_height"]))
        else:
            section.PageSetup.PageSize = PAGE_SIZES[p["PageSizes"]]()
        margins = section.PageSetup.Margins
        margins.Right = cm(p["right_page_margin"])
        margins.Left = cm(p["left_page_margin"])
        margins.Top = cm(p["top_page_margin"])
        margins.Bottom = cm(p["bottom_page_margin"])
        section.PageSetup.HeaderDistance = cm(p["header_distance_up"])
        section.PageSetup.FooterDistance = cm(p["footer_distance_down"])
        self.section = section
        return section

    def new_paragraph(self, prefix="paragraph", *, align=None, first_line=True, hanging=True):
        paragraph = self.section.AddParagraph()
        self.box(paragraph, prefix, first_line=first_line, hanging=hanging)
        self.align(paragraph, self.p[align or f"{prefix}_alignment"])
        if f"{prefix}_line_spacing_rule" in self.p:
            self.spacing(paragraph, prefix)
        paragraph.Format.WordWrap = not self.p["paragraph_word_wrap"]
        self.paragraph = paragraph
        return paragraph

    def append(self, text):
        """يلحق نصاً بالفقرة الجارية مع مسافة فاصلة إن لم تكن فارغة."""
        return self.paragraph.AppendText(text if not self.paragraph.Text else f" {text}")

    def arabic_paragraph(self, text, alignment=None, *, bold=False):
        """فقرة النص العربي قبل ترجمته في التخطيط الثنائي المتتابع (include_arabic_paragraph)."""
        paragraph = self.section.AddParagraph()
        run = paragraph.AppendText(text)
        self.box(paragraph, "paragraph")
        self.align(paragraph, alignment or self.p["arabic_paragraph_alignment"], rtl=True)
        self.spacing(paragraph, "paragraph")
        self.font(run, "arabic_paragraph", bidi=True)
        if bold:
            run.CharacterFormat.Bold = True
        self.paragraph = None
        return paragraph

    @staticmethod
    def is_prose(row):
        return row["type"] in ("paragraph", "listparagraph") and row["sub_type"] == "normal"

    def prose_run(self, index):
        """صفوف النثر المتتالية من ``index`` في المجموعة نفسها: يُكتب عربيها فقرةً واحدة."""
        group = self.rows[index]["split_group"]
        run = []
        for row in self.rows[index:]:
            if not self.is_prose(row) or row["split_group"] != group:
                break
            run.append(row)
        return run

    @staticmethod
    def first_paragraph(container):
        """فقرة للكتابة في رأس أو تذييل: الفارغة التي ينشئها Spire تلقائياً إن وُجدت، وإلا جديدة."""
        if container.Paragraphs.Count and not container.Paragraphs[0].Text:
            return container.Paragraphs[0]
        return container.AddParagraph()

    def page_number(self, container):
        paragraph = self.first_paragraph(container)
        run = paragraph.AppendField("Page Number", FieldType.FieldPage)
        self.font(run, "numbering", bidi=False)
        run.CharacterFormat.FontName = self.p["paragraph_fonts"]
        paragraph.Format.HorizontalAlignment = ALIGN[self.p["numbering_alignment"]]
        return paragraph

    # ------------------------------------------------------------------ البناء
    def build(self):
        self.background()
        language_title = self.title_page()
        self.headers_and_numbering(language_title)
        for index, row in enumerate(self.rows):
            handler = getattr(self, f"row_{row['type']}", None)
            if handler:
                handler(index, row)
        self.strip_markers()
        if self.p["include_index"]:
            self.index()
        self.tag_line()
        return self.document

    def background(self):
        p = self.p
        if not p["background_custom_color"]:
            return
        rgb = (int(p["background_r_rgb"]), int(p["background_g_rgb"]), int(p["background_b_rgb"]))
        if rgb != (255, 255, 255):
            self.document.Background.Type = BackgroundType.Color
            self.document.Background.Color = Color.FromArgb(1, *rgb)

    def title_page(self):
        """صفحة العنوان: العنوان العربي ثم العنوان بلغة الهدف إن كانت أول جملة عنواناً."""
        p = self.p
        section = self.new_section()
        for _ in range(7):
            section.AddParagraph()
        paragraph = section.AddParagraph()
        self.multiple_spacing(paragraph, p["title_line_spacing"])
        run = paragraph.AppendText(self.title)
        self.font(run, "arabic_title", bidi=True)
        self.align(paragraph, p["title_alignment"])
        paragraph.Format.BeforeSpacing = float(p["arabic_title_spacing_before"])
        paragraph.Format.AfterSpacing = float(p["arabic_title_spacing_after"])

        language_title = ""
        if self.rows and self.rows[0]["type"] == "title":
            language_title = self.rows[0]["translation"]
            paragraph = section.AddParagraph()
            self.multiple_spacing(paragraph, p["title_line_spacing"])
            text = language_title.upper() if p["title_uppercase"] else language_title
            run = paragraph.AppendText(text)
            self.font(run, "title")
            self.align(paragraph, p["title_alignment"])

        breaker = section.AddParagraph()
        if self.columns > 1:
            breaker.AppendBreak(BreakType.ColumnBreak)
        else:
            breaker.AppendBreak(BreakType.PageBreak)
            self.new_section(link_to_previous=False)
        return language_title

    def headers_and_numbering(self, language_title):
        p, section = self.p, self.section
        if not p["no_header_checkbox"]:
            if not p["add_odd_even_header"]:
                if p["add_header_title"] and language_title:
                    self.first_paragraph(section.HeadersFooters.Header).AppendText(language_title)
            else:
                section.PageSetup.DifferentOddAndEvenPagesHeaderFooter = True
        footer = p["numbering_position"] == "الأسفل"
        if not p["add_odd_even_header"]:
            container = section.HeadersFooters.Footer if footer else section.HeadersFooters.Header
            self.page_number(container)
        else:
            hf = section.HeadersFooters
            for container in (
                (hf.OddFooter, hf.EvenFooter) if footer else (hf.OddHeader, hf.EvenHeader)
            ):
                self.page_number(container)

    # ------------------------------------------------------------------ الصفوف
    def row_title(self, index, row):
        p = self.p
        level = HEADING_LEVEL[row["tag"]]
        prefix = f"heading_{level}"
        if p["include_arabic_paragraph"]:
            self.arabic_paragraph(row["original_text"], p[f"{prefix}_alignment"], bold=True)
        paragraph = self.section.AddParagraph()
        run = paragraph.AppendText(row["translation"])
        paragraph.ApplyStyle(HEADINGS[row["tag"]])
        self.box(paragraph, prefix)
        self.align(paragraph, p[f"{prefix}_alignment"])
        self.font(run, prefix, style=True)
        if p[f"{prefix}_highlight_color"] != "لا لون":
            run.CharacterFormat.HighlightColor = COLORS[p[f"{prefix}_highlight_color"]]()
        self.multiple_spacing(paragraph, p[f"{prefix}_line_spacing"])
        self.paragraph = None

    def row_listparagraph(self, index, row):
        self.row_paragraph(index, row)

    def row_paragraph(self, index, row):
        sub = row["sub_type"]
        if sub == "aya":
            return self.row_aya(index, row)
        if sub == "hadith":
            return self.row_hadith(index, row)
        if sub == "athar":
            return self.row_athar(index, row)
        previous = self.rows[index - 1] if index else None
        opens_run = (
            previous is None
            or not self.is_prose(previous)
            or previous["split_group"] != row["split_group"]
            or self.paragraph is None
        )
        if self.p["include_arabic_paragraph"] and opens_run:
            self.arabic_paragraph(" ".join(r["original_text"] for r in self.prose_run(index)))
            self.split_group = row["split_group"]
            self.new_paragraph()
        elif (
            row["splitted"] == 0 or row["split_group"] != self.split_group or self.paragraph is None
        ):
            self.split_group = row["split_group"]
            self.new_paragraph()
        run = self.append(row["translation"])
        self.font(run, "paragraph")

    def row_aya(self, index, row):
        p = self.p
        previous = self.rows[index - 1] if index else None
        if previous is None or previous["sub_type"] != "aya":
            # أول آية في سلسلتها: فقرة جديدة إن بدأت فقرة، ثم النص العربي للآيات المتتابعة كلها
            new = (
                row["splitted"] == 0
                or row["split_group"] != self.split_group
                or self.paragraph is None
            )
            if not p["exclude_arabic_aya"]:
                if p["split_arabic_aya"]:
                    target = self.section.AddParagraph()
                    self.box(target, "aya")
                    self.align(target, p["aya_alignment"], rtl=True)
                else:
                    if new:
                        self.new_paragraph()
                        new = False
                    target = self.paragraph
                for later in self.rows[index:]:
                    if later["sub_type"] != "aya":
                        break
                    text = later["original_text"]
                    if not self.rtl and not p["split_arabic_aya"]:
                        text = text.replace("﴿", "(").replace("﴾", ")")
                    run = target.AppendText(text if not target.Text else f" {text}")
                    self.font(run, "aya", bidi=True)
                if p["aya_linespacing_split"]:
                    self.spacing(target, "aya" if p["split_arabic_aya"] else "paragraph")
                if p["split_arabic_aya"]:
                    new = True
            if new:
                self.new_paragraph()
        run = self.append(row["translation"])
        self.font(run, "trans_aya", style=True)
        self.align(self.paragraph, p["paragraph_alignment"])
        if p["aya_linespacing_split"]:
            self.spacing(self.paragraph, "aya")
        self.split_group = row["split_group"]

    def row_hadith(self, index, row):
        p = self.p
        new = (
            row["splitted"] == 0 or row["split_group"] != self.split_group or self.paragraph is None
        )
        if new:
            self.split_group = row["split_group"]
            self.new_paragraph()
            self.spacing(self.paragraph, "hadith")
        if p["include_arabic_hadith"]:
            if p["split_arabic_hadith"]:
                arabic = self.section.AddParagraph() if not new else self.paragraph
                arabic_run = arabic.AppendText(row["original_text"])
                self.box(arabic, "aya")
                self.align(arabic, p["arabic_hadith_alignment"], rtl=True)
                self.spacing(arabic, "aya")
                self.new_paragraph()
                self.spacing(self.paragraph, "hadith")
            else:
                arabic_run = self.append(row["original_text"])
            self.font(arabic_run, "arabic_hadith", bidi=True)
        run = self.append(row["translation"])
        self.font(run, "hadith", style=True)
        self.align(self.paragraph, p["paragraph_alignment"])

    def row_athar(self, index, row):
        p = self.p
        if p["include_arabic_paragraph"]:
            self.arabic_paragraph(row["original_text"])
            self.new_paragraph()
            self.spacing(self.paragraph, "athar")
            self.split_group = row["split_group"]
        elif self.paragraph is None or row["split_group"] != self.split_group:
            self.new_paragraph()
            self.spacing(self.paragraph, "athar")
            self.split_group = row["split_group"]
        run = self.append(row["translation"])
        self.font(run, "athar", style=True)
        self.align(self.paragraph, p["paragraph_alignment"])

    def row_naqhara(self, index, row):
        p = self.p
        if not p["include_naqhara"]:
            return
        if p["include_arabic_naqhara"]:
            arabic = self.section.AddParagraph()
            arabic_run = arabic.AppendText(guillemets(row["original_text"]))
            self.box(arabic, "aya")
            self.align(arabic, p["arabic_naqhara_alignment"], rtl=True)
            self.spacing(arabic, "aya")
            self.font(arabic_run, "arabic_naqhara", bidi=True)
        paragraph = self.section.AddParagraph()
        run = paragraph.AppendText(row["translation"])
        self.font(run, "naqhara", style=True)
        self.spacing(paragraph, "naqhara")
        self.align(paragraph, p["naqhara_alignment"])
        paragraph.Format.WordWrap = not p["paragraph_word_wrap"]
        self.paragraph = None
        self.split_group = None

    def row_footnote(self, index, row):
        """يعلّق الحاشية عند علامة ``[n]`` في أقرب جملة مضيفة سابقة لم تُستهلك علاماتها بعد."""
        for host in self.rows[:index]:
            if host["type"] == "footnote":
                continue
            markers = MARKER.findall(host["original_text"])
            used = self.consumed_markers.get(host["id"], 0)
            if not markers or used >= len(markers):
                continue
            marker = markers[used]
            self.consumed_markers[host["id"]] = used + 1
            anchor = self.find_anchor(host["translation"], marker)
            if anchor is None:
                self.stats["footnotes_missed"] += 1
                return
            paragraph, text_range = anchor
            footnote = paragraph.AppendFootnote(FootnoteType.Footnote)
            paragraph.ChildObjects.Insert(paragraph.ChildObjects.IndexOf(text_range) + 1, footnote)
            note = re.sub(r"^\{\d+\}\s*", "", row["translation"])
            note = re.sub(r"^\(\d+\)\s*", "", note)
            note = re.sub(r"^\[\d+\]\s*", "", note)
            self.style_footnote(footnote, note)
            self.stats["footnotes_placed"] += 1
            return
        self.stats["footnotes_missed"] += 1

    def find_anchor(self, translation, marker):
        """(الفقرة، النطاق) لآخر ظهور للعلامة في المستند حتى الآن، وإلا لنص الجملة كله."""
        if marker in translation:
            found = self.document.FindAllString(marker, False, True)
            selection = found[-1] if found else None
        else:
            selection = self.document.FindString(translation, False, True)
        if selection is None:
            return None
        text_range = selection.GetAsOneRange()
        return text_range.OwnerParagraph, text_range

    def style_footnote(self, footnote, note):
        p = self.p
        paragraph = footnote.TextBody.AddParagraph()
        run = paragraph.AppendText(note)
        self.font(run, "footnote")
        marker = footnote.MarkerCharacterFormat
        marker.FontName = p["footnote_fonts"]
        marker.FontSize = float(p["footnote_font_size"])
        marker.Bold = p["footnote_font_weight"] == "Bold"
        marker.TextColor = (
            self.color("footnote_number")
            if p["footnote_number_custom_color"]
            else (COLORS[p["footnote_number_font_color"]]())
        )
        self.spacing(paragraph, "footnote")
        self.box(paragraph, "footnote", hanging=True)
        paragraph.Format.WordWrap = not p["paragraph_word_wrap"]
        self.align(paragraph, p["footnote_alignment"])
        if self.rtl:
            marker.FontNameBidi = p["footnote_fonts"]
            marker.FontSizeBidi = float(p["footnote_font_size"])

    # ------------------------------------------------------------------ الختام
    def strip_markers(self):
        """حذف علامات الحواشي ``[n]`` من النص بعد تعليق الحواشي، كما في الأصل."""
        seen = set()
        for row in self.rows:
            for marker in MARKER.findall(row["translation"]) + ARABIC_MARKER.findall(
                row["translation"]
            ):
                if marker in seen:
                    continue
                seen.add(marker)
                for variant in (f"  {marker}", f" {marker}", marker):
                    self.document.Replace(variant, "", False, True)
        self.document.Replace("()", "", False, True)

    def index(self):
        p = self.p
        section = self.new_section(link_to_previous=False)
        title = p["index_title"] or "الفهرس"
        toc_paragraph = section.AddParagraph()
        toc_text = toc_paragraph.AppendText(f"{title}\r\n")
        toc_text.CharacterFormat.Bold = True
        toc_paragraph.Format.HorizontalAlignment = HorizontalAlignment.Center
        toc_paragraph.AppendTOC(1, 3)
        self.document.UpdateTableOfContents()
        style = ParagraphStyle(self.document)
        style.Name = "IndexStyle"
        style.CharacterFormat.FontName = p["index_fonts"]
        style.CharacterFormat.FontSize = float(p["index_font_size"])
        style.CharacterFormat.Bold = p["index_font_weight"] == "Bold"
        style.CharacterFormat.TextColor = self.color("index")
        self.document.Styles.Add(style)
        for i in range(1, section.Paragraphs.Count):
            paragraph = section.Paragraphs[i]
            paragraph.ApplyStyle(style.Name)
            if self.rtl:
                toc_text.CharacterFormat.Bidi = True
                paragraph.Format.IsBidi = True
                paragraph.Format.TextDirection = TextDirection.RightToLeft
            paragraph.Format.HorizontalAlignment = ALIGN[p["paragraph_alignment"]]
            paragraph.Format.BeforeSpacing = float(p["index_spacing_before"])
            paragraph.Format.AfterSpacing = float(p["index_spacing_after"])
            self.spacing(paragraph, "index")

    def tag_line(self):
        if not self.book_tag:
            return
        paragraph = self.section.AddParagraph()
        run = paragraph.AppendText(self.book_tag)
        run.CharacterFormat.FontSize = 7
        run.CharacterFormat.FontSizeBidi = 7
        run.CharacterFormat.FontNameBidi = "Times New Roman"
        paragraph.Format.HorizontalAlignment = HorizontalAlignment.Right

    def save(self, path, kind="docx"):
        path = Path(path)
        fmt = FileFormat.PDF if kind == "pdf" else FileFormat.Docx2016
        self.document.SaveToFile(str(path), fmt)
        self.document.Close()
        return path
