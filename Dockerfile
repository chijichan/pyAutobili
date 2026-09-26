FROM python:3.12-slim

# curl_cffi 自带静态 libcurl，无需系统额外依赖；仅设置时区便于日志时间可读
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY bilibili/ ./bilibili/

# config.json 与 logs/ 由外部挂载，避免 Cookie 打进镜像
VOLUME ["/app/logs"]
CMD ["python", "main.py"]
