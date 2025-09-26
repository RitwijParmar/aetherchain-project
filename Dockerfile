FROM python:3.11-slim
ENV PYTHONUNBUFFERED 1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ .
# This is the correct command to run a Django app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "aetherchain.wsgi:application"]
