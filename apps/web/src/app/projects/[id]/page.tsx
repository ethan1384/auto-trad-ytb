"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DragEvent, useEffect, useRef, useState } from "react";
import {
  Banner,
  Button,
  CheckRow,
  Field,
  FrenchAccentSelect,
  LanguagePair,
  Panel,
  StatusLed,
  cn,
} from "@/components/ui";
import {
  IconCheck,
  IconChevronLeft,
  IconDownload,
  IconFilm,
  IconPlay,
  IconStop,
  IconUpload,
} from "@/components/icons";
import { api, Job, JobStage } from "@/lib/api";
import {
  ARTIFACT_LABELS,
  STAGE_LABELS,
  STAGE_ORDER,
  formatDuration,
  formatWork,
  stageElapsedMs,
  stageRemainingMs,
  stageShare,
  stageWork,
  statusTone,
} from "@/lib/studio";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });

  const latest = useQuery({
    queryKey: ["latest-job", projectId],
    queryFn: () => api.latestJob(projectId),
  });

  const activeJobId = jobId ?? latest.data?.id ?? null;

  const job = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: () => api.getJob(activeJobId!),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" || status === "cancelled" ? false : 1500;
    },
  });

  const artifacts = useQuery({
    queryKey: ["artifacts", projectId, job.data?.status],
    queryFn: () => api.listArtifacts(projectId),
    enabled: job.data?.status === "completed",
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadSource(projectId, file),
    onSuccess: (asset, file) => {
      setAssetId(asset.id);
      setFileName(file.name);
      setMessage("Source video uploaded.");
    },
    onError: (err: Error) => setError(err.message),
  });

  const subtitles = useMutation({
    mutationFn: (include: boolean) => api.updateProject(projectId, { include_subtitles: include }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["project", projectId], updated);
    },
    onError: (err: Error) => setError(err.message),
  });

  const accent = useMutation({
    mutationFn: (next: string) => api.updateProject(projectId, { target_accent: next }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["project", projectId], updated);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const stopJob = useMutation({
    mutationFn: () => api.cancelJob(activeJobId!),
    onSuccess: (updated) => {
      queryClient.setQueryData(["job", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["latest-job", projectId] });
      setMessage("Translation stopped.");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const startJob = useMutation({
    mutationFn: () => api.createJob(projectId, assetId ?? undefined),
    onSuccess: (created: Job) => {
      setJobId(created.id);
      setMessage(
        "Translation started. The first run downloads speech, translation, and voice-cloning models.",
      );
      queryClient.invalidateQueries({ queryKey: ["job", created.id] });
      queryClient.invalidateQueries({ queryKey: ["latest-job", projectId] });
    },
    onError: (err: Error) => setError(err.message),
  });

  function takeFile(file: File | undefined) {
    if (!file || upload.isPending) return;
    setError(null);
    setMessage(null);
    setFileName(file.name);
    upload.mutate(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    takeFile(event.dataTransfer.files?.[0]);
  }

  const translation = job.data?.stages.find((stage) => stage.name === "translate");
  const transcript = job.data?.stages.find((stage) => stage.name === "transcribe");
  const rewrite = job.data?.stages.find((stage) => stage.name === "rewrite");
  const speakerCount = Array.isArray(transcript?.detail?.speakers)
    ? transcript.detail.speakers.length
    : 0;
  const seenKinds = new Set<string>();
  const downloads = (artifacts.data ?? []).filter((item) => {
    if (seenKinds.has(item.kind)) return false;
    seenKinds.add(item.kind);
    return true;
  });
  const render = downloads.find((item) => item.kind === "render" && item.download_url);
  const pinnedRender = useRef<{ id: string; url: string } | null>(null);
  if (render?.download_url && pinnedRender.current?.id !== render.id) {
    pinnedRender.current = { id: render.id, url: render.download_url };
  }
  const playback = pinnedRender.current;
  const stages = orderedStages(job.data?.stages);
  const running = job.data?.status === "running" || job.data?.status === "queued";
  const busy = startJob.isPending || upload.isPending || subtitles.isPending || accent.isPending;
  const canStart = Boolean(project.data?.voice_consent) && !busy;

  return (
    <div className="space-y-8">
      <header className="space-y-5 animate-fade-up">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted transition-colors hover:text-ink"
        >
          <IconChevronLeft className="h-4 w-4" />
          Projects
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-4xl font-semibold tracking-tight">
              {project.data?.name ?? "Project"}
            </h1>
            {project.data ? (
              <div className="mt-3.5 flex flex-wrap items-center gap-2">
                <LanguagePair
                  source={project.data.source_language}
                  target={project.data.target_language}
                  accent={project.data.target_accent}
                />
                <StatusLed
                  tone={project.data.voice_consent ? "ok" : "bad"}
                  label={project.data.voice_consent ? "Voice consent" : "Consent missing"}
                />
                <StatusLed
                  tone={project.data.include_subtitles ? "ok" : "idle"}
                  label={project.data.include_subtitles ? "Subtitles on" : "Subtitles off"}
                />
              </div>
            ) : null}
          </div>
          {job.data ? <StatusLed tone={statusTone(job.data.status)} label={job.data.status} /> : null}
        </div>
        {project.isError ? <Banner tone="bad">{project.error.message}</Banner> : null}
      </header>

      {message ? <Banner tone="ok">{message}</Banner> : null}
      {error ? <Banner tone="bad">{error}</Banner> : null}
      {job.data?.error ? <Banner tone="bad">{job.data.error}</Banner> : null}

      {job.data ? (
        <Pipeline
          stages={stages}
          stopping={stopJob.isPending}
          onStop={running ? () => stopJob.mutate() : undefined}
        />
      ) : (
        <PipelinePreview />
      )}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
        <Panel className="p-5">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              "flex min-h-56 flex-1 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center transition-all duration-200",
              dragging
                ? "border-accent/60 bg-accent/[0.07] scale-[1.01]"
                : "border-white/15 hover:border-white/30 hover:bg-white/[0.03]",
            )}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") fileInput.current?.click();
            }}
          >
            <span
              className={cn(
                "grid h-14 w-14 place-items-center rounded-2xl transition-all duration-200",
                dragging
                  ? "bg-accent/20 text-accent scale-110"
                  : "bg-gradient-to-b from-accent/25 to-accent/5 text-accent",
              )}
            >
              <IconUpload className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold tracking-tight">
              {upload.isPending ? "Uploading…" : fileName ?? "Drop a video here"}
            </h2>
            <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted">
              {fileName && !upload.isPending
                ? "Drop another file to replace it, or start the translation."
                : "Each person in the video is dubbed in the target language with a clone of their own voice."}
            </p>
            <span className="mt-5 inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-ink transition hover:bg-white/10">
              Browse files
            </span>
            <input
              ref={fileInput}
              id="source-video"
              type="file"
              accept="video/*"
              className="sr-only"
              disabled={upload.isPending}
              onChange={(event) => takeFile(event.target.files?.[0])}
            />
          </div>
        </Panel>

        <Panel className="flex flex-col justify-between gap-6 p-5">
          <div className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-faint">Export</p>
            {project.data?.target_language === "fr" ? (
              <Field
                label="French accent"
                htmlFor="project-french-accent"
                hint="Changes a few French words only. Every speaker is still cloned from their own voice."
              >
                <FrenchAccentSelect
                  id="project-french-accent"
                  value={project.data.target_accent ?? "fr-CA"}
                  disabled={!project.data || accent.isPending || startJob.isPending}
                  onChange={(event) => {
                    setError(null);
                    accent.mutate(event.target.value);
                  }}
                />
              </Field>
            ) : null}
            <CheckRow
              checked={project.data?.include_subtitles ?? true}
              disabled={!project.data || subtitles.isPending || startJob.isPending}
              onChange={(include) => {
                setError(null);
                subtitles.mutate(include);
              }}
              title="Burn subtitles"
              detail={
                project.data?.include_subtitles
                  ? "Subtitles are burned into the video."
                  : "The export is rendered without subtitles."
              }
            />
          </div>
          <div className="space-y-3">
            <Button
              type="button"
              className="w-full"
              disabled={!canStart}
              onClick={() => {
                setError(null);
                startJob.mutate();
              }}
            >
              {startJob.isPending ? (
                "Starting…"
              ) : (
                <>
                  <IconPlay className="h-4 w-4" />
                  Start translation
                </>
              )}
            </Button>
            {project.data && !project.data.voice_consent ? (
              <p className="text-xs leading-relaxed text-bad">
                This project was created without voice-cloning consent, so it cannot run.
              </p>
            ) : (
              <p className="text-xs leading-relaxed text-faint">
                The original picture stays. Music, effects, and room tone stay under the new voice.
              </p>
            )}
          </div>
        </Panel>
      </section>

      {transcript?.detail?.text || translation?.detail?.text || rewrite?.detail?.text ? (
        <section className="grid gap-4 lg:grid-cols-3">
          <ScriptPanel
            title="Transcript"
            text={String(transcript?.detail?.text ?? "Waiting for transcription.")}
            note={
              speakerCount === 0
                ? undefined
                : speakerCount === 1
                  ? "1 voice from the video is cloned for the dub."
                  : `${speakerCount} voices from the video are cloned for the dub.`
            }
          />
          <ScriptPanel
            title="Translation"
            text={String(translation?.detail?.text ?? "Waiting for translation.")}
          />
          <ScriptPanel
            title="Rewrite"
            text={rewriteBody(rewrite)}
            note={rewriteNote(rewrite)}
          />
        </section>
      ) : null}

      {playback || downloads.length > 0 ? (
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)]">
          {playback ? (
            <Panel className="overflow-hidden">
              <div className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
                <IconFilm className="h-4 w-4 text-accent" />
                <h2 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">
                  Result
                </h2>
              </div>
              <div className="flex justify-center bg-black">
                <video
                  key={playback.id}
                  src={playback.url}
                  controls
                  className="max-h-[70vh] w-auto max-w-full"
                />
              </div>
            </Panel>
          ) : null}
          {downloads.length > 0 ? (
            <Panel className="overflow-hidden">
              <h2 className="border-b border-line px-5 py-3.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
                Downloads
              </h2>
              <ul>
                {downloads.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5 last:border-b-0"
                  >
                    <span className="text-sm text-ink">
                      {ARTIFACT_LABELS[item.kind] ?? item.kind}
                    </span>
                    {item.download_url ? (
                      <a
                        href={item.download_url}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-ink transition hover:border-accent/40 hover:bg-accent/10 hover:text-accent"
                        target="_blank"
                        rel="noreferrer"
                      >
                        <IconDownload className="h-3.5 w-3.5" />
                        Download
                      </a>
                    ) : (
                      <span className="text-sm text-faint">Unavailable</span>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function orderedStages(stages: JobStage[] | undefined): JobStage[] {
  if (!stages) return [];
  return [...stages].sort((a, b) => a.position - b.position);
}

function PipelinePreview() {
  return (
    <Panel className="px-5 py-5 animate-fade-up">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-faint">Pipeline</p>
      <ol className="mt-5 flex gap-0 overflow-x-auto pb-1">
        {STAGE_ORDER.map((name, index) => (
          <li key={name} className="flex min-w-[5.5rem] flex-1 flex-col">
            <div className="flex items-center">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5 text-[10px] font-semibold text-faint">
                {index + 1}
              </span>
              {index < STAGE_ORDER.length - 1 ? (
                <span className="mx-1.5 h-px flex-1 bg-white/10" />
              ) : null}
            </div>
            <span className="mt-2.5 pr-3 text-xs font-medium text-faint">
              {STAGE_LABELS[name]}
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function Pipeline({
  stages,
  onStop,
  stopping,
}: {
  stages: JobStage[];
  onStop?: () => void;
  stopping?: boolean;
}) {
  const notes = stages.filter(
    (stage) => typeof stage.detail.note === "string" || typeof stage.detail.error === "string",
  );
  const live = stages.some(
    (stage) => stage.status === "running" && stage.started_at && !stage.finished_at,
  );
  const now = useClock(live);
  const durations = stages.map((stage) => stageElapsedMs(stage, now));
  const total = durations.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  const share = stages.reduce((sum, stage) => sum + stageShare(stage), 0);
  const progress = stages.length > 0 ? Math.round((share / stages.length) * 100) : 0;
  const activeIndex = stages.findIndex((stage) => stage.status === "running");
  const active = activeIndex >= 0 ? stages[activeIndex] : undefined;
  const activeWork = active ? stageWork(active.detail) : null;
  const activeLeft = active ? stageRemainingMs(active, now) : null;

  return (
    <Panel className="px-5 py-5 animate-fade-up">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-faint">Pipeline</p>
        <div className="flex items-center gap-3">
          {onStop ? (
            <Button
              type="button"
              tone="ghost"
              className="border-bad/40 px-3 py-1.5 text-bad hover:border-bad/60 hover:bg-bad/10"
              disabled={stopping}
              onClick={onStop}
            >
              <IconStop className="h-3.5 w-3.5" />
              {stopping ? "Stopping…" : "Stop"}
            </Button>
          ) : null}
          {total > 0 ? (
            <p className="font-mono text-[11px] tracking-[0.08em] text-muted">
              {formatDuration(total)}
            </p>
          ) : null}
          <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-semibold text-muted">
            {progress}%
          </span>
        </div>
      </div>
      <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/[0.07]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent to-ok transition-all duration-700 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      {active ? (
        <p className="mt-3 text-sm text-ink">
          <span className="font-medium">{STAGE_LABELS[active.name] ?? active.name}</span>
          {activeWork ? (
            <span className="text-muted"> · {formatWork(activeWork, activeLeft)}</span>
          ) : durations[activeIndex] !== null ? (
            <span className="text-muted"> · {formatDuration(durations[activeIndex] ?? 0)}</span>
          ) : null}
        </p>
      ) : null}
      <ol className="mt-5 flex gap-0 overflow-x-auto pb-1">
        {stages.map((stage, index) => {
          const tone = statusTone(stage.status);
          const elapsed = durations[index];
          const work = tone === "run" ? stageWork(stage.detail) : null;
          const left = work ? stageRemainingMs(stage, now) : null;
          return (
            <li key={stage.id} className="flex min-w-[6.5rem] flex-1 flex-col">
              <div className="flex items-center">
                <span
                  className={cn(
                    "grid h-7 w-7 shrink-0 place-items-center rounded-full border text-[10px] font-semibold transition-colors duration-300",
                    tone === "ok" && "border-ok/40 bg-ok/15 text-ok",
                    tone === "run" && "border-accent/50 bg-accent/15 text-accent",
                    tone === "bad" && "border-bad/40 bg-bad/15 text-bad",
                    tone === "idle" && "border-white/10 bg-white/5 text-faint",
                  )}
                >
                  {tone === "ok" ? (
                    <IconCheck className="h-3.5 w-3.5" strokeWidth={2.4} />
                  ) : tone === "run" ? (
                    <span className="led-run h-2 w-2 rounded-full bg-accent" />
                  ) : (
                    index + 1
                  )}
                </span>
                {index < stages.length - 1 ? (
                  <span
                    className={cn(
                      "mx-1.5 h-px flex-1 transition-colors duration-300",
                      tone === "ok" ? "bg-ok/40" : "bg-white/10",
                    )}
                  />
                ) : null}
              </div>
              <span
                className={cn(
                  "mt-2.5 pr-3 text-xs font-medium",
                  tone === "idle" ? "text-faint" : "text-ink",
                )}
              >
                {STAGE_LABELS[stage.name] ?? stage.name}
              </span>
              <span className="pr-3 font-mono text-[10px] tabular-nums text-muted">
                {elapsed === null ? "—" : formatDuration(elapsed)}
              </span>
              {work ? (
                <>
                  <span className="mr-3 mt-1.5 block h-1 overflow-hidden rounded-full bg-white/10">
                    <span
                      className="block h-full bg-accent transition-all duration-500"
                      style={{ width: `${Math.round((work.done / work.total) * 100)}%` }}
                    />
                  </span>
                  <span className="pr-3 text-[10px] leading-snug text-accent">
                    {formatWork(work, left)}
                  </span>
                </>
              ) : null}
              <span className="pr-3 text-[10px] font-medium uppercase tracking-[0.12em] text-faint">
                {stage.status}
                {stage.attempt > 1 ? ` · ${stage.attempt}` : ""}
              </span>
            </li>
          );
        })}
      </ol>
      {notes.length > 0 ? (
        <ul className="mt-5 space-y-2 border-t border-line pt-4">
          {notes.map((stage) => (
            <li key={stage.id} className="text-xs leading-relaxed text-muted">
              <span className="font-medium text-ink">
                {STAGE_LABELS[stage.name] ?? stage.name}.{" "}
              </span>
              {typeof stage.detail.note === "string" ? stage.detail.note : null}
              {typeof stage.detail.error === "string" ? (
                <span className="text-bad">{stage.detail.error}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

function useClock(live: boolean): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!live) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);
  return now;
}

function rewriteBody(stage: JobStage | undefined): string {
  const text = stage?.detail?.text;
  if (typeof text === "string" && text.trim()) return text;
  const work = stage ? stageWork(stage.detail) : null;
  if (stage?.status === "running" && work) {
    return `Rewriting ${Math.round(work.done)} of ${Math.round(work.total)} lines.`;
  }
  if (stage?.status === "running") return "Rewriting…";
  return "Waiting for rewrite.";
}

function rewriteNote(stage: JobStage | undefined): string | undefined {
  const count = stage?.detail?.rewritten_lines;
  if (typeof count !== "number") return undefined;
  if (count === 0) return "Spoken lines kept from the translation.";
  return count === 1 ? "1 line rewritten for speech." : `${count} lines rewritten for speech.`;
}

function ScriptPanel({ title, text, note }: { title: string; text: string; note?: string }) {
  return (
    <Panel className="p-5">
      <h2 className="text-xs font-semibold uppercase tracking-[0.18em] text-faint">{title}</h2>
      {note ? <p className="mt-2 text-xs text-muted">{note}</p> : null}
      <p className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-ink">
        {text}
      </p>
    </Panel>
  );
}
