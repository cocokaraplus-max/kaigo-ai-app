FROM python:3.11-slim
WORKDIR /app
# wkhtmltopdf公式debパッケージを直接インストール
#
# dockerfile-curl-retry-v1 : 落とし方について（2026-09-14 にデプロイが落ちた）
#   ログ: E: Invalid archive signature / Could not read meta data from
#         /tmp/wkhtmltox.deb。curl の転送量が全部ゼロだった。
#   GitHubからの取得が空振りし、中身の無いファイルが .deb として保存された。
#
#   ★-f を付ける
#       -L だけだと、404やエラーページが返っても curl は成功扱いになり、
#       それを .deb として保存してしまう。-f があれば curl 自身が失敗し、
#       どこで何が起きたかが分かる。
#   ★--retry を付ける
#       ネットの一瞬の不調で、デプロイ全体を落とさない。
#       ★本番のデプロイ中に起きると、その日は出せなくなる。
#   ★apt に渡す前に、大きさを確かめる
#       本物は約11MB。1MBに満たなければそこで止める。
#       -f をすり抜ける壊れ方が残っても、ここで捕まる。
#   ★URLと版は変えていない。直したのは【取り方】だけ。
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
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxcb1 \
    libxshmfence1 \
    && curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors \
         https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb -o /tmp/wkhtmltox.deb \
    && [ "$(stat -c%s /tmp/wkhtmltox.deb)" -gt 1000000 ] \
    && apt-get install -y /tmp/wkhtmltox.deb \
    && rm /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium(Playwright) 導入: サーバーPDF生成用
RUN python -m playwright install chromium
COPY . .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "8", "--worker-class", "gthread", "--timeout", "180", "--limit-request-line", "8190", "app:app"]
