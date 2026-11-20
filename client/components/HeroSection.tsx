"use client";

import React, { useState } from "react";
import type { StartPayload } from "@/lib/useRunJob";
import { Button } from "./ui/button";

interface HeroSectionProps {
  onStart: (payload: StartPayload) => void;
  /** A run is in flight: the form is locked until it finishes. */
  busy: boolean;
}

const SAMPLES = ["native.no", "tanyxai.com", "devrev.ai", "inhabitr.ai"];

const MODES = [
  { value: "fast", label: "Standard", hint: "One writing pass. The quickest option." },
  { value: "refine", label: "Enhanced", hint: "Drafts several versions and keeps the strongest. Takes longer." },
] as const;

const INDUSTRIES = [
  { value: "auto", label: "Detect automatically" },
  { value: "saas", label: "SaaS" },
  { value: "hospitality", label: "Hospitality" },
  { value: "ecommerce", label: "E-commerce" },
  { value: "general", label: "General" },
];

/** Accepts "acme.com", "www.acme.com" or a full URL; returns "" when it cannot be a website. */
function normalize(raw: string): string {
  const v = raw.trim();
  if (!v) return "";
  try {
    const u = new URL(v.includes("//") ? v : `https://${v}`);
    return u.hostname.includes(".") ? u.toString() : "";
  } catch {
    return "";
  }
}

const SELECT =
  "h-11 sm:h-8 sm:pointer-coarse:h-11 w-full rounded-md border border-border bg-bg pl-3 pr-8 text-sm text-fg appearance-none cursor-pointer " +
  "hover:border-border-strong transition-colors duration-[120ms] disabled:text-fg-disabled disabled:cursor-default " +
  "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%237b8191%22 stroke-width=%221.5%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-no-repeat bg-[length:16px] bg-[position:right_8px_center]";

export function HeroSection({ onStart, busy }: HeroSectionProps) {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<"fast" | "refine">("fast");
  const [industry, setIndustry] = useState("auto");
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  const validate = (v: string) => (normalize(v) ? null : "Enter a website like acme.com or https://www.acme.com");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const err = validate(url);
    setTouched(true);
    setError(err);
    if (err) return;
    onStart({ url: normalize(url), mode, industry: industry === "auto" ? null : industry, posts: 3 });
  };

  return (
    <section id="generator" className="w-full max-w-[1120px] mx-auto px-5 sm:px-8 pt-16 sm:pt-24 pb-16 sm:pb-20">
      <h1 className="max-w-[720px] text-[40px] sm:text-[56px] leading-[1.05] font-semibold tracking-[-0.025em] text-fg">
        Social posts from your website, backed by sources.
      </h1>
      <p className="mt-4 max-w-[560px] text-[17px] sm:text-lg leading-[1.6] tracking-[-0.005em] text-fg-2">
        Paste your website. Anchor writes LinkedIn posts and Instagram carousels from what your brand has actually done,
        in your colors and type, with a link to every source.
      </p>

      <form onSubmit={submit} noValidate className="mt-10 max-w-[640px]" aria-label="Create posts">
        <label htmlFor="site" className="block text-[13px] font-medium text-fg-2">
          Website
        </label>
        <div className="mt-1.5 flex flex-col sm:flex-row gap-2">
          <input
            id="site"
            type="url"
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            placeholder="https://www.acme.com"
            value={url}
            disabled={busy}
            aria-invalid={!!error}
            aria-describedby="site-msg"
            onChange={(e) => {
              setUrl(e.target.value);
              if (touched) setError(validate(e.target.value));
            }}
            onBlur={() => {
              if (!url.trim()) return;
              setTouched(true);
              setError(validate(url));
            }}
            className={`w-full sm:w-auto sm:flex-1 min-w-0 h-12 sm:h-10 sm:pointer-coarse:h-11 rounded-md border bg-bg px-3 text-base sm:text-[15px] text-fg placeholder:text-fg-3 outline-none transition-[border-color,box-shadow] duration-[120ms] ease-out disabled:text-fg-disabled disabled:bg-bg-subtle focus-visible:shadow-[0_0_0_2px_var(--color-accent-subtle)] ${
              error ? "border-danger" : "border-border hover:border-border-strong focus:border-accent"
            }`}
          />
          <Button type="submit" size="field" loading={busy} className="w-full sm:w-[148px]">
            {busy ? "Creating" : "Create posts"}
          </Button>
        </div>
        <p id="site-msg" className={`mt-1.5 min-h-[18px] text-[13px] ${error ? "text-danger" : "text-fg-3"}`} aria-live="polite">
          {error ??
            (busy ? "Your posts are being created below. You can start another run when this one finishes." : "")}
        </p>

        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="mode" className="block text-[13px] font-medium text-fg-2">
              Mode
            </label>
            <select
              id="mode"
              value={mode}
              disabled={busy}
              onChange={(e) => setMode(e.target.value as "fast" | "refine")}
              className={`mt-1.5 ${SELECT}`}
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-[13px] text-fg-3">{MODES.find((m) => m.value === mode)?.hint}</p>
          </div>
          <div>
            <label htmlFor="industry" className="block text-[13px] font-medium text-fg-2">
              Industry
            </label>
            <select
              id="industry"
              value={industry}
              disabled={busy}
              onChange={(e) => setIndustry(e.target.value)}
              className={`mt-1.5 ${SELECT}`}
            >
              {INDUSTRIES.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-[13px] text-fg-3">Sets which playbook the posts follow.</p>
          </div>
        </div>

        <p className="mt-6 text-[13px] text-fg-3">
          Or try{" "}
          {SAMPLES.map((s, i) => (
            <React.Fragment key={s}>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setUrl(`https://${s}`);
                  setError(null);
                }}
                className="text-accent hover:underline underline-offset-2 rounded-sm cursor-pointer disabled:text-fg-disabled disabled:no-underline disabled:cursor-default"
              >
                {s}
              </button>
              {i < SAMPLES.length - 2 ? ", " : i === SAMPLES.length - 2 ? " or " : ""}
            </React.Fragment>
          ))}
        </p>
      </form>
    </section>
  );
}
