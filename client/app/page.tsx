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

// A true sequence, so it is numbered.
const STEPS = [
  { title: "Paste your website", body: "Any company site works, from a one-page startup to a global brand." },
  {
    title: "Anchor reads and writes",
    body: "It reads your pages and recent press, picks the stories worth telling and writes a post for each one.",
  },
  { title: "Review and publish", body: "Check each post against its sources, copy it in one click or export the whole set." },
];

const OUTPUTS = [
  {
    term: "A LinkedIn post",
    body: "Written in your brand's voice, with the hook in the lines people see before \u201csee more\u201d.",
  },
  { term: "An Instagram caption", body: "A shorter version of the same story, with hashtags that fit it." },
  { term: "Carousel slides", body: "Sized for the feed and set in your own colors and typography, ready to upload." },
  { term: "Its sources", body: "A link to every page or article the post is based on, so you can check each claim." },
];

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
      document.title = `Posts ready for ${result.brand} — Anchor`;
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

  const { state, start, attach, reset, cancel } = useRunJob(handleDone);
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

      <main id="main" className="flex-1 flex flex-col">
        <HeroSection onStart={onStart} busy={busy} />

        {(showProgress || current) && (
          <section ref={liveRef} id="live-run" className="w-full max-w-[1120px] mx-auto px-5 sm:px-8 scroll-mt-20">
            {showProgress ? (
              <RunProgress
                state={state}
                onRetry={onRetry}
                onCancel={async () => {
                  await cancel();
                  setRefreshKey((k) => k + 1);
                }}
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

        <section id="how-it-works" className="w-full max-w-[1120px] mx-auto px-5 sm:px-8 py-16 sm:py-24 border-t border-border-subtle">
          <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-x-16 gap-y-8">
            <div>
              <h2 className="text-2xl leading-[1.25] font-semibold tracking-[-0.015em]">How Anchor works</h2>
              <p className="mt-3 max-w-[400px] text-[17px] leading-[1.6] text-fg-2">
                Posts come from what your brand has published and what the press has written about it. Anything Anchor
                can&rsquo;t trace to a source is left out.
              </p>
            </div>
            <ol className="border-t border-border-subtle">
              {STEPS.map((step, i) => (
                <li key={step.title} className="grid grid-cols-[28px_minmax(0,1fr)] sm:grid-cols-[28px_200px_minmax(0,1fr)] gap-x-4 gap-y-1 py-5 border-b border-border-subtle">
                  <span className="text-sm text-fg-3 tabular-nums">{i + 1}</span>
                  <h3 className="text-sm font-medium text-fg">{step.title}</h3>
                  <p className="col-start-2 sm:col-start-3 text-sm leading-[1.6] text-fg-2">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>

          <div className="mt-16 sm:mt-24 grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-x-16 gap-y-8">
            <h2 className="text-2xl leading-[1.25] font-semibold tracking-[-0.015em]">What you get for each post</h2>
            <dl className="border-t border-border-subtle">
              {OUTPUTS.map((o) => (
                <div key={o.term} className="grid sm:grid-cols-[228px_minmax(0,1fr)] gap-x-4 gap-y-1 py-5 border-b border-border-subtle">
                  <dt className="text-sm font-medium text-fg">{o.term}</dt>
                  <dd className="text-sm leading-[1.6] text-fg-2">{o.body}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      </main>

      <footer className="w-full border-t border-border">
        <div className="max-w-[1120px] mx-auto px-5 sm:px-8 py-8 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-[13px] text-fg-2">
          <span>
            <span className="font-medium text-fg">Anchor</span> writes social posts from your website.
          </span>
          <nav className="flex gap-5" aria-label="Footer">
            <a href="#generator" className="hover:text-fg transition-colors duration-[120ms] rounded-sm">
              Create posts
            </a>
            <a href="#recent-runs" className="hover:text-fg transition-colors duration-[120ms] rounded-sm">
              Library
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
