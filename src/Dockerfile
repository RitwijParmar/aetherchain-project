FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the PORT environment variable that Cloud Run uses
ENV PORT 8080

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/
RUN python manage.py collectstatic --noinput

# This command starts a web server, which is required for Cloud Run services
# even if they only do background work.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 aetherchain.wsgi:application
