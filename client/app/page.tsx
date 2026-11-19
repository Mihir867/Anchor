"use client";

import React, { useEffect, useState, useRef } from "react";
import { Navbar } from "@/components/Navbar";
import { HeroSection } from "@/components/HeroSection";
import { RunResultView } from "@/components/RunResultView";
import { RecentRunsSection } from "@/components/RecentRunsSection";
import { RunResult, listRuns, getRun } from "@/lib/api";

export default function Home() {
  const [currentResult, setCurrentResult] = useState<RunResult | null>(null);
  const resultRef = useRef<HTMLDivElement | null>(null);

  // On initial mount, load the latest completed run so the user immediately sees a working result
  useEffect(() => {
    async function loadInitial() {
      try {
        const runs = await listRuns();
        const doneRun = runs.find((r) => r.status === "done" && r.verified_posts > 0) || runs[0];
        if (doneRun) {
          const detail = await getRun(doneRun.id);
          if (detail.result) {
            setCurrentResult(detail.result);
          }
        }
      } catch (err) {
        console.error("Failed to load initial run:", err);
      }
    }
    loadInitial();
  }, []);

  const handleRunCompleted = (result: RunResult) => {
    setCurrentResult(result);
    setTimeout(() => {
      resultRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 150);
  };

  const handleSelectRun = (result: RunResult) => {
    setCurrentResult(result);
    setTimeout(() => {
      resultRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 150);
  };

  return (
    <div className="min-h-screen bg-[#080d16] text-[#f8fafc] font-sans flex flex-col selection:bg-amber-500/20 selection:text-amber-200">
      <Navbar />

      <main className="flex-1 flex flex-col">
        {/* Hero Section with Interactive Prompt-Kit Input */}
        <HeroSection onRunCompleted={handleRunCompleted} />

        {/* Live Active / Selected Run Result Section */}
        {currentResult && (
          <section
            ref={resultRef}
            id="result-viewer"
            className="w-full max-w-6xl mx-auto px-4 sm:px-6 py-12 font-sans"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-xs font-mono font-semibold uppercase tracking-wider text-emerald-400">
                  Live Active Run Viewer
                </span>
              </div>
              <span className="text-xs text-[#909dad]">
                Click any post below to inspect slides, copy, and verbatim citations
              </span>
            </div>

            <RunResultView
              result={currentResult}
              onClose={() => setCurrentResult(null)}
            />
          </section>
        )}

        {/* Historical Runs Archive */}
        <RecentRunsSection
          onSelectRun={handleSelectRun}
          selectedTaskId={currentResult?.task_id}
        />

        {/* Feature Highlights Grid / Proof Bento */}
        <section
          id="features"
          className="max-w-6xl mx-auto px-4 sm:px-6 py-20 w-full border-t border-[#212c3d]/60 font-sans"
        >
          <div className="text-center max-w-xl mx-auto mb-14">
            <h2 className="text-3xl sm:text-4xl font-bold text-[#f8fafc] tracking-tight mb-3">
              Grounding, not vibes.
            </h2>
            <p className="text-sm sm:text-base text-[#909dad] leading-relaxed">
              Every single claim traces to verbatim crawl evidence. Unsupported
              posts are dropped, not shipped.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Card 1: Verbatim Fact Mining */}
            <div className="p-7 rounded-2xl bg-[#0c121d] border border-[#212c3d] hover:border-[#2f3d52] transition-colors duration-200 flex flex-col justify-between shadow-lg">
              <div>
                <div className="w-10 h-10 rounded-xl bg-[#182232] border border-[#212c3d] flex items-center justify-center text-[#f59e0b] mb-5">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-[#f8fafc] mb-2 tracking-tight">
                  Verbatim Fact Extraction
                </h3>
                <p className="text-sm text-[#909dad] leading-relaxed">
                  Extracts JSON-LD, pricing tables, case studies, and press mentions into immutable evidence items [E1..En]. Quotes must match character-for-character.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[#212c3d]/60 text-xs font-mono text-[#909dad] flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>Exact substring checks (no hallucination)</span>
              </div>
            </div>

            {/* Card 2: Dual-Model Critic Loop */}
            <div className="p-7 rounded-2xl bg-[#0c121d] border border-[#212c3d] hover:border-[#2f3d52] transition-colors duration-200 flex flex-col justify-between shadow-lg">
              <div>
                <div className="w-10 h-10 rounded-xl bg-[#182232] border border-[#212c3d] flex items-center justify-center text-[#f59e0b] mb-5">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-[#f8fafc] mb-2 tracking-tight">
                  Independent Model Critic
                </h3>
                <p className="text-sm text-[#909dad] leading-relaxed">
                  A different model family (Qwen 27B checking GPT-OSS 120B) independently flags exaggerations, unearned superlatives, or unverified claims.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[#212c3d]/60 text-xs font-mono text-[#909dad] flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>Zero self-grading bias</span>
              </div>
            </div>

            {/* Card 3: 1080x1350 Carousels & PDF */}
            <div className="p-7 rounded-2xl bg-[#0c121d] border border-[#212c3d] hover:border-[#2f3d52] transition-colors duration-200 flex flex-col justify-between shadow-lg">
              <div>
                <div className="w-10 h-10 rounded-xl bg-[#182232] border border-[#212c3d] flex items-center justify-center text-[#f59e0b] mb-5">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-[#f8fafc] mb-2 tracking-tight">
                  Branded Posters & Carousels
                </h3>
                <p className="text-sm text-[#909dad] leading-relaxed">
                  Extracts live brand @font-face and WCAG color contrast to render 1080×1350 cover & explainer slides, plus LinkedIn document PDFs.
                </p>
              </div>
              <div className="mt-6 pt-4 border-t border-[#212c3d]/60 text-xs font-mono text-[#909dad] flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                <span>Live stylesheet token extraction</span>
              </div>
            </div>
          </div>
        </section>

        {/* Harness² Continuous Optimization Section */}
        <section
          id="harness2"
          className="max-w-6xl mx-auto px-4 sm:px-6 py-16 w-full border-t border-[#212c3d]/60 font-sans"
        >
          <div className="rounded-3xl bg-gradient-to-r from-[#0c1424] via-[#0c121d] to-[#0c1424] border border-[#212c3d] p-8 sm:p-12 relative overflow-hidden">
            <div className="max-w-2xl relative z-10 space-y-4">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400 font-mono">
                Google Research Method
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold text-[#f8fafc] tracking-tight">
                Self-improving Harness² Architecture
              </h2>
              <p className="text-sm sm:text-base text-[#909dad] leading-relaxed">
                Anchor uses Harness² (Propose-Probe-Compose) to refine prompts, guardrails, and industry playbooks per vertical. Lessons accumulate in industry libraries, making future runs faster and more accurate without model weight fine-tuning.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-[#212c3d] py-10 text-xs text-[#909dad] bg-[#080d16] font-sans">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <svg
              className="w-4 h-4 text-[#f59e0b] fill-current"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
            </svg>
            <span className="font-semibold text-sm text-[#f8fafc]">Anchor</span>
            <span className="text-[#909dad]">— Autonomous Brand Social Engine</span>
          </div>
          <div className="text-center sm:text-right text-[#909dad]">
            Connected to FastAPI backend on port 8000 · Full-Stack Active
          </div>
        </div>
      </footer>
    </div>
  );
}
