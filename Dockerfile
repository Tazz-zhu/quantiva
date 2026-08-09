# Quantiva ?????????? - ????
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8686

# ?????0.0.0.0 + ?????????
CMD ["python", "scripts/webui.py", "--prod", "--port", "8686"]
