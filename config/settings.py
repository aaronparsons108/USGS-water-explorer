"""Django settings for the USGS Site Explorer.

Defaults target local research use: SQLite, DEBUG on, localhost only. Every
security-relevant value reads from the environment first, so the same checkout
can be pointed at a real host without editing this file.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [v.strip() for v in raw.split(",") if v.strip()]


# --- Data locations ---------------------------------------------------------

# Committed summary CSVs: demo site metadata, fallback metrics, and the USGS
# parameter-code snapshot that keeps the picker working offline.
DATA_DIR = BASE_DIR / "data"

# Parsed daily-value caches (Parquet), rebuilt with: python manage.py build_cache
CACHE_DIR = Path(os.environ.get("NITRO_CACHE_DIR", BASE_DIR / ".cache"))

# Per-dataset storage: raw downloads plus the built daily tables. Gitignored.
DATASETS_STORE_DIR = Path(os.environ.get("NITRO_DATASETS_DIR", BASE_DIR / "datasets_store"))

# Root of the research checkout holding the raw sitedata/ used only to rebuild
# the demo cache. Without it the demo serves full-window values from the
# committed CSVs and says so in the explorer.
NITRO_DATA_ROOT = Path(
    os.environ.get("NITRO_DATA_ROOT", BASE_DIR.parent / "nitro-research")
)
SITEDATA_DIR = NITRO_DATA_ROOT / "sitedata"

# The study window. Any sub-window may be requested; dates outside it simply
# have no data behind them.
DATE_START = "2008-01-01"
DATE_END = "2026-02-26"

# --- Core -------------------------------------------------------------------

# Fine for local research use. Set DJANGO_SECRET_KEY before exposing this to a
# network, and turn DJANGO_DEBUG off with it.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-local-hydrology-development-key"
)
DEBUG = _env_flag("DJANGO_DEBUG", True)
# "testserver" is what django.test.Client sends, so smoke tests run against
# these settings without a separate configuration.
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "testserver"])

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "landing_page",
    "explorer",
    "datasets",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Background job threads and request threads share this file. A busy
        # timeout lets a writer wait for the lock instead of failing outright.
        "OPTIONS": {"timeout": 20},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
