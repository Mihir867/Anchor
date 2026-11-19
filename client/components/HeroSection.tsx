"use client";

import React, { useState } from "react";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from "./prompt-kit/prompt-input";
import { createRun, getRun, RunResult } from "@/lib/api";

type StatusType = "idle" | "queued" | "crawling" | "extracting" | "generating" | "verifying" | "done";

interface HeroSectionProps {
  onRunCompleted?: (result: RunResult) => void;
}

export function HeroSection({ onRunCompleted }: HeroSectionProps) {
  const [url, setUrl] = useState("https://native.no");
  const [mode, setMode] = useState<"fast" | "refine">("fast");
  const [industry, setIndustry] = useState<string>("auto");
  const [status, setStatus] = useState<StatusType>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [elapsedSecs, setElapsedSecs] = useState<number>(0);

  const handleSubmit = async () => {
    if (!url.trim()) return;

    setStatus("queued");
    setErrorMsg(null);
    setElapsedSecs(0);

    const startTime = Date.now();
    const timer = setInterval(() => {
      setElapsedSecs(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    try {
      const newJobId = await createRun({
        url: url.trim(),
        mode,
        industry: industry === "auto" ? null : industry,
        posts: 3,
      });

      setJobId(newJobId);
      pollJob(newJobId, timer);
    } catch (err: unknown) {
      clearInterval(timer);
      const message = err instanceof Error ? err.message : String(err);
      setErrorMsg(message);
      setStatus("idle");
    }
  };

  const pollJob = (id: string, timer: NodeJS.Timeout) => {
    const interval = setInterval(async () => {
      try {
        const data = await getRun(id);
        if (data.status === "running") {
          // Progress simulation stages based on elapsed time
          setStatus("crawling");
        } else if (data.status === "done") {
          clearInterval(interval);
          clearInterval(timer);
          setStatus("done");
          if (data.result) {
            onRunCompleted?.(data.result);
          }
        } else if (data.status === "failed") {
          clearInterval(interval);
          clearInterval(timer);
          setErrorMsg(data.error || "Job execution failed");
          setStatus("idle");
        }
      } catch {
        // Keep polling
      }
    }, 2500);
  };

  const handleSelectSample = (sampleUrl: string) => {
    setUrl(sampleUrl);
  };

  return (
    <section id="generator" className="relative w-full flex flex-col items-center justify-center px-4 pt-12 pb-16 overflow-hidden font-sans">
      {/* Subtle Atmospheric Radial Glow (Native.no style) */}
      <div
        className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[1000px] h-[550px] bg-[radial-gradient(ellipse_at_top,rgba(245,158,11,0.12),rgba(8,13,22,0)_70%)]"
        aria-hidden="true"
      />

      {/* Eyebrow Badge (No emojis, sleek SVG) */}
      <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#182232] border border-[#212c3d] text-xs font-medium text-[#909dad] mb-6 tracking-wide">
        <svg
          className="w-3.5 h-3.5 text-[#f59e0b] fill-current"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
        </svg>
        <span>Autonomous Brand Intelligence & Content Engine</span>
      </div>

      {/* Hero Headline in Pure Inter */}
      <h1 className="max-w-4xl text-center text-4xl sm:text-6xl md:text-7xl font-bold tracking-[-0.035em] text-[#f8fafc] leading-[1.08] mb-5 font-sans">
        Your brand. <br className="hidden sm:inline" />
        <span className="text-[#f8fafc]">Verifiably looking its best.</span>
      </h1>

      {/* Hero Subtitle */}
      <p className="max-w-2xl text-center text-base sm:text-lg text-[#909dad] leading-relaxed mb-9 font-normal">
        Give it any company website. Anchor crawls the site and press, extracts verifiable proof, and generates branded social carousels where every single claim traces to cited evidence.
      </p>

      {/* Prompt-Kit Chat / Input Container */}
      <div className="w-full max-w-2xl relative z-10">
        <PromptInput
          value={url}
          onValueChange={setUrl}
          onSubmit={handleSubmit}
          isLoading={status !== "idle" && status !== "done"}
          className="shadow-[0_25px_60px_-15px_rgba(0,0,0,0.7)]"
        >
          <PromptInputTextarea
            placeholder="Enter brand website (e.g. https://native.no) or custom query..."
            disabled={status !== "idle" && status !== "done"}
          />

          <PromptInputActions>
            {/* Left Tools / Mode Selectors */}
            <div className="flex items-center gap-2">
              {/* Mode Toggle with SVG icons */}
              <button
                type="button"
                onClick={() => setMode(mode === "fast" ? "refine" : "fast")}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#182232] hover:bg-[#212c3d] text-[#909dad] hover:text-[#f8fafc] border border-[#212c3d] transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
              >
                {mode === "fast" ? (
                  <svg className="w-3.5 h-3.5 text-[#f59e0b]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5 text-[#f59e0b]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                )}
                <span>{mode === "fast" ? "Fast Mode" : "Harness² Refine"}</span>
              </button>

              {/* Industry Select */}
              <select
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                className="bg-[#182232] text-[#909dad] hover:text-[#f8fafc] text-xs font-medium rounded-lg px-2.5 py-1.5 border border-[#212c3d] outline-none cursor-pointer hover:bg-[#212c3d] transition-colors duration-150 focus-visible:ring-1 focus-visible:ring-amber-400"
              >
                <option value="auto">Auto-Classify</option>
                <option value="saas">SaaS Playbook</option>
                <option value="hospitality">Hospitality Playbook</option>
                <option value="ecommerce">E-Commerce Playbook</option>
                <option value="general">General Playbook</option>
              </select>
            </div>

            {/* Right Action Button */}
            <PromptInputAction tooltip="Generate verified posts & carousels">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!url.trim() || (status !== "idle" && status !== "done")}
                className={`inline-flex items-center gap-2 px-5 py-2 rounded-full font-semibold text-sm transition-all duration-150 ${
                  !url.trim()
                    ? "bg-[#182232] text-[#909dad] cursor-not-allowed border border-[#212c3d]"
                    : "bg-[#f8fafc] text-[#080d16] hover:bg-[#e2e8f0] active:scale-[0.98] shadow-md cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                }`}
              >
                {status !== "idle" && status !== "done" ? (
                  <>
                    <svg className="animate-spin h-4 w-4 text-[#080d16]" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    <span>Generating... ({elapsedSecs}s)</span>
                  </>
                ) : (
                  <>
                    <span>Generate</span>
                    <svg className="w-3.5 h-3.5 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2.5">
                      <line x1="5" y1="12" x2="19" y2="12" />
                      <polyline points="12 5 19 12 12 19" />
                    </svg>
                  </>
                )}
              </button>
            </PromptInputAction>
          </PromptInputActions>
        </PromptInput>

        {/* Live Execution Timeline Progress */}
        {status !== "idle" && (
          <div className="mt-4 p-4 rounded-xl bg-[#0c121d] border border-[#212c3d] text-xs font-sans space-y-3">
            <div className="flex items-center justify-between border-b border-[#212c3d]/60 pb-2.5">
              <span className="font-semibold text-[#f8fafc] flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#f59e0b] animate-pulse" />
                Backend Engine Task Active
              </span>
              <span className="text-[#909dad] font-mono text-[11px]">
                {jobId ? `Job: ${jobId}` : "Running"} ({elapsedSecs}s elapsed)
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div
                className={`p-2.5 rounded-lg border text-center transition-colors duration-200 ${
                  elapsedSecs < 12
                    ? "bg-[#182232] border-[#f59e0b] text-[#f8fafc] font-medium"
                    : "bg-[#0c121d] border-[#212c3d] text-[#909dad]"
                }`}
              >
                1. Playwright Crawl
              </div>
              <div
                className={`p-2.5 rounded-lg border text-center transition-colors duration-200 ${
                  elapsedSecs >= 12 && elapsedSecs < 24
                    ? "bg-[#182232] border-[#f59e0b] text-[#f8fafc] font-medium"
                    : elapsedSecs >= 24
                    ? "bg-[#0c121d] border-[#212c3d] text-[#909dad]"
                    : "opacity-40"
                }`}
              >
                2. Extract Proof
              </div>
              <div
                className={`p-2.5 rounded-lg border text-center transition-colors duration-200 ${
                  elapsedSecs >= 24 && elapsedSecs < 42
                    ? "bg-[#182232] border-[#f59e0b] text-[#f8fafc] font-medium"
                    : elapsedSecs >= 42
                    ? "bg-[#0c121d] border-[#212c3d] text-[#909dad]"
                    : "opacity-40"
                }`}
              >
                3. Mine & Draft
              </div>
              <div
                className={`p-2.5 rounded-lg border text-center transition-colors duration-200 ${
                  elapsedSecs >= 42 || status === "done"
                    ? "bg-[#182232] border-[#f59e0b] text-[#f8fafc] font-medium"
                    : "opacity-40"
                }`}
              >
                4. Critic & Render
              </div>
            </div>

            {status === "done" && (
              <div className="mt-3 pt-2.5 flex items-center justify-between text-[#f59e0b]">
                <span className="flex items-center gap-1.5 font-medium">
                  <svg className="w-4 h-4 text-emerald-400 stroke-current" fill="none" viewBox="0 0 24 24" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  <span className="text-emerald-300">Run completed successfully! See posts below.</span>
                </span>
                <button
                  type="button"
                  onClick={() => setStatus("idle")}
                  className="text-[#909dad] hover:text-[#f8fafc] underline cursor-pointer"
                >
                  Reset
                </button>
              </div>
            )}

            {errorMsg && (
              <div className="mt-2 text-rose-400 font-medium">
                Error: {errorMsg}
              </div>
            )}
          </div>
        )}

        {/* Quick Sample Suggestions */}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <span className="text-xs text-[#909dad] font-medium mr-1">
            Try a sample:
          </span>
          {[
            { label: "native.no", url: "https://native.no" },
            { label: "tanyxai.com", url: "https://www.tanyxai.com" },
            { label: "devrev.ai", url: "https://devrev.ai" },
            { label: "inhabitr.ai", url: "https://inhabitr.ai" },
          ].map((sample) => (
            <button
              key={sample.label}
              type="button"
              onClick={() => handleSelectSample(sample.url)}
              className="text-xs px-2.5 py-1 rounded-full bg-[#0c121d] hover:bg-[#182232] text-[#909dad] hover:text-[#f8fafc] border border-[#212c3d] hover:border-slate-500 transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
            >
              {sample.label}
            </button>
          ))}
        </div>

        {/* MCP Connectors Footer Row (Just like Native.no, SVG icons) */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs text-[#909dad] bg-[#0c121d]/70 border border-[#212c3d] hover:border-slate-500 transition-colors duration-150 cursor-pointer">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>Connect Claude via MCP</span>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs text-[#909dad] bg-[#0c121d]/70 border border-[#212c3d] hover:border-slate-500 transition-colors duration-150 cursor-pointer">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            <span>Connect ChatGPT via MCP</span>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs text-[#909dad] bg-[#0c121d]/70 border border-[#212c3d] hover:border-slate-500 transition-colors duration-150 cursor-pointer">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span>Connect Grok Bot via MCP</span>
          </div>
        </div>
      </div>
    </section>
  );
}
