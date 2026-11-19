"use client";

import React, { useCallback, useEffect, useState } from "react";
import { listRuns, RunItem, getRun, RunResult } from "@/lib/api";
import { STAGES } from "@/lib/stages";

interface RecentRunsSectionProps {
  onSelectRun: (res: RunResult) => void;
  /** Follow a run that is still in flight. */
  onAttach: (id: string, url: string, mode: "fast" | "refine") => void;
  selectedTaskId?: string;
  activeJobId?: string | null;
  /** Bump to force a reload (e.g. when a run finishes). */
  refreshKey?: number;
}

function ago(iso?: string) {
  if (!iso) return "";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function host(r: RunItem) {
  const u = r.url || r.brand || r.task_id;
  try {
    return new URL(u.includes("//") ? u : `https://${u}`).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
}

export function RecentRunsSection({ onSelectRun, onAttach, selectedTaskId, activeJobId, refreshKey }: RecentRunsSectionProps) {
  const [runs, setRuns] = useState<RunItem[] | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const load = useCallback(async () => setRuns(await listRuns()), []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  // While anything is in flight, keep the archive live.
  const anyRunning = runs?.some((r) => r.status === "running" || r.status === "queued");
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => document.visibilityState === "visible" && load(), 5000);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const open = async (r: RunItem) => {
    if (r.status === "running" || r.status === "queued") {
      onAttach(r.id, r.url || r.brand || "", (r.mode as "fast" | "refine") || "fast");
      return;
    }
    if (r.status !== "done") return;
    setLoadingId(r.id);
    try {
      const data = await getRun(r.id);
      if (data.result) onSelectRun(data.result);
    } catch (err) {
      console.error("Failed to load run:", err);
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <section id="recent-runs" className="w-full max-w-6xl mx-auto px-4 sm:px-6 py-14">
      <div className="flex items-end justify-between mb-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Library</h2>
          <p className="text-sm text-muted mt-1">Everything you&rsquo;ve created, in one place.</p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-full text-[13px] font-medium border border-line bg-surface hover:border-line-strong transition-colors cursor-pointer"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.6m14.8 2A8 8 0 004.6 9m0 0H9m11 11v-5h-.6m0 0a8 8 0 01-15.4-2m15.4 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {runs === null ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[132px] rounded-2xl border border-line bg-surface p-5 space-y-3">
              <div className="h-4 w-1/2 rounded skeleton" />
              <div className="h-3 w-3/4 rounded skeleton" />
            </div>
          ))}
        </div>
      ) : runs.length === 0 ? (
        <div className="p-10 rounded-2xl bg-surface border border-dashed border-line-strong text-center">
          <div className="font-medium">Nothing here yet</div>
          <p className="text-sm text-muted mt-1">Paste a website above and your first posts will show up here.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {runs.map((r) => {
            const running = r.status === "running" || r.status === "queued";
            const selected = selectedTaskId === r.task_id || selectedTaskId === r.id || activeJobId === r.id;
            const stage = STAGES.find((s) => s.id === r.stage);
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => open(r)}
                disabled={r.status === "failed" || r.status === "cancelled"}
                className={`group text-left p-5 rounded-2xl border bg-surface transition-all cursor-pointer disabled:cursor-default flex flex-col justify-between min-h-[132px] ${
                  selected ? "border-ink shadow-lift" : "border-line hover:border-line-strong hover:shadow-card hover:-translate-y-0.5"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-[15px] truncate">{r.brand && !r.brand.includes("//") ? r.brand : host(r)}</span>
                    {running ? (
                      <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full bg-brand-tint text-brand-deep border border-amber-200 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-brand animate-breathe" />
                        {stage?.short || "Creating"}
                      </span>
                    ) : r.status === "cancelled" ? (
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-sunken text-muted border border-line shrink-0">Stopped</span>
                    ) : r.status === "failed" ? (
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-sunken text-muted border border-line shrink-0">Didn&rsquo;t finish</span>
                    ) : (
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-ok-tint text-ok border border-emerald-200 shrink-0">
                        {r.verified_posts} post{r.verified_posts === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                  <div className="text-[13px] text-muted mt-1 truncate">{host(r)}</div>
                </div>
                <div className="mt-4 flex items-center justify-between text-[12px] text-faint">
                  <span>
                    {ago(r.created_at)}
                  </span>
                  <span className="text-ink-soft font-medium group-hover:text-ink">
                    {loadingId === r.id ? "Opening…" : running ? "Follow →" : r.status === "done" ? "View →" : ""}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
