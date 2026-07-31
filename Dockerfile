FROM python:3.11-slim
WORKDIR /app
# wkhtmltopdf公式debパッケージを直接インストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-noto-cjk \
    poppler-utils \
    libheif1 \
    libssl3 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    && curl -L https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb -o /tmp/wkhtmltox.deb \
    && apt-get install -y /tmp/wkhtmltox.deb \
    && rm /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium(Playwright) 導入: サーバーPDF生成用
RUN python -m playwright install --with-deps chromium
COPY . .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "8", "--worker-class", "gthread", "--timeout", "180", "--limit-request-line", "8190", "app:app"]
