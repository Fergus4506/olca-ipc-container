FROM python:3.11-slim
WORKDIR /app

# 安裝基礎套件並安裝 Python 依賴
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y build-essential gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 將 Flask app 複製進去（在 docker-compose 中可使用 volume 掛載以開發）
COPY my_flask1.py ./
# 設定環境變數
COPY .env ./

EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "my_flask1:app", "--workers", "1"]
