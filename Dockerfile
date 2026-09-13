FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.lock ./
RUN pip install -r requirements.lock \
    && useradd --uid 10001 --create-home appuser
COPY app.py worker.py serve.py ./
COPY static ./static
RUN mkdir -p /app/.runtime/jobs && chown -R appuser:appuser /app/.runtime
USER appuser
EXPOSE 10000
CMD ["python", "serve.py"]
