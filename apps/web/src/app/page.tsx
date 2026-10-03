"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  Banner,
  Button,
  CheckRow,
  Field,
  FrenchAccentSelect,
  LanguagePair,
  LanguageSelect,
  LocalTime,
  Panel,
} from "@/components/ui";
import { IconArrowRight, IconFolder, IconSparkles } from "@/components/icons";
import { api } from "@/lib/api";

export default function HomePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("fr");
  const [accent, setAccent] = useState("fr-CA");
  const [consent, setConsent] = useState(true);
  const [subtitles, setSubtitles] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    refetchInterval: 10_000,
  });

  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    create.mutate({
      name,
      source_language: source,
      target_language: target,
      target_accent: target === "fr" ? accent : null,
      voice_consent: consent,
      include_subtitles: subtitles,
    });
  }

  const count = projects.data?.length;

  return (
    <div className="space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-4 animate-fade-up">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-accent">Library</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight sm:text-5xl">Your projects</h1>
          <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted">
            Translate and dub your videos into any language — every speaker keeps their own voice.
          </p>
        </div>
        {typeof count === "number" ? (
          <span className="rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 text-xs font-medium text-muted">
            {count} {count === 1 ? "project" : "projects"}
          </span>
        ) : null}
      </header>

      <Panel className="animate-fade-up overflow-hidden [animation-delay:80ms]">
        <div className="border-b border-line bg-gradient-to-r from-accent/[0.08] via-transparent to-violet/[0.08] px-6 py-5">
          <div className="flex items-center gap-2.5">
            <IconSparkles className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-semibold tracking-tight">New dub</h2>
          </div>
          <p className="mt-1 text-sm text-muted">
            A project needs voice-cloning consent before it can run.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-6 p-6">
          <Field label="Name" htmlFor="project-name">
            <input
              id="project-name"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="field"
              placeholder="Spring launch, French"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
            <Field label="Source" htmlFor="source-language">
              <LanguageSelect
                id="source-language"
                value={source}
                onChange={(event) => setSource(event.target.value)}
              />
            </Field>
            <span
              className="hidden pb-3 text-center text-accent sm:block"
              aria-hidden
            >
              <IconArrowRight className="h-4 w-4" />
            </span>
            <Field label="Target" htmlFor="target-language">
              <LanguageSelect
                id="target-language"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              />
            </Field>
          </div>
          {target === "fr" ? (
            <Field
              label="French accent"
              htmlFor="french-accent"
              hint="Changes a few French words only. Every speaker is still cloned from their own voice."
            >
              <FrenchAccentSelect
                id="french-accent"
                value={accent}
                onChange={(event) => setAccent(event.target.value)}
              />
            </Field>
          ) : null}
          {source === target ? (
            <Banner tone="info">Source and target are the same language.</Banner>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <CheckRow
              checked={consent}
              onChange={setConsent}
              title="Voice cloning consent"
              detail="Required. Each speaker is dubbed with a clone of their own voice."
            />
            <CheckRow
              checked={subtitles}
              onChange={setSubtitles}
              title="Burn subtitles"
              detail="Draw the translated lines on the exported picture."
            />
          </div>
          {error ? <Banner tone="bad">{error}</Banner> : null}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
            <p className="text-xs text-faint">
              {consent ? "Ready to create." : "Turn consent on to create a project that can run."}
            </p>
            <Button type="submit" disabled={create.isPending || !name.trim() || !consent}>
              {create.isPending ? "Creating…" : "Create project"}
              {create.isPending ? null : <IconArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </form>
      </Panel>

      <section className="space-y-4 animate-fade-up [animation-delay:160ms]">
        <h2 className="text-xs font-semibold uppercase tracking-[0.22em] text-faint">Recent</h2>
        {projects.isError ? (
          <Banner tone="bad">
            API unreachable at {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}. Start
            the backend first.
          </Banner>
        ) : null}
        {projects.isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }, (_, index) => (
              <div
                key={index}
                className="h-40 animate-pulse rounded-2xl border border-line bg-raised/60"
              />
            ))}
          </div>
        ) : null}
        {projects.data && projects.data.length > 0 ? (
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {projects.data.map((project) => (
              <li key={project.id}>
                <Link
                  href={`/projects/${project.id}`}
                  className="group flex h-full flex-col justify-between gap-10 rounded-2xl border border-line bg-raised/80 p-5 shadow-card backdrop-blur-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lift"
                >
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-lg font-semibold tracking-tight transition-colors group-hover:text-accent">
                      {project.name}
                    </h3>
                    <LocalTime
                      iso={project.created_at}
                      className="shrink-0 pt-1 text-[11px] font-medium text-faint"
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <LanguagePair
                      source={project.source_language}
                      target={project.target_language}
                      accent={project.target_accent}
                    />
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors group-hover:text-ink">
                      Open
                      <IconArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
        {projects.data?.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-line-strong px-6 py-16 text-center">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-white/5 text-faint">
              <IconFolder className="h-5 w-5" />
            </span>
            <p className="mt-4 font-medium text-ink">No projects yet</p>
            <p className="mt-1 text-sm text-muted">
              Create one above, then upload a video to dub.
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );
}
