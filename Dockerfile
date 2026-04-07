# 1. 動作の土台となるPython環境（軽量で高速なslim版）を指定
FROM python:3.11-slim

# 2. サーバー内の作業場所（フォルダ）を決定
WORKDIR /app

# 3. 必要なパッケージ一覧（requirements.txt）をコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 君の作ったTASUKARUのコードをすべてコピー
COPY . .

# 5. Google Cloud Runが通信に使う「8080番のドア」を開けておく
EXPOSE 8080

# 6. Streamlitを8080番ポートで起動するコマンド
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]