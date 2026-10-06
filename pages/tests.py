import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .views import ASSETS_DIR, CLASSIFY_PAGE, DOCUMENTS_PAGE, HOME_FILE, ROOT_FILES, TRANSLATE_PAGE


class HomePageTests(SimpleTestCase):
    """الصفحة الرئيسية الحالية تبقى على / بلا أي تغيير، ولا تحتاج قاعدة بيانات ولا تسجيل دخول."""

    def test_home_returns_200_with_the_site_title(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>منصة مُنير</title>".encode(), response.getvalue())

    def test_home_is_html(self):
        response = self.client.get("/")
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

    def test_home_is_served_byte_for_byte(self):
        expected = (Path(settings.BASE_DIR) / HOME_FILE).read_bytes()
        response = self.client.get("/")
        self.assertEqual(response.getvalue(), expected)

    def test_home_rejects_unsafe_methods(self):
        self.assertEqual(self.client.post("/").status_code, 405)

    def test_index_html_is_not_exposed_at_its_own_path(self):
        self.assertEqual(self.client.get("/index.html").status_code, 404)


class AppPagesTests(SimpleTestCase):
    """صفحات التطبيقات تعيش في pages/html وتُخدم بايتاً بايت."""

    def bundle(self, url, path):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), path.read_bytes())

    def test_classify_page(self):
        self.bundle("/classify/", CLASSIFY_PAGE)

    def test_classify_document_permalink(self):
        self.bundle("/classify/documents/42/", CLASSIFY_PAGE)

    def test_translate_without_a_document_starts_at_upload(self):
        response = self.client.get("/translate/")
        self.assertRedirects(response, "/classify/", fetch_redirect_response=False)

    def test_documents_browse_page(self):
        self.bundle("/translate/documents/", DOCUMENTS_PAGE)

    def test_document_permalink_serves_the_translate_bundle(self):
        self.bundle("/translate/documents/42/", TRANSLATE_PAGE)

    def test_stage_permalinks_serve_the_translate_bundle(self):
        for stage in ("segments", "translation", "review", "export"):
            with self.subTest(stage=stage):
                self.bundle(f"/translate/documents/42/{stage}/", TRANSLATE_PAGE)


class AssetsTests(SimpleTestCase):
    """أصول الصفحات من pages/assets بنوعها الصحيح، وكل ما تشير إليه الصفحات موجود."""

    def test_assets_are_served_with_their_content_type(self):
        for path, content_type in (
            ("css/moneer.css", "text/css; charset=utf-8"),
            ("js/dc-runtime.js", "text/javascript; charset=utf-8"),
            ("fonts/thmanyah-text-400.woff2", "font/woff2"),
            ("img/moneer-logo.png", "image/png"),
            ("img/quranenc.svg", "image/svg+xml"),
        ):
            with self.subTest(path=path):
                response = self.client.get(f"/assets/{path}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], content_type)
                self.assertEqual(
                    b"".join(response.streaming_content), (ASSETS_DIR / path).read_bytes()
                )

    def test_fonts_and_images_are_cached_and_code_is_revalidated(self):
        self.assertIn(
            "max-age", self.client.get("/assets/fonts/thmanyah-text-400.woff2")["Cache-Control"]
        )
        self.assertEqual(self.client.get("/assets/css/moneer.css")["Cache-Control"], "no-cache")

    def test_unknown_types_missing_files_and_traversal_are_rejected(self):
        self.assertEqual(self.client.get("/assets/img/missing.png").status_code, 404)
        self.assertEqual(self.client.get("/assets/../views.py").status_code, 404)
        self.assertNotEqual(self.client.get("/assets/..%2Fviews.py").status_code, 200)
        self.assertEqual(self.client.get("/assets/css").status_code, 404)

    def test_every_asset_the_pages_reference_exists(self):
        pages = [
            Path(settings.BASE_DIR) / HOME_FILE,
            CLASSIFY_PAGE,
            TRANSLATE_PAGE,
            *ASSETS_DIR.glob("css/*.css"),
        ]
        for page in pages:
            text = page.read_text(encoding="utf-8")
            refs = re.findall(r"/assets/([\w./-]+)", text) + re.findall(
                r"url\([\"']?\.\./([\w./-]+)", text
            )
            self.assertTrue(refs, page)
            for ref in refs:
                with self.subTest(page=page.name, ref=ref):
                    self.assertTrue((ASSETS_DIR / ref).is_file())


class _TagBalance(HTMLParser):
    """يكدّس الوسوم المفتوحة؛ أي إغلاق لا يطابق آخر مفتوح يُسجَّل."""

    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.stack, self.mismatched = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            self.mismatched.append((tag, self.getpos()[0]))


class PageMarkupTests(SimpleTestCase):
    """قالب كل صفحة متوازن الوسوم: إغلاق ناقص أو زائد يُخرج ما بعده من حاويته فتبدو الصفحة مكسورة."""

    def test_page_templates_have_balanced_tags(self):
        for page in (Path(settings.BASE_DIR) / HOME_FILE, CLASSIFY_PAGE, TRANSLATE_PAGE):
            with self.subTest(page=page.name):
                html = page.read_text(encoding="utf-8")
                template = html[html.index("<x-dc>") : html.index("</x-dc>") + len("</x-dc>")]
                parser = _TagBalance()
                parser.feed(template)
                self.assertEqual(parser.mismatched, [], "إغلاق لا يطابق المفتوح (الوسم، السطر)")
                self.assertEqual(parser.stack, [], "وسوم بلا إغلاق (الوسم، السطر)")


class RootFilesTests(SimpleTestCase):
    def test_root_files_are_served_with_their_content_type(self):
        for name, content_type in ROOT_FILES.items():
            if name == HOME_FILE:
                continue
            with self.subTest(name=name):
                response = self.client.get(f"/{name}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], content_type)
                self.assertEqual(response.getvalue(), (Path(settings.BASE_DIR) / name).read_bytes())

    def test_unknown_root_file_is_404(self):
        self.assertEqual(self.client.get("/missing.png").status_code, 404)


class DocumentsPageTests(SimpleTestCase):
    """صفحة قائمة المستندات: تقرأ واجهة القائمة، وكل أصولها موجودة فعلاً في pages/assets."""

    def test_page_reads_the_documents_api(self):
        html = DOCUMENTS_PAGE.read_text(encoding="utf-8")
        self.assertIn("/api/translate/documents/", html)
        for stage in ("رفع الملف", "التقطيع الذكي", "المطابقة والترجمة", "المراجعة", "التصدير"):
            self.assertIn(stage, html)

    def test_referenced_static_assets_exist(self):
        import re

        html = DOCUMENTS_PAGE.read_text(encoding="utf-8")
        # /static/ لا يُخدم في الإنتاج؛ كل الأصول من /assets/
        self.assertNotIn("/static/", html)
        paths = set(re.findall(r"/assets/([\w./-]+\.\w+)", html))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((ASSETS_DIR / path).is_file(), path)
