"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Navbar } from "@/components/Navbar";
import { HeroSection } from "@/components/HeroSection";
import { RunResultView } from "@/components/RunResultView";
import { RunProgress } from "@/components/RunProgress";
import { RecentRunsSection } from "@/components/RecentRunsSection";
import { RunResult, listRuns, getRun } from "@/lib/api";
import { StartPayload, useRunJob } from "@/lib/useRunJob";
import { STAGES } from "@/lib/stages";

const BASE_TITLE = "Anchor — On-brand social posts from your website";

export default function Home() {
  const [current, setCurrent] = useState<RunResult | null>(null);
  const [fresh, setFresh] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const lastPayload = useRef<StartPayload | null>(null);

  const scrollToLive = () => setTimeout(() => liveRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);

  const handleDone = useCallback((result: RunResult) => {
    setCurrent(result);
    setFresh(true);
    setRefreshKey((k) => k + 1);
    scrollToLive();
    if (document.visibilityState === "hidden") {
      document.title = `✓ Posts ready for ${result.brand} — Anchor`;
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        const n = new Notification("Your posts are ready", {
          body: `${result.verified_posts} post${result.verified_posts === 1 ? "" : "s"} for ${result.brand}`,
        });
        n.onclick = () => {
          window.focus();
          n.close();
        };
      }
    } else {
      document.title = BASE_TITLE;
    }
  }, []);

  const { state, start, attach, reset } = useRunJob(handleDone);
  const busy = state.phase === "starting" || state.phase === "active";

  // Restore the normal title when the user comes back to the tab.
  useEffect(() => {
    const back = () => {
      if (document.visibilityState === "visible" && !busy) document.title = BASE_TITLE;
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [busy]);
  useEffect(() => {
    if (state.phase === "idle" || state.phase === "failed") document.title = BASE_TITLE;
  }, [state.phase]);

  // Keep ?run=<id> in the URL so a run can be bookmarked or shared.
  const [ready, setReady] = useState(false);
  const linkedId = state.jobId ?? current?.task_id ?? null;
  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    if (linkedId) url.searchParams.set("run", linkedId);
    else url.searchParams.delete("run");
    window.history.replaceState(null, "", url);
  }, [linkedId, ready]);

  // First visit: open ?run=<id> if given (following it if still running), else the latest run.
  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      const wanted = new URLSearchParams(window.location.search).get("run");
      if (wanted) {
        try {
          const job = await getRun(wanted);
          if (cancelled) return;
          if (job.status === "running" || job.status === "queued") {
            attach(job.job_id, job.request?.url || wanted, job.request?.mode || "fast");
            return;
          }
          if (job.result) {
            setCurrent((c) => c ?? job.result!);
            return;
          }
        } catch {
          // unknown id: fall back to the latest run
        }
      }
      const runs = await listRuns();
      const latest = runs.find((r) => r.status === "done" && r.verified_posts > 0);
      if (!latest || cancelled) return;
      try {
        const detail = await getRun(latest.id);
        if (!cancelled && detail.result) setCurrent((c) => c ?? detail.result!);
      } catch {
        // the library still lists it
      }
    };
    init().finally(() => !cancelled && setReady(true));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onStart = (payload: StartPayload) => {
    lastPayload.current = payload;
    setFresh(false);
    start(payload);
    setRefreshKey((k) => k + 1);
    scrollToLive();
  };

  const onRetry = () => {
    const p = lastPayload.current ?? (state.url ? { url: state.url, mode: state.mode, posts: 3 } : null);
    if (p) onStart(p);
  };

  const stageIdx = STAGES.findIndex((s) => s.id === state.job?.stage);
  const activeLabel = busy ? (stageIdx >= 0 ? STAGES[stageIdx].short : "Starting") : null;
  const showProgress = state.phase === "starting" || state.phase === "active" || state.phase === "failed";

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar activeLabel={activeLabel} />

      <main className="flex-1 flex flex-col">
        <HeroSection onStart={onStart} busy={busy} />

        {(showProgress || current) && (
          <section ref={liveRef} id="live-run" className="w-full max-w-6xl mx-auto px-4 sm:px-6 scroll-mt-24">
            {showProgress ? (
              <RunProgress
                state={state}
                onRetry={onRetry}
                onReset={() => {
                  reset();
                }}
              />
            ) : (
              current && (
                <RunResultView
                  key={current.task_id}
                  result={current}
                  fresh={fresh}
                  onClose={() => {
                    setCurrent(null);
                    setFresh(false);
                    reset();
                  }}
                />
              )
            )}
          </section>
        )}

        <RecentRunsSection
          refreshKey={refreshKey}
          activeJobId={busy ? state.jobId : null}
          selectedTaskId={current?.task_id}
          onSelectRun={(r) => {
            setCurrent(r);
            setFresh(false);
            if (!busy) reset();
            if (!busy) scrollToLive();
          }}
          onAttach={(id, url, mode) => {
            attach(id, url, mode);
            scrollToLive();
          }}
        />

        <section id="features" className="max-w-6xl mx-auto px-4 sm:px-6 py-20 w-full border-t border-line">
          <div className="text-center max-w-xl mx-auto mb-12">
            <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight">Posts you can stand behind.</h2>
            <p className="mt-3 text-muted leading-relaxed">
              Real stories from your brand, written to perform and designed to look like you.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {[
              {
                title: "Grounded in your story",
                body: "Every post is built from what your brand has actually done: launches, customers, milestones and press. Each one links to its sources.",
                foot: "Sources included",
                icon: "M9 12l2 2 4-4m5.6-4.1A12 12 0 0112 3a12 12 0 01-8.6 2.9A12 12 0 003 9c0 5.6 3.8 10.3 9 11.6 5.2-1.3 9-6 9-11.6 0-1-.1-2.1-.4-3.1z",
              },
              {
                title: "Written for each channel",
                body: "A LinkedIn post and an Instagram caption for every story, with hooks that land before \u201csee more\u201d and hashtags that fit.",
                foot: "LinkedIn + Instagram",
                icon: "M8 10h8M8 14h5m-9 6l3-3h10a3 3 0 003-3V7a3 3 0 00-3-3H7a3 3 0 00-3 3v13z",
              },
              {
                title: "Designed on-brand",
                body: "Carousel slides in your own colors and typography, sized for the feed and ready to upload.",
                foot: "Your colors, your type",
                icon: "M4 5a1 1 0 011-1h14a1 1 0 011 1v14a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm4 11l3-3 2 2 3-4 2 3",
              },
            ].map((f) => (
              <div
                key={f.title}
                className="group p-7 rounded-3xl bg-surface border border-line shadow-card flex flex-col justify-between transition-all hover:-translate-y-0.5 hover:shadow-lift"
              >
                <div>
                  <span className="w-10 h-10 rounded-2xl bg-brand-tint text-brand-deep flex items-center justify-center">
                    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                      <path d={f.icon} />
                    </svg>
                  </span>
                  <h3 className="mt-5 text-lg font-semibold tracking-tight">{f.title}</h3>
                  <p className="mt-2 text-[14px] text-muted leading-relaxed">{f.body}</p>
                </div>
                <div className="mt-6 pt-4 border-t border-line text-[12px] text-faint flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-ok" />
                  {f.foot}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5 rounded-3xl border border-line bg-gradient-to-br from-amber-50 via-surface to-orange-50 p-8 sm:p-10">
            <div className="grid sm:grid-cols-3 gap-6">
              {[
                ["1", "Paste your website", "Any company site works, from a startup landing page to a global brand."],
                ["2", "We craft your posts", "Stories, copy and visuals, put together for you."],
                ["3", "Copy and publish", "One click to copy, or export the whole set."],
              ].map(([n, t, b]) => (
                <div key={n} className="flex gap-3.5">
                  <span className="w-7 h-7 shrink-0 rounded-full bg-ink text-white text-[12px] font-semibold flex items-center justify-center">{n}</span>
                  <div>
                    <div className="font-semibold tracking-tight">{t}</div>
                    <p className="mt-1 text-[14px] text-muted leading-relaxed">{b}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="w-full border-t border-line py-8 text-[13px] text-muted">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-ink">Anchor</span>
            <span>Social posts, ready to publish</span>
          </div>
          <a href="#generator" className="hover:text-ink">
            Create posts ↑
          </a>
        </div>
      </footer>
    </div>
  );
}
