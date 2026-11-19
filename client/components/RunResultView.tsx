"use client";

import React, { useEffect, useState } from "react";
import { PostCard, RunResult, assetUrl } from "@/lib/api";
import { LinkedInApp, LinkedInPost } from "./previews/LinkedInPost";
import { InstagramPost } from "./previews/InstagramPost";
import { BrandAvatar, handleFor } from "./previews/shared";

interface RunResultViewProps {
  result: RunResult;
  onClose?: () => void;
  /** Briefly celebrate a run that just finished. */
  fresh?: boolean;
}

type Platform = "linkedin" | "instagram";

const tag = (h: string) => (h.startsWith("#") ? h : `#${h}`);

function withTags(text: string | undefined, tags: string[]) {
  return [text?.trim() || "", tags.join(" ")].filter(Boolean).join("\n\n");
}

export function RunResultView({ result, onClose, fresh }: RunResultViewProps) {
  const cards = result.deck?.cards || [];
  const verified = cards.filter((c) => c.status === "verified");
  const shown = verified.length > 0 ? verified : cards;

  const [sel, setSel] = useState(0);
  const [platform, setPlatform] = useState<Platform>("linkedin");
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => setSel(0), [result.task_id]);

  const card: PostCard | undefined = shown[Math.min(sel, shown.length - 1)];
  const brand = result.brand || "Brand";
  const domain = result.domain;
  const handle = handleFor(brand, domain);

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 1800);
    });
  };

  if (!card) {
    return (
      <div className="rounded-3xl bg-surface border border-line p-12 text-center shadow-card">
        <div className="text-lg font-semibold">We couldn&rsquo;t find enough to write about</div>
        <p className="mt-2 text-sm text-muted max-w-md mx-auto">
          We only publish posts we can back up. Try a site with more about its products, customers or news.
        </p>
      </div>
    );
  }

  const tags = (card.post?.hashtags || []).map(tag);
  const images = (card.slide_urls ?? []).map(assetUrl);
  const linkedinText = withTags(card.post?.linkedin, tags);
  const instagramText = withTags(card.post?.instagram_caption, tags);
  const previewProps = {
    brand,
    handle,
    domain,
    logoUrl: result.logo_url,
    brandColor: result.brand_color,
    images,
    title: card.post?.poster_headline || card.fact.headline,
  };

  return (
    <div className={`rounded-3xl bg-surface border border-line shadow-lift overflow-hidden ${fresh ? "animate-fade-up" : ""}`}>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-6 sm:px-8 py-5 border-b border-line">
        <div className="flex items-center gap-3.5 min-w-0">
          <BrandAvatar brand={brand} logoUrl={result.logo_url} color={result.brand_color} size={44} shape="square" />
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-xl font-semibold tracking-tight truncate">{brand}</h3>
              <Chip tone="ok">
                <CheckIcon /> {verified.length} post{verified.length === 1 ? "" : "s"} ready
              </Chip>
              {fresh && <Chip tone="brand">Just generated</Chip>}
            </div>
            <div className="text-[13px] text-muted mt-0.5 flex items-center gap-1.5 flex-wrap">
              {domain && <span>{domain}</span>}
              {domain && result.industry && result.industry !== "general" && <Dot />}
              {result.industry && result.industry !== "general" && <span className="capitalize">{result.industry}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {result.posts_md_url && (
            <a
              href={assetUrl(result.posts_md_url)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-full text-[13px] font-medium border border-line hover:border-line-strong hover:bg-sunken transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export all
            </a>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="w-9 h-9 rounded-full flex items-center justify-center text-muted hover:text-ink hover:bg-sunken transition-colors cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        {/* Left: posts, copy, sources */}
        <aside className="border-b lg:border-b-0 lg:border-r border-line p-5 sm:p-6 space-y-7 bg-surface">
          <section>
            <SectionLabel>Posts</SectionLabel>
            <div className="space-y-2">
              {shown.map((c, i) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setSel(i)}
                  className={`w-full text-left p-3 rounded-2xl border transition-all cursor-pointer ${
                    i === sel ? "border-ink bg-sunken/60 shadow-card" : "border-line hover:border-line-strong hover:bg-sunken/40"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="relative w-11 h-[55px] shrink-0 rounded-md overflow-hidden bg-sunken border border-line">
                      {c.slide_urls?.[0] && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={assetUrl(c.slide_urls[0])} alt="" className="w-full h-full object-cover" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted uppercase tracking-wide">
                        <span>Post {i + 1}</span>
                        {c.fact.category && (
                          <>
                            <Dot />
                            <span className="truncate">{c.fact.category}</span>
                          </>
                        )}
                      </div>
                      <div className="text-[14px] font-medium leading-snug mt-0.5 line-clamp-2">{c.fact.headline}</div>
                    </div>
                    {c.fallback ? (
                      <span className="text-[10px] font-medium text-amber-600 uppercase tracking-wide mt-0.5 whitespace-nowrap"
                            title="Not every claim could be verified. Review before publishing.">
                        Needs review
                      </span>
                    ) : c.status === "verified" ? (
                      <span className="text-ok mt-0.5" title="Backed by sources">
                        <CheckIcon className="w-4 h-4" />
                      </span>
                    ) : (
                      <span className="text-bad text-xs mt-0.5" title="Draft">
                        ✗
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section>
            <SectionLabel>Copy &amp; publish</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <CopyButton label="LinkedIn post" done={copied === "li"} onClick={() => copy(linkedinText, "li")} />
              <CopyButton label="Instagram caption" done={copied === "ig"} onClick={() => copy(instagramText, "ig")} />
            </div>
            {tags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {tags.map((t) => (
                  <span key={t} className="text-[12px] px-2 py-0.5 rounded-full bg-sunken text-ink-soft border border-line">
                    {t}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-3 flex items-center gap-2 text-[12px] text-muted">
              <span>{card.post?.linkedin?.length ?? 0} chars on LinkedIn</span>
              <Dot />
              <span>{card.post?.instagram_caption?.length ?? 0} on Instagram</span>
            </div>
          </section>

          <section>
            <SectionLabel>Sources</SectionLabel>
            <blockquote className="text-[13px] leading-relaxed text-ink-soft border-l-2 border-brand pl-3 py-0.5">
              &ldquo;{card.fact.quote}&rdquo;
            </blockquote>
            <div className="mt-3 space-y-2">
              {(card.sources || []).map((s, i) => (
                <a
                  key={`${s.url}-${i}`}
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group block p-3 rounded-xl border border-line hover:border-line-strong hover:bg-sunken/40 transition-colors"
                >
                  {s.date && <div className="text-[11px] text-muted">{s.date}</div>}
                  <div className="text-[13px] font-medium line-clamp-2 group-hover:underline">{s.title || s.url}</div>
                  <div className="text-[12px] text-faint truncate mt-0.5">{s.url.replace(/^https?:\/\//, "")}</div>
                </a>
              ))}
            </div>
          </section>
        </aside>

        {/* Right: platform preview */}
        <section className="relative bg-sunken min-h-[640px] flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 sm:px-6 pt-5">
            <Segmented
              value={platform}
              onChange={(v) => setPlatform(v as Platform)}
              options={[
                { value: "linkedin", label: "LinkedIn", icon: <LinkedInGlyph /> },
                { value: "instagram", label: "Instagram", icon: <InstagramGlyph /> },
              ]}
            />
            {platform === "linkedin" && (
              <Segmented
                small
                value={device}
                onChange={(v) => setDevice(v as "desktop" | "mobile")}
                options={[
                  { value: "desktop", label: "Desktop" },
                  { value: "mobile", label: "Mobile" },
                ]}
              />
            )}
          </div>

          <div
            className="flex-1 flex items-start justify-center px-4 py-8 bg-[radial-gradient(#e2ddd4_1px,transparent_1px)] [background-size:18px_18px]"
            key={`${card.id}-${platform}-${device}`}
          >
            <div className="animate-fade-up w-full flex justify-center">
              {platform === "linkedin" ? (
                device === "desktop" ? (
                  <LinkedInPost {...previewProps} text={linkedinText} />
                ) : (
                  <LinkedInApp {...previewProps} text={linkedinText} />
                )
              ) : (
                <InstagramPost {...previewProps} text={instagramText} />
              )}
            </div>
          </div>

          {shown.length > 1 && (
            <div className="flex items-center justify-center gap-3 pb-6 text-[13px] text-muted">
              <button
                type="button"
                disabled={sel === 0}
                onClick={() => setSel((s) => s - 1)}
                className="h-8 px-3 rounded-full border border-line bg-surface hover:border-line-strong disabled:opacity-40 cursor-pointer disabled:cursor-default"
              >
                ← Previous
              </button>
              <span className="tabular-nums">
                Post {sel + 1} of {shown.length}
              </span>
              <button
                type="button"
                disabled={sel === shown.length - 1}
                onClick={() => setSel((s) => s + 1)}
                className="h-8 px-3 rounded-full border border-line bg-surface hover:border-line-strong disabled:opacity-40 cursor-pointer disabled:cursor-default"
              >
                Next →
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

// ---- small pieces ------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint mb-2.5">{children}</div>;
}

function Dot() {
  return <span className="w-[3px] h-[3px] rounded-full bg-current opacity-50 shrink-0" />;
}

function Chip({ children, tone }: { children: React.ReactNode; tone: "ok" | "brand" }) {
  const cls = tone === "ok" ? "bg-ok-tint text-ok border-emerald-200" : "bg-brand-tint text-brand-deep border-amber-200";
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[12px] font-medium border ${cls}`}>{children}</span>;
}

function CheckIcon({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

function CopyButton({ label, done, onClick }: { label: string; done: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-10 px-3 rounded-xl text-[13px] font-medium inline-flex items-center justify-center gap-1.5 transition-all cursor-pointer active:scale-[0.98] ${
        done ? "bg-ok text-white" : "bg-ink text-white hover:bg-ink-soft"
      }`}
    >
      {done ? (
        <>
          <CheckIcon /> Copied
        </>
      ) : (
        <>
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <rect x="9" y="9" width="12" height="12" rx="2" />
            <path d="M5 15V5a2 2 0 012-2h10" />
          </svg>
          {label}
        </>
      )}
    </button>
  );
}

function Segmented({
  value,
  onChange,
  options,
  small,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; icon?: React.ReactNode }[];
  small?: boolean;
}) {
  return (
    <div className="inline-flex p-1 rounded-full bg-surface border border-line shadow-card">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`inline-flex items-center gap-1.5 rounded-full font-medium transition-all cursor-pointer ${small ? "h-7 px-3 text-[12px]" : "h-8 px-4 text-[13px]"} ${
            value === o.value ? "bg-ink text-white shadow-sm" : "text-muted hover:text-ink"
          }`}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

function LinkedInGlyph() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.34V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 110-4.13 2.06 2.06 0 010 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

function InstagramGlyph() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" />
      <circle cx="12" cy="12" r="4.2" />
      <circle cx="17.4" cy="6.6" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}
