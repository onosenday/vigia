# vigia-bot — consultas por Telegram en el chat de las alertas (solo lectura)
FROM python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
RUN apk add --no-cache tzdata
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY *.py /app/vigia_bot/
WORKDIR /app
USER 65534:65534
CMD ["python3", "-m", "vigia_bot"]
