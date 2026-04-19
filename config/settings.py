"""
Django settings for Betala Inventory project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Bygger paths inne i prosjektet
BASE_DIR = Path(__file__).resolve().parent.parent

# Last miljøvariabler
load_dotenv(BASE_DIR / '.env')

# Sikkerhet
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# CSRF trusted origins for Cloudflare Tunnel
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if os.getenv('CSRF_TRUSTED_ORIGINS') else []

# Produksjonssikkerhet
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    # Third party
    'django_extensions',
    'django_filters',  # django-filter pakken
    'import_export',
    'crispy_forms',
    'crispy_bootstrap5',
    'rest_framework',
    'drf_spectacular',
    
    # Local apps
    'inventory.apps.InventoryConfig',
    'betala_sync.apps.BetalaSyncConfig',
    'reports.apps.ReportsConfig',
    
    # Scheduler
    'django_apscheduler',
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

# WhiteNoise for produksjon - legges til hvis installert
try:
    import whitenoise
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
except ImportError:
    pass

# Debug toolbar for utvikling
if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1']

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'betala_sync.context_processors.betala_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database - Bruker SQLite for rask lokal testing, bytt til PostgreSQL for produksjon
USE_SQLITE = os.getenv('USE_SQLITE', 'true').lower() == 'true'

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'festival_inventory'),
            'USER': os.getenv('DB_USER', 'inventory_user'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Login settings
LOGIN_URL = 'betala_sync:betala_login'
LOGIN_REDIRECT_URL = 'inventory:dashboard'
LOGOUT_REDIRECT_URL = 'betala_sync:betala_login'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'betala_sync': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'apscheduler': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}

# Internationalization
LANGUAGE_CODE = 'nb-no'
TIME_ZONE = 'Europe/Oslo'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# WhiteNoise for serving static files in production
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Crispy forms
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# DRF Spectacular (OpenAPI)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Betala Inventory API',
    'DESCRIPTION': 'API for lagerstyring med Betala POS',
    'VERSION': '1.0.0',
}

# Betala API
BETALA_API_URL = os.getenv('BETALA_API_URL', 'https://betalademo.betala.no')
BETALA_API_KEY = os.getenv('BETALA_API_KEY', 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJleHAiOjE3ODQ2MzU5NDcsIm5iZiI6MTc3NjM0MTU0NywiaWF0IjoxNzc2MzQxNTQ3LCJ1c2VyX2lkIjoxODY1Njk1MjM3LCJlbWFpbCI6Impvbi5zaWd1cmRhcnNvbkBhZHZhbmlhLm5vIiwiaXNfYWRtaW4iOmZhbHNlfQ.4hd6E3h2WZAmv57n6woUahGV1I8xHOCoXBnRv5Cgu50GqStR6e8K7JtrhNS_HE1vyvkPr01xu0X1OXW3CQ5oXw')
BETALA_ORGANIZATION_ID = os.getenv('BETALA_ORGANIZATION_ID', '2456907496')
BETALA_SALES_POINT_GROUP_ID = os.getenv('BETALA_SALES_POINT_GROUP_ID', '5414')

# Celery
CELERY_BROKER_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Login (bruker Betala login)
LOGIN_REDIRECT_URL = 'inventory:dashboard'
LOGOUT_REDIRECT_URL = 'betala_sync:betala_login'

# APScheduler
APSCHEDULER_DATETIME_FORMAT = "d.m.Y H:i:s"
APSCHEDULER_RUN_NOW_TIMEOUT = 25  # Sekunder
