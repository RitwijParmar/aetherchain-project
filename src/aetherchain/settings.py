from pathlib import Path
import os
import importlib.util

import dj_database_url
from neomodel import config

BASE_DIR = Path(__file__).resolve().parent.parent

# --- PRODUCTION SECURITY SETTINGS ---
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-dev-insecure-key')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', '*').split(',') if host.strip()]
APPEND_SLASH = False

# --- APPLICATION DEFINITION ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'aetherchain.core',
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
if importlib.util.find_spec('whitenoise') is not None:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ROOT_URLCONF = 'aetherchain.urls'
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
    },
]
WSGI_APPLICATION = 'aetherchain.wsgi.application'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
if importlib.util.find_spec('whitenoise') is not None:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# --- DATABASE AND SERVICE CONFIGURATION ---
POSTGRES_URI = os.getenv('POSTGRES_URI', '')
DEFAULT_DB_URL = POSTGRES_URI or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {
    'default': dj_database_url.config(default=DEFAULT_DB_URL, conn_max_age=600),
}

NEO4J_URI = os.getenv('NEO4J_URI', '')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')

if NEO4J_URI and NEO4J_PASSWORD:
    config.DATABASE_URL = f"neo4j+s://{NEO4J_USERNAME}:{NEO4J_PASSWORD}@{NEO4J_URI}"

GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', '')
GCP_QUOTA_PROJECT_ID = os.getenv('GCP_QUOTA_PROJECT_ID', GCP_PROJECT_ID)
GCLOUD_BIN = os.getenv('GCLOUD_BIN', 'gcloud')
API_TOKEN = os.getenv('API_TOKEN')

# Vertex AI Search / Discovery Engine settings
VERTEX_SEARCH_SERVING_CONFIG = os.getenv('VERTEX_SEARCH_SERVING_CONFIG', '')
VERTEX_SEARCH_MAX_RESULTS = int(os.getenv('VERTEX_SEARCH_MAX_RESULTS', '8'))
VERTEX_SEARCH_ENABLE_SUMMARY = os.getenv('VERTEX_SEARCH_ENABLE_SUMMARY', 'true').lower() == 'true'
VERTEX_SEARCH_SUMMARY_RESULT_COUNT = int(os.getenv('VERTEX_SEARCH_SUMMARY_RESULT_COUNT', '3'))
CREDIT_FIRST_MODE = os.getenv('CREDIT_FIRST_MODE', 'true').lower() == 'true'
VERTEX_GENAI_MODEL = os.getenv('VERTEX_GENAI_MODEL', '')
VERTEX_GENAI_LOCATION = os.getenv('VERTEX_GENAI_LOCATION', 'us-central1')
VERTEX_GENAI_MAX_OUTPUT_TOKENS = int(os.getenv('VERTEX_GENAI_MAX_OUTPUT_TOKENS', '350'))
BILLING_EXPORT_SCAN_PROJECTS = os.getenv('BILLING_EXPORT_SCAN_PROJECTS', '')
ENABLE_GRAPH_FALLBACK = os.getenv('ENABLE_GRAPH_FALLBACK', 'true').lower() == 'true'

# Shared request controls
EXTERNAL_REQUEST_TIMEOUT_SECONDS = int(os.getenv('EXTERNAL_REQUEST_TIMEOUT_SECONDS', '20'))
