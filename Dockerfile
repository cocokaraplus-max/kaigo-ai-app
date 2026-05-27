FROM python:3.11-slim
WORKDIR /app
# wkhtmltopdf + 日本語フォント
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    fonts-noto-cjk \
    xvfb \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]
