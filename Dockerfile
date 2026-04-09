# ==========================================
# TASUKARU - 市販モデル用 Dockerfile
# ==========================================

# 1. Python 3.11 軽量版を使用
FROM python:3.11-slim

# 2. 作業ディレクトリを設定
WORKDIR /app

# 3. システムの依存パッケージをインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 4. Pythonパッケージをインストール
#    （コードより先にコピーするとキャッシュが効いて速くなる）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. アプリのコードをコピー
COPY . .

# 6. Cloud Runが使う8080番ポートを開放
EXPOSE 8080

# 7. ヘルスチェック設定
#    Cloud Runがアプリの動作確認に使う
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/_stcore/health || exit 1

# 8. Streamlit起動コマンド
#    ・headlessモードで起動（ブラウザを開かない）
#    ・CORSを無効化（Cloud Run環境で必要）
#    ・XSRFを無効化（API連携で必要）
CMD ["streamlit", "run", "app.py", \
    "--server.port=8080", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false"]