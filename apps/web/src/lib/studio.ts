export const FRENCH_ACCENTS = [
  { code: "fr-FR", label: "France" },
  { code: "fr-CA", label: "Québec" },
  { code: "fr-BE", label: "Belgium" },
  { code: "fr-CH", label: "Switzerland" },
] as const;

export function frenchAccentLabel(code: string | null | undefined): string {
  return FRENCH_ACCENTS.find((item) => item.code === code)?.label ?? "Québec";
}

export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "fr", label: "French" },
  { code: "es", label: "Spanish" },
  { code: "de", label: "German" },
  { code: "pt", label: "Portuguese" },
  { code: "it", label: "Italian" },
  { code: "nl", label: "Dutch" },
  { code: "pl", label: "Polish" },
  { code: "ru", label: "Russian" },
  { code: "tr", label: "Turkish" },
  { code: "ar", label: "Arabic" },
  { code: "hi", label: "Hindi" },
  { code: "ja", label: "Japanese" },
  { code: "ko", label: "Korean" },
  { code: "zh", label: "Chinese" },
] as const;

export const STAGE_ORDER = [
  "ingest",
  "extract_audio",
  "transcribe",
  "translate",
  "rewrite",
  "synthesize",
  "align",
  "lipsync",
  "render",
  "complete",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  ingest: "Ingest",
  extract_audio: "Audio",
  transcribe: "Transcript",
  translate: "Translate",
  rewrite: "Rewrite",
  synthesize: "Voices",
  align: "Timing",
  lipsync: "Picture",
  render: "Render",
  complete: "Done",
};

export const ARTIFACT_LABELS: Record<string, string> = {
  source_video: "Source video",
  audio: "Extracted audio",
  transcript: "Transcript",
  script: "Translated script",
  voice: "Dubbed voice",
  render: "Translated video",
  subtitles: "Subtitles",
};

export function languageName(code: string): string {
  return LANGUAGES.find((item) => item.code === code)?.label ?? code.toUpperCase();
}

export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export type StageWork = {
  done: number;
  total: number;
  unit: string;
};

export function stageWork(detail: Record<string, unknown> | undefined): StageWork | null {
  if (!detail) return null;
  const { done, total } = detail;
  if (typeof done !== "number" || typeof total !== "number") return null;
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return null;
  const unit = typeof detail.unit === "string" && detail.unit ? detail.unit : "lines";
  return { done: Math.max(0, Math.min(done, total)), total, unit };
}

export function stageShare(stage: {
  status: string;
  detail?: Record<string, unknown>;
}): number {
  if (statusTone(stage.status) === "ok") return 1;
  if (stage.status !== "running") return 0;
  const work = stageWork(stage.detail);
  if (!work) return 0;
  return work.done / work.total;
}

export function stageRemainingMs(
  stage: { started_at: string | null; finished_at: string | null; status: string; detail?: Record<string, unknown> },
  now: number | null,
): number | null {
  const elapsed = stageElapsedMs(stage, now);
  const work = stageWork(stage.detail);
  if (elapsed === null || !work || work.done <= 0) return null;
  if (work.done >= work.total) return 0;
  return (elapsed * (work.total - work.done)) / work.done;
}

export function formatWork(work: StageWork, remaining: number | null): string {
  const count = `${Math.round(work.done)}/${Math.round(work.total)} ${work.unit}`;
  if (remaining === null || remaining <= 0) return count;
  return `${count} · ~${formatDuration(remaining)} left`;
}

export function stageElapsedMs(
  stage: { started_at: string | null; finished_at: string | null; status: string },
  now: number | null,
): number | null {
  if (!stage.started_at) return null;
  const start = Date.parse(stage.started_at);
  if (Number.isNaN(start)) return null;
  if (stage.finished_at) {
    const end = Date.parse(stage.finished_at);
    if (Number.isNaN(end)) return null;
    return Math.max(0, end - start);
  }
  if (stage.status !== "running" || now === null) return null;
  return Math.max(0, now - start);
}

export function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
}

export type Tone = "ok" | "run" | "bad" | "idle";

export function statusTone(status: string): Tone {
  if (status === "succeeded" || status === "completed" || status === "skipped") return "ok";
  if (status === "running" || status === "queued") return "run";
  if (status === "failed" || status === "cancelled") return "bad";
  return "idle";
}
