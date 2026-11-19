"use client";

import React, { useState } from "react";
import { PromptInput, PromptInputTextarea, PromptInputActions, PromptInputAction } from "./prompt-kit/prompt-input";
import type { StartPayload } from "@/lib/useRunJob";

interface HeroSectionProps {
  onStart: (payload: StartPayload) => void;
  /** A run is in flight: the input is locked until it finishes. */
  busy: boolean;
}

const SAMPLES = [
  { label: "native.no", url: "https://native.no" },
  { label: "tanyxai.com", url: "https://www.tanyxai.com" },
  { label: "devrev.ai", url: "https://devrev.ai" },
  { label: "inhabitr.ai", url: "https://inhabitr.ai" },
];

export function HeroSection({ onStart, busy }: HeroSectionProps) {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<"fast" | "refine">("fast");
  const [industry, setIndustry] = useState<string>("auto");

  const submit = () => {
    const u = url.trim();
    if (!u || busy) return;
    onStart({ url: u, mode, industry: industry === "auto" ? null : industry, posts: 3 });
  };

  return (
    <section id="generator" className="relative w-full flex flex-col items-center px-4 pt-16 sm:pt-24 pb-14 overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 -translate-x-1/2 w-[1100px] h-[620px] bg-[radial-gradient(ellipse_at_center,rgba(251,191,36,0.20),rgba(250,249,247,0)_65%)]"
      />

      <div className="relative inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-line text-[12px] font-medium text-muted mb-7 shadow-card">
        <svg className="w-3.5 h-3.5 text-brand" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
        </svg>
        Social posts, ready to publish
      </div>

      <h1 className="relative max-w-4xl text-center text-[44px] leading-[1.04] sm:text-6xl md:text-7xl font-semibold tracking-[-0.04em] text-ink">
        Your brand,
        <br />
        <span className="bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500 bg-clip-text text-transparent">verifiably</span> at its best.
      </h1>

      <p className="relative max-w-xl text-center text-base sm:text-lg text-muted leading-relaxed mt-5 mb-10">
        Paste your website. Get on-brand LinkedIn posts and Instagram carousels, written from your real wins and backed by
        sources you can check.
      </p>

      <div className="relative w-full max-w-2xl z-10">
        <PromptInput value={url} onValueChange={setUrl} onSubmit={submit} isLoading={busy}>
          <PromptInputTextarea placeholder="Paste a website, e.g. https://www.salesforce.com" disabled={busy} aria-label="Brand website" />
          <PromptInputActions>
            <div className="flex items-center gap-2">
              <div className="inline-flex p-0.5 rounded-full bg-sunken border border-line text-[12px] font-medium">
                {(["fast", "refine"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    disabled={busy}
                    onClick={() => setMode(m)}
                    className={`h-7 px-3 rounded-full transition-all cursor-pointer disabled:cursor-default ${
                      mode === m ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
                    }`}
                  >
                    {m === "fast" ? "Standard" : "Enhanced"}
                  </button>
                ))}
              </div>
              <select
                value={industry}
                disabled={busy}
                onChange={(e) => setIndustry(e.target.value)}
                aria-label="Industry"
                className="h-8 bg-sunken text-muted hover:text-ink text-[12px] font-medium rounded-full pl-3 pr-2 border border-line outline-none cursor-pointer focus-visible:ring-2 focus-visible:ring-amber-200"
              >
                <option value="auto">Any industry</option>
                <option value="saas">SaaS</option>
                <option value="hospitality">Hospitality</option>
                <option value="ecommerce">E-commerce</option>
                <option value="general">General</option>
              </select>
            </div>

            <PromptInputAction tooltip="Create posts">
              <button
                type="button"
                onClick={submit}
                disabled={!url.trim() || busy}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-full font-semibold text-[14px] transition-all bg-ink text-white hover:bg-ink-soft active:scale-[0.98] shadow-card cursor-pointer disabled:bg-line disabled:text-faint disabled:shadow-none disabled:cursor-not-allowed"
              >
                {busy ? (
                  <>
                    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    Creating
                  </>
                ) : (
                  <>
                    Create posts
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </>
                )}
              </button>
            </PromptInputAction>
          </PromptInputActions>
        </PromptInput>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <span className="text-[12px] text-faint mr-1">Try</span>
          {SAMPLES.map((s) => (
            <button
              key={s.label}
              type="button"
              disabled={busy}
              onClick={() => setUrl(s.url)}
              className="text-[12px] h-7 px-3 rounded-full bg-surface hover:bg-sunken text-muted hover:text-ink border border-line hover:border-line-strong transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
