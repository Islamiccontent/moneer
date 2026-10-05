from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .views import CLASSIFY_PAGE, DOCUMENTS_PAGE, HOME_FILE, ROOT_FILES, TRANSLATE_PAGE


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

    def test_translate_page(self):
        self.bundle("/translate/", TRANSLATE_PAGE)

    def test_documents_browse_page(self):
        self.bundle("/translate/documents/", DOCUMENTS_PAGE)

    def test_document_permalink_serves_the_translate_bundle(self):
        self.bundle("/translate/documents/42/", TRANSLATE_PAGE)

    def test_stage_permalinks_serve_the_translate_bundle(self):
        for stage in ("segments", "translation", "review", "export"):
            with self.subTest(stage=stage):
                self.bundle(f"/translate/documents/42/{stage}/", TRANSLATE_PAGE)


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
