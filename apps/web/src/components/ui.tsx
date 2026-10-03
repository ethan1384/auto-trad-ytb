"use client";

import { FRENCH_ACCENTS, LANGUAGES, Tone, formatWhen, frenchAccentLabel, languageName } from "@/lib/studio";
import { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes, useEffect, useState } from "react";

export function LocalTime({ iso, className }: { iso: string; className?: string }) {
  const [label, setLabel] = useState<string | null>(null);
  useEffect(() => {
    setLabel(formatWhen(iso));
  }, [iso]);
  return (
    <time dateTime={iso} className={className}>
      {label ?? "\u00a0"}
    </time>
  );
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

const DOT_CLASS: Record<Tone, string> = {
  ok: "bg-ok",
  run: "led-run bg-accent",
  bad: "bg-bad",
  idle: "bg-faint/70",
};

const PILL_CLASS: Record<Tone, string> = {
  ok: "border-ok/25 bg-ok/10 text-ok",
  run: "border-accent/25 bg-accent/10 text-accent",
  bad: "border-bad/25 bg-bad/10 text-bad",
  idle: "border-white/10 bg-white/5 text-muted",
};

export function StatusLed({ tone, label }: { tone: Tone; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1",
        PILL_CLASS[tone],
      )}
    >
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_CLASS[tone])} aria-hidden />
      {label ? (
        <span className="text-[11px] font-medium uppercase tracking-[0.12em]">{label}</span>
      ) : null}
    </span>
  );
}

export function LanguagePair({
  source,
  target,
  accent,
}: {
  source: string;
  target: string;
  accent?: string | null;
}) {
  const french = target.toLowerCase().startsWith("fr");
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]">
      <span className="text-ink">{source}</span>
      <span aria-hidden className="text-accent">
        →
      </span>
      <span className="text-ink">{target}</span>
      {french ? (
        <span className="normal-case tracking-normal text-faint">{frenchAccentLabel(accent)}</span>
      ) : null}
      <span className="sr-only">
        {languageName(source)} to {languageName(target)}
        {french ? `, ${frenchAccentLabel(accent)}` : ""}
      </span>
    </span>
  );
}

export function FrenchAccentSelect({
  value,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { value: string }) {
  return (
    <select className="field" value={value} {...props}>
      {FRENCH_ACCENTS.map((item) => (
        <option key={item.code} value={item.code}>
          {item.label}
        </option>
      ))}
    </select>
  );
}

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-line bg-raised/80 shadow-card backdrop-blur-sm",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function Banner({ tone, children }: { tone: "ok" | "bad" | "info"; children: ReactNode }) {
  const styles = {
    ok: "border-ok/25 bg-ok/10 text-ok",
    bad: "border-bad/30 bg-bad/10 text-bad",
    info: "border-line bg-white/[0.04] text-muted",
  } as const;
  return (
    <p role="status" className={cn("rounded-xl border px-4 py-3 text-sm", styles[tone])}>
      {children}
    </p>
  );
}

export function Button({
  tone = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "ghost" }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100",
        tone === "primary"
          ? "bg-gradient-to-b from-[#f8c264] to-[#e99e2c] text-accent-ink shadow-glow hover:brightness-110"
          : "border border-white/10 bg-white/5 text-ink hover:border-white/20 hover:bg-white/10",
        className,
      )}
      {...props}
    />
  );
}

export function Field({
  label,
  htmlFor,
  children,
  hint,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label htmlFor={htmlFor} className="block space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-faint">{hint}</span> : null}
    </label>
  );
}

export function LanguageSelect({
  value,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { value: string }) {
  const known = LANGUAGES.some((item) => item.code === value);
  return (
    <select className="field" value={value} {...props}>
      {known ? null : <option value={value}>{value}</option>}
      {LANGUAGES.map((item) => (
        <option key={item.code} value={item.code}>
          {item.label}
        </option>
      ))}
    </select>
  );
}

export function CheckRow({
  checked,
  onChange,
  disabled,
  title,
  detail,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  title: string;
  detail: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3.5 transition hover:border-white/20 hover:bg-white/[0.05]",
        disabled && "cursor-not-allowed opacity-50 hover:border-white/10 hover:bg-white/[0.03]",
      )}
    >
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span
          aria-hidden
          className="h-5 w-9 rounded-full bg-white/10 transition-colors duration-200 peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40"
        />
        <span
          aria-hidden
          className="pointer-events-none absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 peer-checked:translate-x-4 peer-checked:bg-accent-ink"
        />
      </span>
      <span>
        <span className="block text-sm font-medium text-ink">{title}</span>
        <span className="mt-0.5 block text-xs leading-relaxed text-faint">{detail}</span>
      </span>
    </label>
  );
}
