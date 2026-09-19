FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The bot polls Telegram; it doesn't listen on a port, but a healthcheck-friendly
# default port is harmless. Railway/Render can still attach it.
EXPOSE 8080

CMD ["python", "-m", "app.main"]