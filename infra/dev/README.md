# Local infrastructure notes

`docker compose up -d postgres redis s3 ollama` starts the durable dependencies. The worker rewrites lines with `qwen3.8:27b` on the host Ollama (`host.docker.internal:11434`), because a 0.5B model copies the literal Argos draft and misses greetings, farewells, and idioms. If that model is absent, the Argos line is kept. The compose Ollama service still pulls `qwen2.5:0.5b` and is not used for rewrite.

Default credentials (dev only):

- Postgres: `dubbing` / `dubbing` / db `dubbing`
- S3 (LocalStack): endpoint `http://localhost:4566`, keys `test` / `test`, bucket `dubbing`
- Redis: no password, port `6379`

Note: the official `minio/minio` image was not pullable in some environments, so LocalStack S3 is used for local object storage.

API and worker images install FFmpeg for later real media processing. V1 providers default to `PROVIDER_MODE=mock`.
