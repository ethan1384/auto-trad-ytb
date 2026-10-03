FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
  && rm -rf /var/lib/apt/lists/*

COPY packages/shared /app/packages/shared
COPY services/api /app/services/api

RUN pip install --no-cache-dir -e /app/packages/shared \
  && pip install --no-cache-dir -r /app/services/api/requirements-docker.txt

WORKDIR /app/services/api
ENV PYTHONPATH=/app/services/api

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
