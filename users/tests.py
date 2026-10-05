from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from core.models import Language

User = get_user_model()


class UserManagerTests(TestCase):
    def test_create_user_saves_email_in_lowercase(self):
        user = User.objects.create_user("  User@Example.COM ", "pass-1234", full_name="أحمد")
        user.refresh_from_db()
        self.assertEqual(user.email, "user@example.com")
        self.assertTrue(user.check_password("pass-1234"))

    def test_create_user_rejects_empty_email(self):
        for empty in ("", None):
            with self.subTest(email=empty), self.assertRaises(ValueError):
                User.objects.create_user(empty, "pass-1234", full_name="أحمد")

    def test_create_user_is_not_staff_nor_superuser(self):
        user = User.objects.create_user("a@example.com", "pass-1234", full_name="أحمد")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_create_superuser_sets_flags(self):
        admin_user = User.objects.create_superuser("Admin@Example.com", "pass-1234", full_name="م")
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertEqual(admin_user.email, "admin@example.com")

    def test_create_superuser_rejects_non_staff(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser("x@example.com", "p", full_name="م", is_staff=False)
        with self.assertRaises(ValueError):
            User.objects.create_superuser("x@example.com", "p", full_name="م", is_superuser=False)

    def test_emails_differing_only_in_case_are_rejected(self):
        User.objects.create_user("same@example.com", "pass-1234", full_name="أ")
        with self.assertRaises(IntegrityError):
            User.objects.create_user("SAME@EXAMPLE.COM", "pass-1234", full_name="ب")

    def test_createsuperuser_command_works_with_email(self):
        call_command(
            "createsuperuser",
            interactive=False,
            email="Boss@Example.com",
            full_name="المشرف الأول",
            verbosity=0,
        )
        boss = User.objects.get(email="boss@example.com")
        self.assertTrue(boss.is_superuser)
        self.assertEqual(boss.full_name, "المشرف الأول")


class UserModelTests(TestCase):
    def test_clean_lowercases_email(self):
        user = User(email="Mixed@Case.Org", full_name="س")
        user.set_password("pass-1234")
        user.full_clean()
        self.assertEqual(user.email, "mixed@case.org")

    def test_full_clean_rejects_case_variant_of_existing_email(self):
        User.objects.create_user("taken@example.com", "pass-1234", full_name="أ")
        user = User(email="TAKEN@example.com", full_name="ب")
        user.set_password("pass-1234")
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_names(self):
        user = User(email="n@example.com", full_name="محمد أحمد")
        self.assertEqual(user.get_full_name(), "محمد أحمد")
        self.assertEqual(user.get_short_name(), "محمد")
        self.assertEqual(str(user), "n@example.com")

    def test_short_name_falls_back_to_email(self):
        self.assertEqual(
            User(email="n@example.com", full_name="").get_short_name(), "n@example.com"
        )

    def test_preferred_language_is_set_null_when_language_deleted(self):
        language = Language.objects.create(iso_code="tt", name="تجريبية", name_en="Test")
        user = User.objects.create_user(
            "l@example.com", "pass-1234", full_name="ل", preferred_language=language
        )
        language.delete()
        user.refresh_from_db()
        self.assertIsNone(user.preferred_language)

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertEqual(User.REQUIRED_FIELDS, ["full_name"])


class AdminTests(TestCase):
    def test_user_is_registered_in_admin(self):
        self.assertIn(User, admin.site._registry)

    def test_admin_requires_login_but_nothing_else_does(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/admin/login/"))

    def test_admin_is_arabic_and_rtl(self):
        boss = User.objects.create_superuser("boss@example.com", "pass-1234", full_name="م")
        self.client.force_login(boss)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="ar"')
        self.assertContains(response, 'dir="rtl"')

    def test_admin_user_pages_render(self):
        boss = User.objects.create_superuser("boss@example.com", "pass-1234", full_name="م")
        self.client.force_login(boss)
        for url in (
            "/admin/users/user/",
            "/admin/users/user/add/",
            f"/admin/users/user/{boss.pk}/change/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_add_user_lowercases_email(self):
        boss = User.objects.create_superuser("boss@example.com", "pass-1234", full_name="م")
        self.client.force_login(boss)
        response = self.client.post(
            "/admin/users/user/add/",
            {
                "email": "New@Example.com",
                "full_name": "جديد",
                "password1": "Strong-pass-9876",
                "password2": "Strong-pass-9876",
            },
        )
        self.assertEqual(response.status_code, 302, response.content[:500])
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
