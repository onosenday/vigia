# vigia-bot — consultas por Telegram en el chat de las alertas (solo lectura)
FROM python:3.12-alpine3.24@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8
RUN apk add --no-cache tzdata
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY *.py /app/vigia_bot/
WORKDIR /app
USER 65534:65534
CMD ["python3", "-m", "vigia_bot"]
