FROM python:3.11-slim
ENV PYTHONUNBUFFERED 1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ .
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "aetherchain.wsgi:application"]
