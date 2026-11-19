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

const BASE_TITLE = "Anchor — Evidence-Grounded Brand Intelligence & Social Engine";

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
          body: `${result.verified_posts} verified post${result.verified_posts === 1 ? "" : "s"} for ${result.brand}`,
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
  const activeLabel = busy ? `Generating · ${stageIdx >= 0 ? STAGES[stageIdx].short : "Starting"}` : null;
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
            <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight">Grounding, not vibes.</h2>
            <p className="mt-3 text-muted leading-relaxed">
              Every claim traces to evidence from the crawl. Posts that can&rsquo;t be supported are dropped, not shipped.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {[
              {
                n: "01",
                title: "Verbatim fact extraction",
                body: "Pulls structured data, pricing, case studies and press mentions into numbered evidence. Quotes have to match the source character for character.",
                foot: "Exact substring checks",
              },
              {
                n: "02",
                title: "Independent critic",
                body: "A second model from a different family reviews every draft and flags exaggeration, unearned superlatives and claims the sources don't support.",
                foot: "No self-grading",
              },
              {
                n: "03",
                title: "On-brand carousels",
                body: "Picks up the brand's own fonts and colors from its stylesheet and renders 1080×1350 cover and explainer slides, ready for LinkedIn and Instagram.",
                foot: "Live brand tokens",
              },
            ].map((f) => (
              <div key={f.n} className="p-7 rounded-3xl bg-surface border border-line shadow-card flex flex-col justify-between">
                <div>
                  <div className="text-[13px] font-mono text-brand-deep">{f.n}</div>
                  <h3 className="mt-3 text-lg font-semibold tracking-tight">{f.title}</h3>
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
            <div className="max-w-2xl">
              <div className="text-[12px] font-medium text-brand-deep">Refine mode</div>
              <h3 className="mt-2 text-2xl font-semibold tracking-tight">It gets better at your industry</h3>
              <p className="mt-2 text-muted leading-relaxed">
                Harness² (Propose, Probe, Compose) refines prompts, guardrails and industry playbooks per vertical. What it learns
                carries over, so later fast runs in the same industry start from the improved harness. No fine-tuning involved.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="w-full border-t border-line py-8 text-[13px] text-muted">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-ink">Anchor</span>
            <span>Social posts that cite their sources</span>
          </div>
          <a href="#generator" className="hover:text-ink">
            Start a run ↑
          </a>
        </div>
      </footer>
    </div>
  );
}
