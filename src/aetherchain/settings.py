from pathlib import Path
import os
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- PRODUCTION SECURITY SETTINGS ---

# SECRET_KEY is now read from an environment variable.
# The gcloud deploy command will mount this from Secret Manager.
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

# DEBUG must be False in a production environment.
DEBUG = False

# For a backend service on Cloud Run, allowing all hosts is acceptable
# as it sits behind Google's trusted frontend.
ALLOWED_HOSTS = ["*"]
APPEND_SLASH = False


# --- APPLICATION DEFINITION ---

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
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


# --- DATABASE AND SERVICE CONFIGURATION (from Environment Variables) ---

# Read the Supabase PostgreSQL URI from the environment.
POSTGRES_URI = os.getenv('POSTGRES_URI', '')
DATABASES = {'default': dj_database_url.config(default=POSTGRES_URI, conn_max_age=600)}

# Read Neo4j credentials from the environment.
NEO4J_URI = os.getenv('NEO4J_URI', '7f3e44ae.databases.neo4j.io') # URI can be a default
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

from neomodel import config
if NEO4J_URI and NEO4J_PASSWORD:
    config.DATABASE_URL = f"neo4j+s://{NEO4J_USERNAME}:{NEO4J_PASSWORD}@{NEO4J_URI}"

# Read Google Cloud Project ID from the environment.
GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', 'aetherchain-v2')
