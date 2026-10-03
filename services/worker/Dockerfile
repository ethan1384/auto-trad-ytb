FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl fonts-dejavu-core espeak-ng libsndfile1 \
    git ca-certificates libglib2.0-0 libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY packages/shared /app/packages/shared
COPY services/api /app/services/api
COPY services/worker /app/services/worker

ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

RUN pip install --no-cache-dir -e /app/packages/shared \
  && pip install --no-cache-dir -r /app/services/api/requirements-docker.txt \
  && pip install --no-cache-dir -r /app/services/worker/requirements.txt \
  && pip install --no-cache-dir --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app/services/api
ENV PYTHONPATH=/app/services/api

CMD ["celery", "-A", "app.celery_app.celery", "worker", "--loglevel=INFO", "--concurrency=1"]
