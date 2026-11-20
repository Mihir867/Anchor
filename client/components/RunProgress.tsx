"use client";

import React, { useEffect, useRef, useState } from "react";
import type { RunJobState } from "@/lib/useRunJob";
import { STAGES, estimatePercent, stageDetail, stageIndex } from "@/lib/stages";
import { Button } from "./ui/button";
import { CheckIcon, Spinner } from "./ui/icons";

interface RunProgressProps {
  state: RunJobState;
  onReset: () => void;
  onRetry: () => void;
  /** Stop the run in flight. Rejects if the stop could not be recorded. */
  onCancel: () => Promise<void>;
}

function hostOf(url: string | null) {
  if (!url) return "";
  try {
    return new URL(url.includes("//") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function RunProgress({ state, onReset, onRetry, onCancel }: RunProgressProps) {
  const { phase, job, failures } = state;
  const progress = job?.progress;
  const stage = phase === "starting" ? "queued" : job?.stage || job?.status || "queued";
  const current = stageIndex(stage);
  const target = progress?.target || job?.request?.posts || 3;
  const name = progress?.brand || hostOf(state.url);

  // 1s clock for the eased progress bar.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const stageSeen = useRef<{ stage: string; at: number }>({ stage, at: Date.now() });
  if (stageSeen.current.stage !== stage) stageSeen.current = { stage, at: Date.now() };
  const secsInStage = (now - stageSeen.current.at) / 1000;

  // Headlines reported while writing, by post number, so drafts appear one by one.
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  useEffect(() => setDrafts({}), [state.jobId]); // must run before the effect below
  useEffect(() => {
    if (progress?.post && progress.headline) {
      setDrafts((d) => (d[progress.post!] === progress.headline ? d : { ...d, [progress.post!]: progress.headline! }));
    }
  }, [progress?.post, progress?.headline]);

  // Percent never moves backwards, even if a poll arrives out of order.
  const raw = phase === "done" ? 100 : estimatePercent(stage, progress, secsInStage);
  const best = useRef(0);
  useEffect(() => {
    best.current = 0;
  }, [state.jobId]);
  best.current = Math.max(best.current, raw);
  const pct = best.current;

  // Stop: ask once, inline, then stop.
  const [confirming, setConfirming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setConfirming(false);
    setStopping(false);
    setStopError(null);
  }, [state.jobId]);
  useEffect(() => {
    if (!confirming) return;
    keepRef.current?.focus(); // focus the safe choice
    const t = setTimeout(() => setConfirming(false), 6000);
    return () => clearTimeout(t);
  }, [confirming]);
  const stop = async () => {
    setStopping(true);
    setStopError(null);
    try {
      await onCancel();
    } catch (err) {
      setStopError(err instanceof Error ? err.message : "Couldn't stop the run. Try again.");
      setStopping(false);
      setConfirming(false);
    }
  };

  useEffect(() => {
    if (phase !== "active" && phase !== "starting") return;
    document.title = `${pct}% · ${name || "Your posts"} — Anchor`;
  }, [pct, name, phase]);

  if (phase === "failed") {
    return (
      <div className="rounded-lg border border-border p-6 sm:p-8 animate-fade-up" role="alert">
        <h2 className="text-lg leading-[1.35] font-semibold tracking-[-0.01em]">
          Couldn&rsquo;t create posts{name ? ` for ${name}` : ""}
        </h2>
        <p className="mt-1 max-w-[560px] text-sm text-fg-2">
          {state.error || "The run stopped before any posts were ready. Try again, or try another page of the same site."}
        </p>
        <div className="mt-5 flex gap-2">
          <Button onClick={onRetry}>Try again</Button>
          <Button variant="secondary" onClick={onReset}>
            Dismiss
          </Button>
        </div>
      </div>
    );
  }

  const active = current >= 0 && current < STAGES.length ? STAGES[current] : null;
  const detail = active ? stageDetail(active.id, progress) : null;
  const step = Math.max(current + 1, 1);

  return (
    <div className="relative rounded-lg border border-border overflow-hidden animate-fade-up">
      {/* 2px determinate bar along the top edge */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-border-subtle" aria-hidden>
        <div
          className="h-full bg-accent origin-left transition-transform duration-[240ms] ease-out"
          style={{ transform: `scaleX(${Math.max(pct, 2) / 100})` }}
        />
      </div>

      <header className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 px-5 sm:px-6 pt-6 pb-5 border-b border-border-subtle">
        <div className="min-w-0">
          <h2 className="text-lg leading-[1.35] font-semibold tracking-[-0.01em] truncate">
            Creating posts for {name || "your brand"}
          </h2>
          <p className="mt-1 text-sm text-fg-2" aria-live="polite">
            <span className="tabular-nums">
              Step {Math.min(step, STAGES.length)} of {STAGES.length}
            </span>
            {", "}
            {active ? active.title.toLowerCase() : "getting ready"}
            {detail ? `. ${detail}` : ""}
          </p>
          {failures > 2 && <p className="mt-1 text-[13px] text-warning">Lost connection to the server. Reconnecting.</p>}
          {stopError && <p className="mt-1 text-[13px] text-danger">{stopError}</p>}
        </div>

        {state.jobId && (
          <div className="flex items-center gap-2 shrink-0">
            {confirming ? (
              <>
                <span className="text-[13px] text-fg-2 mr-1">Stop creating these posts?</span>
                <Button ref={keepRef} variant="secondary" onClick={() => setConfirming(false)} disabled={stopping}>
                  Keep going
                </Button>
                <Button variant="destructive" onClick={stop} loading={stopping}>
                  {stopping ? "Stopping" : "Stop run"}
                </Button>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setConfirming(true)}>
                Stop
              </Button>
            )}
          </div>
        )}
      </header>

      <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        {/* Steps */}
        <ol className="px-5 sm:px-6 py-4 md:border-r border-b md:border-b-0 border-border-subtle" aria-label="Steps">
          {STAGES.map((s, i) => {
            const done = i < current;
            const now_ = i === current;
            return (
              <li key={s.id} className="flex items-center gap-3 h-9" aria-current={now_ ? "step" : undefined}>
                <span className="w-4 flex justify-center">
                  {done ? (
                    <CheckIcon className="w-4 h-4 text-success" />
                  ) : now_ ? (
                    <Spinner className="w-3.5 h-3.5 text-accent" />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-border-strong" aria-hidden />
                  )}
                </span>
                <span className={`text-sm transition-colors duration-[120ms] ${now_ ? "text-fg font-medium" : done ? "text-fg-2" : "text-fg-3"}`}>
                  {s.title}
                </span>
              </li>
            );
          })}
        </ol>

        {/* Posts taking shape */}
        <div className="px-5 sm:px-6 py-4">
          <h3 className="text-[13px] font-medium text-fg-3 h-9 flex items-center">Posts</h3>
          <ul className="border-t border-border-subtle">
            {/* Extra rows appear when the engine writes backfill posts beyond the target. */}
            {Array.from({ length: Math.max(target, progress?.post ?? 0) }, (_, i) => i + 1).map((n) => {
              const headline = drafts[n];
              const writing = stage === "write" && progress?.post === n;
              const drafted = !writing && (!!headline || (progress?.post ?? 0) > n || current > 3);
              return (
                <li key={n} className="flex items-center gap-4 h-12 border-b border-border-subtle">
                  <span className="w-12 shrink-0 text-[13px] text-fg-3 tabular-nums">Post {n}</span>
                  <span className="min-w-0 flex-1">
                    {headline ? (
                      <span className="block truncate text-sm font-medium text-fg animate-fade" title={headline}>
                        {headline}
                      </span>
                    ) : drafted ? (
                      // Opened mid-run: this headline was reported before we started following.
                      <span className="block truncate text-[13px] text-fg-3">Headline shown when the run finishes</span>
                    ) : (
                      <span className="block h-3.5 skeleton" style={{ width: `${[78, 64, 70][(n - 1) % 3]}%` }} />
                    )}
                  </span>
                  <span className="w-[76px] shrink-0 flex justify-end">
                    {writing ? (
                      <span className="inline-flex items-center gap-1.5 text-[13px] text-fg-2">
                        <Spinner className="w-3 h-3 text-fg-3" />
                        Writing
                      </span>
                    ) : drafted ? (
                      <span className="inline-flex items-center gap-1.5 text-[13px] text-fg-2">
                        <CheckIcon className="w-3.5 h-3.5 text-success" />
                        Drafted
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-4 text-[13px] text-fg-3">
            You can leave this page. The run continues and appears in your library when it finishes.
          </p>
        </div>
      </div>
    </div>
  );
}
