import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- nitro-research data locations -----------------------------------------
# Committed small summary CSVs (site metadata + offline fallback). Lives in-repo.
DATA_DIR = BASE_DIR / "data"

# Parsed daily-value caches (Parquet). Rebuilt with: python manage.py build_cache
CACHE_DIR = Path(os.environ.get("NITRO_CACHE_DIR", BASE_DIR / ".cache"))

# Root of the research1 repo that holds the raw 436 MB sitedata/ and
# pmcodesites/. Needed only to (re)build the cache and to recompute medians/MI
# over custom date ranges/seasons. Override with the NITRO_DATA_ROOT env var.
NITRO_DATA_ROOT = Path(
    os.environ.get("NITRO_DATA_ROOT", BASE_DIR.parent / "nitro-research")
)
SITEDATA_DIR = NITRO_DATA_ROOT / "sitedata"

# Study window used by research1 (heatmap_common). The date-range filter may
# request any sub-window of this; values outside are simply absent from data.
DATE_START = "2008-01-01"
DATE_END = "2026-02-26"

SECRET_KEY = 'django-insecure-temporary-key-for-local-hydrology-dev'
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'landing_page',
    'explorer',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    }
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
