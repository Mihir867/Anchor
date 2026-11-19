"use client";

import React, { useEffect, useRef, useState } from "react";
import type { RunJobState } from "@/lib/useRunJob";
import { STAGES, TIPS, estimatePercent, stageDetail, stageIndex } from "@/lib/stages";

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

const RING = 2 * Math.PI * 52;

export function RunProgress({ state, onReset, onRetry }: RunProgressProps) {
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

  const [tip, setTip] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 6500);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (phase !== "active" && phase !== "starting") return;
    document.title = `${pct}% · ${name || "Your posts"} — Anchor`;
  }, [pct, name, phase]);

  if (phase === "failed") {
    return (
      <div className="rounded-[28px] bg-surface border border-line shadow-lift p-8 sm:p-10 text-center animate-fade-up">
        <div className="mx-auto w-12 h-12 rounded-2xl bg-red-50 text-bad flex items-center justify-center">
          <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M12 8v5m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="mt-4 text-xl font-semibold tracking-tight">We hit a snag{name ? ` with ${name}` : ""}</div>
        <p className="mt-1.5 text-sm text-muted max-w-sm mx-auto">{state.error || "Something went wrong. Please try again."}</p>
        <div className="mt-6 flex justify-center gap-2">
          <button type="button" onClick={onRetry} className="h-10 px-5 rounded-full bg-ink text-white text-[13px] font-semibold hover:bg-ink-soft cursor-pointer">
            Try again
          </button>
          <button type="button" onClick={onReset} className="h-10 px-5 rounded-full border border-line text-[13px] font-medium hover:bg-sunken cursor-pointer">
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  const active = current >= 0 && current < STAGES.length ? STAGES[current] : null;
  const detail = active ? stageDetail(active.id, progress) : null;

  return (
    <div className="relative rounded-[28px] bg-surface border border-line shadow-lift overflow-hidden animate-fade-up">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -right-32 w-[520px] h-[420px] bg-[radial-gradient(ellipse_at_center,rgba(251,191,36,0.16),transparent_65%)]"
      />

      <div className="relative grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* Left: ring + current step */}
        <div className="p-7 sm:p-10 flex flex-col items-center md:items-start text-center md:text-left">
          <div className="relative w-32 h-32">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120" aria-hidden>
              <defs>
                <linearGradient id="anchor-ring" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#fbbf24" />
                  <stop offset="100%" stopColor="#f97316" />
                </linearGradient>
              </defs>
              <circle cx="60" cy="60" r="52" fill="none" stroke="var(--color-sunken)" strokeWidth="8" />
              <circle
                cx="60"
                cy="60"
                r="52"
                fill="none"
                stroke="url(#anchor-ring)"
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={RING}
                strokeDashoffset={RING * (1 - Math.max(pct, 2) / 100)}
                className="transition-[stroke-dashoffset] duration-1000 ease-out"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-3xl font-semibold tabular-nums tracking-tight">{pct}%</span>
            </div>
          </div>

          <div className="mt-6 text-[12px] font-medium text-brand-deep inline-flex items-center gap-2">
            <span className="relative flex w-2 h-2">
              <span className="absolute inset-0 rounded-full bg-brand animate-ping opacity-60" />
              <span className="relative w-2 h-2 rounded-full bg-brand" />
            </span>
            Creating for {name || "your brand"}
          </div>
          <h3 key={active?.id ?? "start"} className="mt-2 text-2xl sm:text-[28px] leading-tight font-semibold tracking-tight animate-fade-up">
            {active ? active.title : "Getting things ready"}
            <span className="inline-block w-6 text-left animate-breathe">…</span>
          </h3>
          <p className="mt-1.5 text-sm text-muted min-h-5">{detail}</p>

          {/* Step track */}
          <div className="mt-7 w-full flex items-center gap-1.5" aria-label={`Step ${Math.max(current + 1, 1)} of ${STAGES.length}`}>
            {STAGES.map((s, i) => (
              <span
                key={s.id}
                title={s.title}
                className={`h-1.5 flex-1 rounded-full transition-colors duration-700 ${
                  i < current ? "bg-ink" : i === current ? "bg-gradient-to-r from-amber-400 to-orange-500 animate-breathe" : "bg-sunken"
                }`}
              />
            ))}
          </div>

          {failures > 2 && <div className="mt-3 text-[12px] text-brand-deep">Reconnecting…</div>}
        </div>

        {/* Right: posts taking shape */}
        <div className="p-7 sm:p-10 md:border-l border-t md:border-t-0 border-line bg-sunken/40">
          <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-faint">Your posts</div>
          <div className="mt-3 space-y-2.5">
            {Array.from({ length: target }, (_, i) => i + 1).map((n) => {
              const headline = drafts[n];
              const writing = stage === "write" && progress?.post === n;
              const ready = !writing && (!!headline || (progress?.post ?? 0) > n || current > 3);
              return (
                <div
                  key={n}
                  className={`p-4 rounded-2xl bg-surface border transition-all duration-500 ${
                    writing ? "border-amber-300 shadow-card -translate-y-0.5" : "border-line"
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-wide">
                    <span className="text-muted">Post {n}</span>
                    {writing ? (
                      <span className="text-brand-deep animate-breathe">Writing</span>
                    ) : ready ? (
                      <span className="text-ok inline-flex items-center gap-1">
                        <svg className="w-3 h-3 animate-pop" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                          <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        Ready
                      </span>
                    ) : null}
                  </div>
                  {headline ? (
                    <div className="mt-1.5 text-[14px] font-medium leading-snug line-clamp-2 animate-fade-up">{headline}</div>
                  ) : (
                    <div className="mt-2.5 space-y-1.5">
                      <div className="h-3 rounded skeleton w-[85%]" />
                      <div className="h-3 rounded skeleton w-[55%]" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <p key={tip} className="mt-6 text-[13px] text-ink-soft leading-relaxed min-h-[40px] animate-fade-up">
            {TIPS[tip]}
          </p>
        </div>
      </div>
    </div>
  );
}
