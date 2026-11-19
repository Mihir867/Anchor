"use client";

import React, { useEffect, useRef, useState } from "react";
import type { RunJobState } from "@/lib/useRunJob";
import { STAGES, TIPS, estimatePercent, formatDuration, stageDetail, stageIndex } from "@/lib/stages";

interface RunProgressProps {
  state: RunJobState;
  onReset: () => void;
  onRetry: () => void;
}

function hostOf(url: string | null) {
  if (!url) return "";
  try {
    return new URL(url.includes("//") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function RunProgress({ state, onReset, onRetry }: RunProgressProps) {
  const { phase, job, startedAt, failures } = state;
  const progress = job?.progress;
  const stage = phase === "starting" ? "queued" : job?.stage || job?.status || "queued";
  const current = stageIndex(stage);
  const target = progress?.target || job?.request?.posts || 3;
  const name = progress?.brand || hostOf(state.url);

  // 1s clock for elapsed time and the eased progress bar.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // When did we first see the current stage (for easing within a stage)?
  const stageSeen = useRef<{ stage: string; at: number }>({ stage, at: Date.now() });
  if (stageSeen.current.stage !== stage) stageSeen.current = { stage, at: Date.now() };
  const secsInStage = (now - stageSeen.current.at) / 1000;

  // Headlines the engine reported while writing, by post number, so drafts appear one by one.
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

  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;
  const [tip, setTip] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 7000);
    return () => clearInterval(t);
  }, []);

  // Live tab title so a backgrounded tab still shows where the run is.
  useEffect(() => {
    if (phase !== "active" && phase !== "starting") return;
    const label = current >= 0 && current < STAGES.length ? STAGES[current].short : "Queued";
    document.title = `${pct}% · ${label} · ${name || "Anchor"} — Anchor`;
  }, [pct, current, name, phase]);

  const [notify, setNotify] = useState<NotificationPermission | "unsupported">("default");
  useEffect(() => {
    setNotify(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  if (phase === "failed") {
    return (
      <div className="rounded-3xl bg-surface border border-red-200 shadow-lift p-6 sm:p-8 animate-fade-up">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-red-50 text-bad flex items-center justify-center shrink-0">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
              <path d="M12 8v5m0 3h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-lg font-semibold">We couldn&rsquo;t finish {name || "this run"}</div>
            <p className="mt-1 text-sm text-muted break-words">{state.error || "The run failed."}</p>
            <div className="mt-4 flex gap-2">
              <button type="button" onClick={onRetry} className="h-9 px-4 rounded-full bg-ink text-white text-[13px] font-medium hover:bg-ink-soft cursor-pointer">
                Try again
              </button>
              <button type="button" onClick={onReset} className="h-9 px-4 rounded-full border border-line text-[13px] font-medium hover:bg-sunken cursor-pointer">
                Dismiss
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-3xl bg-surface border border-line shadow-lift overflow-hidden animate-fade-up">
      {/* Top: title + bar */}
      <div className="px-6 sm:px-8 pt-6 pb-5 border-b border-line">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[12px] font-medium text-brand-deep">
              <span className="relative flex w-2 h-2">
                <span className="absolute inset-0 rounded-full bg-brand animate-ping opacity-60" />
                <span className="relative w-2 h-2 rounded-full bg-brand" />
              </span>
              {stage === "queued" ? "Starting up" : "Live"} · {formatDuration(elapsed)} elapsed
            </div>
            <h3 className="mt-1.5 text-xl sm:text-2xl font-semibold tracking-tight truncate">
              Creating posts for {name || "your brand"}
            </h3>
            <p className="mt-1 text-sm text-muted">
              {current >= 0 && current < STAGES.length ? STAGES[current].title : "Waiting for a free worker"}
              {current >= 0 && current < STAGES.length && stageDetail(STAGES[current].id, progress) && (
                <span className="text-ink-soft"> · {stageDetail(STAGES[current].id, progress)}</span>
              )}
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-3xl font-semibold tabular-nums tracking-tight">{pct}%</div>
            <div className="text-[12px] text-faint">{state.mode === "refine" ? "usually 5–10 min" : "usually 1–3 min"}</div>
          </div>
        </div>
        <div className="mt-4 h-2 rounded-full bg-sunken overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-amber-400 to-orange-500 transition-[width] duration-1000 ease-out relative overflow-hidden"
            style={{ width: `${Math.max(pct, 2)}%` }}
          >
            <span className="absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.45),transparent)] bg-[length:200px_100%] animate-shimmer" />
          </div>
        </div>
        {failures > 2 && (
          <div className="mt-3 text-[12px] text-brand-deep">Connection hiccup. Still checking on your run…</div>
        )}
      </div>

      <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* Stepper */}
        <ol className="p-6 sm:p-8 space-y-1 md:border-r border-line">
          {STAGES.map((s, i) => {
            const state_ = i < current ? "done" : i === current ? "active" : "todo";
            const detail = state_ !== "todo" ? stageDetail(s.id, progress) : null;
            return (
              <li key={s.id} className="relative flex gap-3.5 pb-4 last:pb-0">
                {i < STAGES.length - 1 && (
                  <span className={`absolute left-[11px] top-7 bottom-0 w-px ${i < current ? "bg-ok/40" : "bg-line"}`} />
                )}
                <span
                  className={`relative z-10 mt-0.5 w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-[11px] font-semibold transition-colors ${
                    state_ === "done"
                      ? "bg-ok text-white"
                      : state_ === "active"
                        ? "bg-ink text-white ring-4 ring-amber-100"
                        : "bg-sunken text-faint border border-line"
                  }`}
                >
                  {state_ === "done" ? (
                    <svg className="w-3.5 h-3.5 animate-pop" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                      <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : state_ === "active" ? (
                    <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
                      <path d="M21 12a9 9 0 00-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </span>
                <div className="min-w-0">
                  <div className={`text-[14px] font-medium ${state_ === "todo" ? "text-faint" : "text-ink"}`}>{s.title}</div>
                  {detail && <div className="text-[12px] text-muted mt-0.5 animate-fade-up">{detail}</div>}
                </div>
              </li>
            );
          })}
        </ol>

        {/* Drafts taking shape */}
        <div className="p-6 sm:p-8 bg-sunken/50 space-y-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Your posts</div>
          <div className="space-y-2.5">
            {Array.from({ length: target }, (_, i) => i + 1).map((n) => {
              const headline = drafts[n];
              const writing = stage === "writing" && progress?.post === n;
              // Earlier posts are finished even if we joined late and never saw their headline.
              const drafted = !writing && (!!headline || (progress?.post ?? 0) > n || current > 3);
              return (
                <div
                  key={n}
                  className={`p-3.5 rounded-2xl bg-surface border transition-all ${writing ? "border-amber-300 shadow-card" : "border-line"}`}
                >
                  <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-wide">
                    <span className="text-muted">Post {n}</span>
                    {writing ? (
                      <span className="text-brand-deep animate-breathe">Writing &amp; fact-checking</span>
                    ) : drafted ? (
                      <span className="text-ok">Drafted</span>
                    ) : (
                      <span className="text-faint">Up next</span>
                    )}
                  </div>
                  {headline ? (
                    <div className="mt-1.5 text-[14px] font-medium leading-snug line-clamp-2 animate-fade-up">{headline}</div>
                  ) : drafted ? (
                    <div className="mt-1.5 text-[13px] text-muted">Draft finished. Shows up with the results.</div>
                  ) : (
                    <div className="mt-2 space-y-1.5">
                      <div className="h-3 rounded skeleton w-[85%]" />
                      <div className="h-3 rounded skeleton w-[55%]" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="pt-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint mb-1.5">While you wait</div>
            <p key={tip} className="text-[13px] text-ink-soft leading-relaxed min-h-[40px] animate-fade-up">
              {TIPS[tip]}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            {notify === "default" && (
              <button
                type="button"
                onClick={() => Notification.requestPermission().then(setNotify)}
                className="h-8 px-3 rounded-full bg-surface border border-line text-[12px] font-medium hover:border-line-strong cursor-pointer inline-flex items-center gap-1.5"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Notify me when it&rsquo;s ready
              </button>
            )}
            {notify === "granted" && <span className="text-[12px] text-ok font-medium">✓ We&rsquo;ll notify you when it&rsquo;s done</span>}
            <span className="text-[12px] text-muted">You can leave this page. The run keeps going and gets saved to your library.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
