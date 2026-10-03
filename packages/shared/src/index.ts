export const JOB_STATUSES = [
  "pending",
  "queued",
  "running",
  "failed",
  "completed",
  "cancelled",
] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];

export const STAGE_STATUSES = [
  "pending",
  "running",
  "succeeded",
  "failed",
  "skipped",
] as const;

export type StageStatus = (typeof STAGE_STATUSES)[number];

export const PIPELINE_STAGES = [
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

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

export const PIPELINE_LABELS: Record<PipelineStage, string> = {
  ingest: "Ingest",
  extract_audio: "Extract audio",
  transcribe: "Transcribe",
  translate: "Translate",
  rewrite: "Rewrite",
  synthesize: "Voice synthesis",
  align: "Align timing",
  lipsync: "Original picture",
  render: "Render",
  complete: "Complete",
};
