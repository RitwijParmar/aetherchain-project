from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'django-insecure-placeholder-key-for-now'
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','aetherchain.core',]
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware',]
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

POSTGRES_URI = os.getenv('POSTGRES_URI', '')
NEO4J_URI = os.getenv('NEO4J_URI', '')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')
HF_TOKEN = os.getenv('HF_TOKEN')

DATABASES = {'default': dj_database_url.config(default=POSTGRES_URI, conn_max_age=600)}

from neomodel import config
if NEO4J_URI and NEO4J_PASSWORD:
    config.DATABASE_URL = f"neo4j+s://{NEO4J_USERNAME}:{NEO4J_PASSWORD}@{NEO4J_URI}"

GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', '')
