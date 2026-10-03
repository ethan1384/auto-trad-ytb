"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { api } from "@/lib/api";
import { StatusLed, cn } from "@/components/ui";
import { IconFolder, IconWaveform } from "@/components/icons";

function Wordmark() {
  return (
    <Link href="/" className="group flex items-center gap-3">
      <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-[#f8c264] to-[#e08a1e] text-accent-ink shadow-glow transition-transform duration-200 group-hover:scale-105">
        <IconWaveform className="h-5 w-5" strokeWidth={2.2} />
      </span>
      <span className="leading-none">
        <span className="block text-[15px] font-semibold tracking-tight text-ink">
          Dubbing Studio
        </span>
        <span className="mt-1 block text-[10px] font-medium uppercase tracking-[0.2em] text-faint">
          Local
        </span>
      </span>
    </Link>
  );
}

function ApiStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: 1,
    refetchInterval: 20_000,
  });

  if (health.isPending) {
    return <StatusLed tone="idle" label="API" />;
  }
  if (health.isError) {
    return <StatusLed tone="bad" label="API down" />;
  }
  return <StatusLed tone="ok" label="API live" />;
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const onProjects = path === "/" || path.startsWith("/projects");

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-canvas/80 px-4 py-3 backdrop-blur-xl lg:hidden">
        <Wordmark />
        <ApiStatus />
      </header>

      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-line bg-raised/60 px-5 py-7 backdrop-blur-xl lg:flex">
        <Wordmark />
        <nav className="mt-10 space-y-1">
          <Link
            href="/"
            aria-current={onProjects ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors",
              onProjects
                ? "bg-white/[0.07] text-ink shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]"
                : "text-muted hover:bg-white/[0.04] hover:text-ink",
            )}
          >
            <IconFolder className={cn("h-4 w-4", onProjects ? "text-accent" : "text-faint")} />
            Projects
            {onProjects ? (
              <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
            ) : null}
          </Link>
        </nav>
        <div className="mt-auto space-y-3 rounded-2xl border border-line bg-white/[0.03] p-4">
          <ApiStatus />
          <p className="text-xs leading-relaxed text-faint">
            Original picture kept. Music and other sounds stay under the dubbed voice.
          </p>
        </div>
      </aside>

      <div className="lg:pl-64">
        <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-8 lg:py-12">{children}</main>
      </div>
    </div>
  );
}
