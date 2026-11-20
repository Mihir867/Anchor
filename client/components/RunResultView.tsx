"use client";

import React, { useEffect, useRef, useState } from "react";
import { PostCard, RunResult, assetUrl } from "@/lib/api";
import { LinkedInApp, LinkedInPost } from "./previews/LinkedInPost";
import { InstagramPost } from "./previews/InstagramPost";
import { BrandAvatar, handleFor } from "./previews/shared";
import { Button, IconButton, buttonClass } from "./ui/button";
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, CopyIcon, DownloadIcon, Status, XIcon } from "./ui/icons";

interface RunResultViewProps {
  result: RunResult;
  onClose?: () => void;
  /** The run just finished (content fades in once). */
  fresh?: boolean;
}

type Platform = "linkedin" | "instagram";
type Device = "desktop" | "mobile";

const INDUSTRY_LABEL: Record<string, string> = { saas: "SaaS", ecommerce: "E-commerce", hospitality: "Hospitality" };

const tag = (h: string) => (h.startsWith("#") ? h : `#${h}`);

function withTags(text: string | undefined, tags: string[]) {
  return [text?.trim() || "", tags.join(" ")].filter(Boolean).join("\n\n");
}

export function RunResultView({ result, onClose, fresh }: RunResultViewProps) {
  const cards = result.deck?.cards || [];
  const verified = cards.filter((c) => c.status === "verified");
  const shown = verified.length > 0 ? verified : cards;
  const review = shown.filter((c) => c.fallback).length;

  const [sel, setSel] = useState(0);
  const [platform, setPlatform] = useState<Platform>("linkedin");
  const [device, setDevice] = useState<Device>("desktop");
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setSel(0), [result.task_id]);
  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  const card: PostCard | undefined = shown[Math.min(sel, shown.length - 1)];
  const brand = result.brand || "Brand";
  const domain = result.domain;
  const handle = handleFor(brand, domain);
  const industry = result.industry && result.industry !== "general" ? INDUSTRY_LABEL[result.industry] ?? result.industry : null;
  const ready = verified.length - review;

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(
      () => {
        setCopyError(false);
        setCopied(label);
        if (copyTimer.current) clearTimeout(copyTimer.current);
        copyTimer.current = setTimeout(() => setCopied(null), 1500);
      },
      () => setCopyError(true),
    );
  };

  if (!card) {
    return (
      <div className="rounded-lg border border-border p-6 sm:p-8">
        <h2 className="text-lg leading-[1.35] font-semibold tracking-[-0.01em]">No posts for {brand}</h2>
        <p className="mt-1 max-w-[560px] text-sm text-fg-2">
          Anchor only delivers posts it can back with a source, and this site didn&rsquo;t have enough to go on. Try a site
          with more about its products, customers or news.
        </p>
        {onClose && (
          <Button variant="secondary" className="mt-5" onClick={onClose}>
            Dismiss
          </Button>
        )}
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
    <div className={`rounded-lg border border-border overflow-hidden ${fresh ? "animate-fade-up" : ""}`}>
      {/* Header */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-5 sm:px-6 py-5 border-b border-border">
        <div className="flex items-center gap-3 min-w-0">
          <BrandAvatar brand={brand} logoUrl={result.logo_url} color={result.brand_color} size={40} shape="square" />
          <div className="min-w-0">
            <h2 className="text-lg leading-[1.35] font-semibold tracking-[-0.01em] truncate">{brand}</h2>
            <p className="text-[13px] text-fg-3 truncate">
              {[domain, industry].filter(Boolean).join(", ")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 sm:shrink-0">
          <div className="flex items-center gap-4">
            {ready > 0 && (
              <Status tone="success">
                <span className="tabular-nums">
                  {ready} post{ready === 1 ? "" : "s"} ready
                </span>
              </Status>
            )}
            {review > 0 && (
              <Status tone="warning">
                <span className="tabular-nums">
                  {review} {ready > 0 ? "to review" : `post${review === 1 ? "" : "s"} to review`}
                </span>
              </Status>
            )}
          </div>
          <div className="flex items-center gap-1">
            {result.posts_md_url && (
              <a href={assetUrl(result.posts_md_url)} target="_blank" rel="noreferrer" className={buttonClass("secondary", "md")}>
                <DownloadIcon className="w-3.5 h-3.5" />
                Export all
              </a>
            )}
            {onClose && (
              <IconButton label="Close posts" onClick={onClose}>
                <XIcon className="w-4 h-4" />
              </IconButton>
            )}
          </div>
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        {/* Left: posts, copy, sources */}
        <aside className="border-b lg:border-b-0 lg:border-r border-border">
          <section className="px-3 pt-4 pb-3" aria-labelledby="posts-h">
            <h3 id="posts-h" className="px-2 text-[13px] font-medium text-fg-3 mb-1">
              Posts
            </h3>
            <ul>
              {shown.map((c, i) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSel(i)}
                    aria-current={i === sel || undefined}
                    className={`w-full flex items-start gap-3 px-2 py-2.5 rounded-md text-left cursor-pointer transition-colors duration-[120ms] ease-out ${
                      i === sel ? "bg-accent-subtle" : "hover:bg-bg-subtle active:bg-bg-muted"
                    }`}
                  >
                    <span className="w-8 aspect-[4/5] shrink-0 rounded-sm overflow-hidden bg-bg-muted">
                      {c.slide_urls?.[0] && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={assetUrl(c.slide_urls[0])} alt="" className="w-full h-full object-cover" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-fg-3 truncate">
                        Post {i + 1}
                        {c.fact.category ? `, ${c.fact.category}` : ""}
                      </span>
                      <span className="block text-sm font-medium leading-snug text-fg line-clamp-2">{c.fact.headline}</span>
                      {c.fallback && (
                        <span className="mt-1 block" title="Not every claim could be verified. Review before publishing.">
                          <Status tone="warning">Review before publishing</Status>
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="px-5 py-5 border-t border-border-subtle" aria-labelledby="copy-h">
            <h3 id="copy-h" className="text-[13px] font-medium text-fg-3">
              Copy
            </h3>
            <div className="mt-2.5 grid grid-cols-2 gap-2">
              <Button onClick={() => copy(linkedinText, "li")}>
                {copied === "li" ? <CheckIcon className="w-3.5 h-3.5" /> : <CopyIcon className="w-3.5 h-3.5" />}
                {copied === "li" ? "Copied" : "LinkedIn post"}
              </Button>
              <Button variant="secondary" onClick={() => copy(instagramText, "ig")}>
                {copied === "ig" ? <CheckIcon className="w-3.5 h-3.5 text-success" /> : <CopyIcon className="w-3.5 h-3.5" />}
                {copied === "ig" ? "Copied" : "Instagram caption"}
              </Button>
            </div>
            <p className="mt-2 min-h-[18px] text-[13px] text-fg-3" aria-live="polite">
              {copyError ? (
                <span className="text-danger">Your browser blocked copying. Select the text in the preview instead.</span>
              ) : (
                <span className="tabular-nums">
                  {(card.post?.linkedin?.length ?? 0).toLocaleString()} characters on LinkedIn,{" "}
                  {(card.post?.instagram_caption?.length ?? 0).toLocaleString()} on Instagram
                </span>
              )}
            </p>
            {tags.length > 0 && <p className="mt-2 text-[13px] leading-relaxed text-fg-2 break-words">{tags.join(" ")}</p>}
          </section>

          <section className="px-5 py-5 border-t border-border-subtle" aria-labelledby="src-h">
            <h3 id="src-h" className="text-[13px] font-medium text-fg-3">
              Sources
            </h3>
            <blockquote className="mt-2.5 text-[13px] leading-relaxed text-fg-2 border-l-2 border-border-strong pl-3">
              &ldquo;{card.fact.quote}&rdquo;
            </blockquote>
            <ul className="mt-3 border-t border-border-subtle">
              {(card.sources || []).map((s, i) => (
                <li key={`${s.url}-${i}`} className="border-b border-border-subtle">
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="group block py-2.5 -mx-2 px-2 rounded-md hover:bg-bg-subtle transition-colors duration-[120ms]"
                  >
                    <span className="block text-[13px] font-medium text-fg line-clamp-2 group-hover:underline underline-offset-2">
                      {s.title || s.url}
                    </span>
                    <span className="block text-[12px] text-fg-3 truncate mt-0.5">
                      {s.url.replace(/^https?:\/\//, "")}
                      {s.date ? `, ${s.date}` : ""}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        {/* Right: platform preview */}
        <section className="bg-bg-subtle min-h-[640px] flex flex-col min-w-0" aria-label="Preview">
          <div className="flex flex-wrap items-end justify-between gap-x-6 px-5 sm:px-6 border-b border-border">
            <Tabs
              label="Platform"
              value={platform}
              onChange={(v) => setPlatform(v as Platform)}
              options={[
                { value: "linkedin", label: "LinkedIn" },
                { value: "instagram", label: "Instagram" },
              ]}
            />
            {platform === "linkedin" && (
              <Tabs
                label="Device"
                value={device}
                onChange={(v) => setDevice(v as Device)}
                options={[
                  { value: "desktop", label: "Desktop" },
                  { value: "mobile", label: "Mobile" },
                ]}
              />
            )}
          </div>

          <div className="flex-1 flex items-start justify-center px-4 py-8" key={`${card.id}-${platform}-${device}`}>
            <div className="animate-fade w-full flex justify-center">
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
            <div className="flex items-center justify-center gap-2 pb-6 text-[13px] text-fg-2">
              <IconButton label="Previous post" disabled={sel === 0} onClick={() => setSel((s) => s - 1)}>
                <ChevronLeftIcon className="w-4 h-4" />
              </IconButton>
              <span className="tabular-nums min-w-[88px] text-center">
                Post {sel + 1} of {shown.length}
              </span>
              <IconButton label="Next post" disabled={sel === shown.length - 1} onClick={() => setSel((s) => s + 1)}>
                <ChevronRightIcon className="w-4 h-4" />
              </IconButton>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/** Text tabs with a 2px accent underline on the active tab. Arrow keys move between tabs. */
function Tabs({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : -1) + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex items-center gap-5">
      {options.map((o, i) => {
        const on = value === o.value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={`relative h-11 text-sm font-medium cursor-pointer rounded-sm transition-colors duration-[120ms] ease-out ${
              on ? "text-fg" : "text-fg-3 hover:text-fg"
            }`}
          >
            {o.label}
            <span
              aria-hidden
              className={`absolute inset-x-0 -bottom-px h-0.5 bg-accent origin-center transition-transform duration-[160ms] ease-out ${
                on ? "scale-x-100" : "scale-x-0"
              }`}
            />
          </button>
        );
      })}
    </div>
  );
}
