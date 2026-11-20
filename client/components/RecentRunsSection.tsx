"use client";

import React, { useCallback, useEffect, useState } from "react";
import { fetchRuns, RunItem, getRun, RunResult } from "@/lib/api";
import { STAGES } from "@/lib/stages";
import { Button } from "./ui/button";
import { ChevronRightIcon, RefreshIcon, Spinner, Status } from "./ui/icons";

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
  if (s < 60) return "Just now";
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

// Shared column layout for the header, rows and skeleton rows.
const COLS = "grid grid-cols-[minmax(0,1fr)_auto_20px] sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_150px_96px_20px] items-center gap-4";

function RunStatus({ r }: { r: RunItem }) {
  if (r.status === "running" || r.status === "queued") {
    const stage = STAGES.find((s) => s.id === r.stage);
    return (
      <span className="inline-flex items-center gap-2 text-[13px] text-fg-2 whitespace-nowrap">
        <Spinner className="w-3 h-3 text-fg-3" />
        {r.status === "queued" ? "Queued" : stage?.short || "Creating"}
      </span>
    );
  }
  if (r.status === "cancelled") return <Status tone="neutral">Stopped</Status>;
  if (r.status === "failed") return <Status tone="danger">Didn&rsquo;t finish</Status>;
  return (
    <Status tone="success">
      <span className="tabular-nums">
        {r.verified_posts} post{r.verified_posts === 1 ? "" : "s"}
      </span>
    </Status>
  );
}

export function RecentRunsSection({ onSelectRun, onAttach, selectedTaskId, activeJobId, refreshKey }: RecentRunsSectionProps) {
  const [runs, setRuns] = useState<RunItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRuns(await fetchRuns());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  // While anything is in flight, keep the library live.
  const anyRunning = runs?.some((r) => r.status === "running" || r.status === "queued");
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => document.visibilityState === "visible" && load(), 5000);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const open = async (r: RunItem) => {
    setOpenError(null);
    if (r.status === "running" || r.status === "queued") {
      onAttach(r.id, r.url || r.brand || "", (r.mode as "fast" | "refine") || "fast");
      return;
    }
    if (r.status !== "done") return;
    setLoadingId(r.id);
    try {
      const data = await getRun(r.id);
      if (data.result) onSelectRun(data.result);
    } catch {
      setOpenError(`Couldn't open the posts for ${host(r)}. Check your connection and try again.`);
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <section id="recent-runs" className="w-full max-w-[1120px] mx-auto px-5 sm:px-8 py-16 sm:py-24">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl leading-[1.25] font-semibold tracking-[-0.015em]">Library</h2>
          <p className="mt-1 text-sm text-fg-2">Every set of posts you have created.</p>
        </div>
        <Button variant="secondary" onClick={refresh} loading={refreshing}>
          {!refreshing && <RefreshIcon className="w-3.5 h-3.5" />}
          Refresh
        </Button>
      </header>

      {openError && (
        <p className="mt-4 text-[13px] text-danger" role="alert">
          {openError}
        </p>
      )}

      <div className="mt-6">
        <div className={`${COLS} h-9 border-b border-border text-[13px] font-medium text-fg-3`}>
          <span>Brand</span>
          <span className="hidden sm:block">Website</span>
          <span className="text-right sm:text-left">Status</span>
          <span className="hidden sm:block text-right">Created</span>
          <span />
        </div>

        {runs === null && !failed ? (
          <ul aria-busy="true" aria-label="Loading library">
            {[92, 78, 60].map((w) => (
              <li key={w} className={`${COLS} h-12 border-b border-border-subtle`}>
                <span className="h-3.5 skeleton" style={{ width: `${w}%` }} />
                <span className="hidden sm:block h-3.5 skeleton w-[70%]" />
                <span className="h-3.5 skeleton w-16" />
                <span className="hidden sm:block h-3.5 skeleton w-14 ml-auto" />
                <span />
              </li>
            ))}
          </ul>
        ) : failed && !runs ? (
          <div className="py-10 max-w-[480px]">
            <div className="text-sm font-medium text-fg">Couldn&rsquo;t load your library</div>
            <p className="mt-1 text-sm text-fg-2">The server didn&rsquo;t respond. Check your connection, then try again.</p>
            <Button variant="secondary" className="mt-4" onClick={refresh} loading={refreshing}>
              Try again
            </Button>
          </div>
        ) : runs && runs.length === 0 ? (
          <div className="py-10 max-w-[480px]">
            <div className="text-sm font-medium text-fg">No posts yet</div>
            <p className="mt-1 text-sm text-fg-2">
              Each set of posts you create appears here, so you can come back to copy or export it later.
            </p>
            <a
              href="#generator"
              className="mt-4 inline-block text-sm font-medium text-accent hover:underline underline-offset-2 rounded-sm"
            >
              Create your first posts
            </a>
          </div>
        ) : (
          <ul>
            {runs!.map((r) => {
              const running = r.status === "running" || r.status === "queued";
              const openable = running || r.status === "done";
              const selected = selectedTaskId === r.task_id || selectedTaskId === r.id || activeJobId === r.id;
              const name = r.brand && !r.brand.includes("//") ? r.brand : host(r);
              const cells = (
                <>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-fg" title={name}>
                      {name}
                    </span>
                    <span className="sm:hidden block truncate text-[13px] text-fg-3">
                      {host(r)}, {ago(r.created_at).toLowerCase()}
                    </span>
                  </span>
                  <span className="hidden sm:block truncate text-sm text-fg-2" title={host(r)}>
                    {host(r)}
                  </span>
                  <span className="justify-self-end sm:justify-self-start">
                    {loadingId === r.id ? (
                      <span className="inline-flex items-center gap-2 text-[13px] text-fg-2">
                        <Spinner className="w-3 h-3 text-fg-3" />
                        Opening
                      </span>
                    ) : (
                      <RunStatus r={r} />
                    )}
                  </span>
                  <span className="hidden sm:block text-right text-[13px] text-fg-3 tabular-nums whitespace-nowrap">
                    {ago(r.created_at)}
                  </span>
                  <span className="text-fg-3">{openable && <ChevronRightIcon className="w-4 h-4" />}</span>
                </>
              );
              return (
                <li key={r.id} className="border-b border-border-subtle">
                  {openable ? (
                    <button
                      type="button"
                      onClick={() => open(r)}
                      aria-current={selected || undefined}
                      aria-label={`${running ? "Follow" : "Open"} posts for ${name}`}
                      className={`${COLS} w-full h-12 pointer-coarse:h-[52px] px-3 -mx-3 box-content text-left rounded-md cursor-pointer transition-colors duration-[120ms] ease-out ${
                        selected ? "bg-accent-subtle" : "hover:bg-bg-subtle active:bg-bg-muted"
                      }`}
                    >
                      {cells}
                    </button>
                  ) : (
                    <div className={`${COLS} h-12 pointer-coarse:h-[52px]`}>{cells}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
