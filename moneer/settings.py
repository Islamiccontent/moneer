"""إعدادات Django لمشروع مُنير؛ كل ما يختلف بحسب البيئة أو يُعدّ سراً يُقرأ من .env."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env.local")
load_dotenv(BASE_DIR / ".env")


def env(key, default=None, *, required=False):
    value = os.environ.get(key, default)
    if required and not value:
        raise ImproperlyConfigured(f"المتغير {key} مطلوب. أضفه إلى .env (انظر .env.example).")
    return value


def env_bool(key, default=False):
    return str(env(key, str(default))).strip().lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


SECRET_KEY = env("SECRET_KEY", required=True)

DEBUG = env_bool("DEBUG", False)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_tasks_db",
    "core",
    "users",
    "content",
    "classify",
    "translate",
    "pages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "moneer.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "moneer.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", required=True),
        "USER": env("DB_USER", required=True),
        "PASSWORD": env("DB_PASSWORD", required=True),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "users.User"

LOGIN_URL = "/accounts/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"

TIME_ZONE = "Asia/Riyadh"

USE_I18N = True

USE_TZ = True

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

STATIC_URL = "static/"

STATICFILES_DIRS = [BASE_DIR / "static"]

STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ICADB_LANGUAGES_URL = env("ICADB_LANGUAGES_URL", "https://icadb.com/api/languages/list/")

ICADB_QURAN_URL = env("ICADB_QURAN_URL", "https://icadb.com/quran/api/quran/")

QURAN_KB_DIR = BASE_DIR / env("QURAN_KB_DIR", "imports/quran-kb")

GEMINI_API_KEY = env("GEMINI_API_KEY", "")
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
TRANSLATE_MODEL = env("TRANSLATE_MODEL", "gemini-3.1-pro-preview")
CENTRAL_DB_URL = env("CENTRAL_DB_URL", "https://icadb.com")
QURAN_EXTRACT_MODEL = env("QURAN_EXTRACT_MODEL", "gpt-5-nano")

TASKS = {
    "default": {
        "BACKEND": env("TASKS_BACKEND", "django.tasks.backends.immediate.ImmediateBackend"),
    }
}
