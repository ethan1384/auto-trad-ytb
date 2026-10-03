# Progress log

## 2026-10-02 — Pipeline performance baseline

### Done
- `scripts/bench_pipeline.py` runs the real `PipelineRunner` in local mode on a clip, with SQLite and a directory in place of S3. Jobs run back to back in one process like the Celery worker. Each job reports stage times, ffmpeg / Ollama / SQL counters, a cProfile dump, and output fingerprints. `--compare` checks two runs.
- With a fixed seed, every output (transcript, script, cloned voice, final MP4) is byte-identical from one job to the next, so an optimization can be checked bit for bit.
- Warm job on a 59 s clip (M5 Pro, OmniVoice on MPS): 173 s. Synthesize 104 s, rewrite 45 s (21 sequential Ollama calls), transcribe 17 s, render 5 s.
- `scripts/bench_transcribe_threads.py`: Whisper at 8 threads and diarization at 4–8 threads give the same words and turns as today, 30–40 % faster.
- No application code changed yet.

## 2026-09-29 — Interruptions stay two speeches

### Done
- When one person cuts in before the other has finished, the shared line was given entirely to whoever occupied more of it. The other person's words were dubbed in the first voice.
- A line that contains two real stretches is now cut at the overlap, on the word boundary. Each side keeps its own speaker, its own text, and its own clone. A blip shorter than about a third of a second stays on the line.

## 2026-09-29 — Dialogue speaker turns

### Done
- A real conversation was split into five voices. Each line was embedded with the previous 4.5 seconds, which contained the other person, and a short question was glued to the answer before it.
- Speaker labels now come from sherpa-onnx diarization: pyannote segmentation finds the turns, a 3D-Speaker embedding clusters them, and each transcript line takes the turn that covers it. A short blip inside someone else's turn is not a new voice.
- The threshold is 0.93, tuned on the mother-and-daughter clip so the mother stays one voice and the daughter stays another. Titanet remains the fallback when the segmentation model is missing. Full pyannote.audio stays out of V1.

## 2026-09-29 — Spoken formulas in the rewrite

### Done
- The rewrite no longer asks Qwen 0.5B to polish the Argos line. That model copied the word-for-word draft, so a farewell such as "see you" stayed a literal "te vois".
- Each line is now dubbed from the source by `qwen3.8:27b` on the host Ollama, with the previous and next lines as situation. The Argos line is only the fallback when the model is missing or the answer is unusable.
- The Docker worker reaches that daemon through `host.docker.internal`. The compose Ollama service still only has the 0.5B model and is not on the rewrite path.

## 2026-09-29 — Mac worker on MPS

### Done
- `scripts/worker-mac.sh` stops the Docker CPU worker and runs Celery on the Mac with `--pool=solo` so OmniVoice can use MPS. Clone settings are unchanged.
- The host venv installs the default Apple Silicon torch wheel plus the worker requirements. The Linux image still force-installs CPU torch.

## 2026-09-29 — Stage progress and rewrite script

### Done
- Rewrite and voice report how many lines are finished. The pipeline shows that count and an estimate of the time left on the running stage.
- The project page shows the rewritten script next to the transcript and the translation.

## 2026-09-29 — Stop a running translation

### Done
- The project page has a Stop button while a job is queued or running. It marks the job cancelled and kills the worker process, so a voice clone on CPU ends immediately.
- Between clone batches the worker also checks that flag, so a stop still lands if the kill signal is missed.

## 2026-09-29 — Spoken rewrite with Qwen 0.5B

### Done
- After Argos, each line is rewritten by `qwen2.5:0.5b` through Ollama. The model sees the original sentence, the literal draft, and the target language, and returns one spoken sentence.
- A dropped name, an explanation, or a model that does not answer keeps the Argos line. Times, speaker, and the clone reference stay on the segment. The French variety is applied after the model.
- `docker compose` starts Ollama and pulls the model on first boot. `scripts/dev.sh` starts that service with the rest of the local infra.

## 2026-09-28 — Original voice clone is mandatory again

### Done
- France, Belgium, and Switzerland were speaking with a regional catalog voice. Every accent now clones the original speaker with OmniVoice. The accent only changes a few French words.
- A dub with no original soundtrack fails instead of falling back to edge-tts or espeak.
- `.cursor/rules/voice-cloning.mdc` and `AGENTS.md` tell later sessions that this clone path stays.

## 2026-09-28 — Keep the original ambience

### Done
- Render no longer replaces the whole soundtrack with the dub. Demucs removes the original voice, and the music, effects, and room tone are mixed back under the new voice. The accompaniment ducks only while the dub is speaking.
- The worker image installs Demucs. Rebuild the worker so a running job can separate the soundtrack.
- Stem files are written as WAV directly. Current torchaudio cannot save them without TorchCodec.

## 2026-09-28 — Faster clone, same decode

### Done
- Lines of one voice with similar lengths share one OmniVoice `generate()` call, up to four lines. Decode stays at 32 steps and guidance 3.
- The worker process is no longer recycled after every job, so the loaded OmniVoice weights stay in memory for the next video.

## 2026-09-28 — French accent choice

### Done
- A French project can pick France, Québec, Belgium, or Switzerland. Québec stays the default and keeps the speaker clone.
- France, Belgium, and Switzerland speak with that region's neural voice, and a few marker words in the script follow the variety (week-end / fin de semaine, septante, huitante, nonante).

## 2026-09-28 — Modern UI refresh

### Done
- Restyled the whole dashboard: rounded glass panels, ambient gradient background, gradient brand mark, pill status badges, toggle switches instead of checkboxes, and an inline SVG icon set (no new dependency).
- The pipeline rail is now a stepper with check/numbered nodes, a live progress bar, and per-stage durations. The upload area is a full dropzone with hover/drag states.
- Verified with `tsc --noEmit` and `next build`; both pages screenshot-checked in the browser. Behavior and API calls are unchanged.

## 2026-09-28 — Render keeps the full picture

### Done
- The mux no longer ends when the dubbed track ends. A short soundtrack is padded with silence, so the export runs to the last frame of the original video.

## 2026-09-28 — Pipeline stage durations

### Done
- The project pipeline rail shows each stage duration from `started_at` / `finished_at`, plus the job total. A running stage keeps counting.

## 2026-09-28 — Dashboard UI rewrite

### Done
- Rebuilt the web shell, project library, and project studio around the existing API: language selects, upload drop zone, pipeline rail, result player, and downloads.
- Warm studio palette replaces the previous cyan-on-slate layout. Original pipeline behavior is unchanged.

## 2026-09-28 — Closer voice match

### Done
- The clone reference is now a 24 kHz extract of the original soundtrack. Transcription still uses 16 kHz, which had been stripping everything above 8 kHz before OmniVoice heard the voice.
- The dubbed track stays at 24 kHz through fit, align, and the final mux, so that brightness is still in the export.
- OmniVoice decodes with guidance 3 instead of its default 2, so the line stays on the reference voice.

## 2026-09-28 — Mouth redraw removed

### Done
- The lip-sync stage no longer runs MuseTalk. It copies the source picture, and render muxes the dubbed soundtrack onto those original frames.
- The worker image no longer installs MuseTalk. Mouth redraw stays out of the pipeline.

## 2026-09-28 — Speakable lines and real speaker turns

### Done
- Each sentence is its own dubbed line. A naming cue still keeps the name ("team refurb") in the original language, and the next clause is translated on its own.
- The clone is no longer asked to fill a long pause by stretching the words. A short line stays at a natural pace and the rest of the slot is silence.
- Speaker labels use a few seconds of the current turn, so one person is not split on every sentence. A new person still gets their own voice. A short follow-up keeps the voice that just spoke.
- A few French phrasings Argos speaks badly ("génials", "all my friends", "go check it out") are corrected before synthesis.
- Short cloned lines were each starting with a noise. Same-speaker lines are packed into a real phrase again, and OmniVoice chooses its own length instead of being forced into the slot.
- The packed reference included the pauses between sentences, so the clone drifted off the original voice. Each speaker sample is now the start of their own turn, up to 10s, with those pauses removed. A line is timed to the original only when the French actually fits that window.

## 2026-09-28 — Bootstrap + V1 scaffold

### Done
- Copied `AGENTS.md`, tech reference, Cursor implementation prompt into the repo.
- Wrote architecture, implementation plan, ADR 001, Cursor rules.
- Scaffolded monorepo: `apps/web`, `services/api`, `services/worker`, `packages/shared`, `infra/dev`, `scripts`.
- Docker Compose: Postgres, Redis, MinIO, API, worker, web.
- FastAPI: projects, upload URLs, jobs, artifacts, health.
- Celery pipeline with mock providers for all AI/media stages.
- Next.js dashboard: project list/create, upload, job stage polling.
- `scripts/verify.sh` green (pytest, imports, web build, compose config).
- Docker daemon was not running in this environment; `docker compose config` validated. Start Docker Desktop then `docker compose up` for full local stack.

### Works
- Local orchestration path with `PROVIDER_MODE=mock`.
- DB models + migration `001_initial`.
- Frontend build/typecheck.

### Mocked / deferred
- Real faster-whisper, Argos/NLLB, vLLM rewrite, OmniVoice, MuseTalk, FFmpeg media.
- Production auth (Clerk/Auth.js) and Stripe.

## 2026-09-28 — Upload fix and local translation pipeline

### Done
- Browser upload no longer PUTs the file to LocalStack. The dashboard posts the video to the API, which stores it. That was the Safari “Load failed” (S3 CORS preflight returned 403).
- S3 client skips flexible checksums that LocalStack rejects.
- `PROVIDER_MODE=local` on the Docker worker: faster-whisper, Argos Translate, edge-tts (espeak-ng fallback), ffmpeg render with burned-in subtitles.
- Lip sync keeps the original picture until MuseTalk is installed. Voice output is a target-language neural voice, not a clone.

## 2026-09-28 — Per-speaker voice cloning

### Done
- Transcription labels each line with a speaker id (`spk0`, `spk1`, …) from pitch and spectral shape, and keeps the original wording for the clone reference.
- Translation and rewrite carry that speaker through to synthesis.
- Local synthesis extracts a short sample of each person and speaks their translated lines with OmniVoice. The worker image installs OmniVoice on CPU torch.
- The project page shows how many voices from the video are cloned.

### Limits
- Voices that are very close in pitch and timbre can share one clone. pyannote diarization is still deferred.
- The first dubbed job downloads the OmniVoice weights into the Hugging Face cache volume.
- Verified on the Team Refurb test clip (en→fr): job completed, 1080×1920 H.264/AAC export, player loads in the dashboard.

## 2026-09-28 — MuseTalk lip sync

### Done
- The local lip-sync stage runs MuseTalk 1.5 when `/opt/musetalk-venv` and the V1.5 weights are present. The dubbed audio drives a new mouth; render still muxes that picture with the translated soundtrack and burned-in subtitles.
- MuseTalk is installed in its own virtualenv. Face landmarks use face-alignment instead of mmpose, because mmcv has no Python 3.12 ARM CPU build.
- The picture is sampled at 12 fps and the long edge is capped at 960 px before MuseTalk, so a CPU worker with about 8 GB of RAM can finish. Set `MUSETALK_MAX_FPS` and `MUSETALK_MAX_EDGE` to raise either limit.

### Limits
- This machine has no NVIDIA GPU. MuseTalk runs on CPU, so a long clip stays slow.
- If the venv or weights are missing, the stage still keeps the original picture and says so on the job.

### Local run notes
- Official `minio/minio` image could not be pulled; switched local object storage to **LocalStack S3** (`s3:4566`).
- Full `docker compose up --build` verified: API `/health`, web `:3000`, project create OK.

## 2026-09-28 — Name shield stops at the name

### Done
- Only the short name after “called” / « s'appelle » stays in the original language. The following clause is translated again, instead of remaining English until the next speaker.

## 2026-09-28 — Two-speaker split

### Done
- Lines are labeled with a Titanet-small speaker embedding. Pitch and spectral shape were the same for both people on this clip because they share one microphone, so everything stayed `spk0`.
- The spectral clustering remains the fallback when the model is not installed.

## 2026-09-28 — Intelligible clone and names

### Done
- OmniVoice now receives the target language and the line duration, and decodes with 32 steps. The previous CPU path used 16 steps and no language, then time-stretched each line into the English slot, which made the French unintelligible.
- Playback speedup is capped at 1.25×. A longer line keeps its words instead of being crushed.
- Whisper `small` replaces `base`, and the spoken language is detected. Forcing English on this French clip made Whisper rewrite it, then Argos translated that rewrite again. When the speech is already in the target language, the words are kept.
- Paused sentences are joined before translation, and the words after “called” / “named” / « appelle » stay untranslated.

## 2026-09-28 — Optional burned-in subtitles

### Done
- New projects and the project page have a checkbox to burn subtitles into the export. It stays on by default.
- When the option is off, render muxes the dubbed picture and soundtrack and skips the subtitle file.

## 2026-09-28 — Safari EmptyRanges overlay

### Done
- The result player keeps one `<video>` for a finished render. Presigned download URLs change on each artifact refetch, and remounting the element made Safari throw `Can't find variable: EmptyRanges` (WebKit bug 318284).
- A before-interactive script defines that missing global and stops the same error from opening the Next.js overlay.

## 2026-10-03 — Worker on a Windows NVIDIA GPU

### Done
- `docker-compose.gpu-worker.yml` runs only the Celery worker on a Windows PC (Docker Desktop, WSL2). It uses the Mac's Postgres, Redis, S3, and Ollama, so the rewrite stays on `qwen3.8:27b` with Metal.
- `services/worker/Dockerfile.gpu` installs PyTorch cu128 and points CTranslate2 at the cuBLAS and cuDNN copies bundled with torch. OmniVoice and Demucs pick CUDA on their own. Each line is still cloned from the speaker who said it.
- The worker refuses to start when CUDA is not visible, instead of cloning voices on the PC's CPU. It also stops when it cannot reach the Mac.
- `WHISPER_DEVICE` (default `cpu`) lets Whisper use CUDA. A failed CUDA load falls back to CPU with a warning.
- `scripts/mac-host-gpu-worker.sh` stops every Mac worker and the compose Ollama, which only has the 0.5B model. It also warns when the host Ollama listens on loopback only.
