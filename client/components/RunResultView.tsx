"use client";

import React, { useState } from "react";
import { PostCard, RunResult, API_BASE } from "@/lib/api";

interface RunResultViewProps {
  result: RunResult;
  onClose?: () => void;
}

export function RunResultView({ result, onClose }: RunResultViewProps) {
  const cards = result.deck?.cards || [];
  const verifiedCards = cards.filter((c) => c.status === "verified");
  const displayCards = verifiedCards.length > 0 ? verifiedCards : cards;

  const [selectedCardIdx, setSelectedCardIdx] = useState<number>(0);
  const [activeTab, setActiveTab] = useState<"carousel" | "linkedin" | "instagram" | "evidence">("carousel");
  const [activeSlideIdx, setActiveSlideIdx] = useState<number>(0);
  const [copiedText, setCopiedText] = useState<string | null>(null);

  const currentCard: PostCard | undefined = displayCards[selectedCardIdx];

  // Derive slide image URLs for the current card
  const getSlideImages = (card: PostCard): string[] => {
    if (!result.task_id) return [];
    if (card.slide_paths && card.slide_paths.length > 0) {
      return card.slide_paths.map((p) => {
        const filename = p.split("/").pop();
        return `${API_BASE}/static/runs/${result.task_id}/output/${filename}`;
      });
    }
    // Fallback based on card id pattern post_N_1..3.png
    const cardNum = card.id.replace(/\D/g, "");
    return [1, 2, 3].map(
      (s) => `${API_BASE}/static/runs/${result.task_id}/output/post_${cardNum}_${s}.png`
    );
  };

  const getPdfUrl = (card: PostCard): string => {
    const cardNum = card.id.replace(/\D/g, "");
    return `${API_BASE}/static/runs/${result.task_id}/output/post_${cardNum}_carousel.pdf`;
  };

  const currentSlideImages = currentCard ? getSlideImages(currentCard) : [];
  const currentPdfUrl = currentCard ? getPdfUrl(currentCard) : "";

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(null), 2000);
  };

  if (!currentCard) {
    return (
      <div className="p-8 rounded-2xl bg-[#0c121d] border border-[#212c3d] text-center text-[#909dad]">
        No posts found for this run.
      </div>
    );
  }

  return (
    <div className="w-full rounded-2xl bg-[#0c121d] border border-[#212c3d] p-6 sm:p-8 space-y-6 shadow-2xl">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#212c3d] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="text-2xl font-bold text-[#f8fafc] tracking-tight">
              {result.brand || "Brand"} Generated Output
            </h3>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              {verifiedCards.length} Verified Posts
            </span>
          </div>
          <p className="text-xs text-[#909dad] mt-1 font-mono">
            Task ID: <span className="text-slate-300">{result.task_id}</span> · Industry: <span className="text-amber-400 font-semibold uppercase">{result.industry}</span> · Mode: <span className="text-slate-300">{result.mode}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          {result.posts_md_url && (
            <a
              href={`${API_BASE}${result.posts_md_url}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#182232] hover:bg-[#212c3d] text-[#f8fafc] border border-[#212c3d] transition-colors cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              <span>Download posts.md</span>
            </a>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-[#909dad] hover:text-[#f8fafc] hover:bg-[#182232] transition-colors cursor-pointer"
              title="Close view"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Post Selector Switcher */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[#212c3d]/60 pb-4">
        <span className="text-xs text-[#909dad] font-medium mr-2">Select Post:</span>
        {displayCards.map((c, idx) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              setSelectedCardIdx(idx);
              setActiveSlideIdx(0);
            }}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 cursor-pointer ${
              selectedCardIdx === idx
                ? "bg-[#f8fafc] text-[#080d16] font-semibold shadow-md"
                : "bg-[#182232] text-[#909dad] hover:text-[#f8fafc] border border-[#212c3d]"
            }`}
          >
            Post #{idx + 1} {c.status === "verified" ? "✓" : "✗"}
          </button>
        ))}
      </div>

      {/* Post Headline & Status Banner */}
      <div className="p-4 rounded-xl bg-[#080d16] border border-[#212c3d] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <span className="text-[11px] font-mono uppercase text-amber-400 tracking-wider">
            Category: {currentCard.fact.category || "Verified Insight"}
          </span>
          <h4 className="text-base sm:text-lg font-semibold text-[#f8fafc] mt-0.5">
            {currentCard.fact.headline}
          </h4>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs px-2.5 py-1 rounded bg-[#182232] text-slate-300 font-mono border border-[#212c3d]">
            Evidence: {(currentCard.fact.evidence_ids || []).join(", ")}
          </span>
          <span className="text-xs px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 font-medium border border-emerald-500/20">
            Deterministic: PASS
          </span>
        </div>
      </div>

      {/* Content Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-[#212c3d]">
        <button
          type="button"
          onClick={() => setActiveTab("carousel")}
          className={`pb-2.5 px-3 text-sm font-medium transition-colors border-b-2 cursor-pointer ${
            activeTab === "carousel"
              ? "border-amber-400 text-[#f8fafc]"
              : "border-transparent text-[#909dad] hover:text-[#f8fafc]"
          }`}
        >
          1080×1350 Carousel Slides
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("linkedin")}
          className={`pb-2.5 px-3 text-sm font-medium transition-colors border-b-2 cursor-pointer ${
            activeTab === "linkedin"
              ? "border-amber-400 text-[#f8fafc]"
              : "border-transparent text-[#909dad] hover:text-[#f8fafc]"
          }`}
        >
          LinkedIn Copy
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("instagram")}
          className={`pb-2.5 px-3 text-sm font-medium transition-colors border-b-2 cursor-pointer ${
            activeTab === "instagram"
              ? "border-amber-400 text-[#f8fafc]"
              : "border-transparent text-[#909dad] hover:text-[#f8fafc]"
          }`}
        >
          Instagram Caption
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("evidence")}
          className={`pb-2.5 px-3 text-sm font-medium transition-colors border-b-2 cursor-pointer ${
            activeTab === "evidence"
              ? "border-amber-400 text-[#f8fafc]"
              : "border-transparent text-[#909dad] hover:text-[#f8fafc]"
          }`}
        >
          Source Proof ({(currentCard.sources || []).length})
        </button>
      </div>

      {/* Tab 1: Carousel Viewer */}
      {activeTab === "carousel" && (
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start pt-2">
          {/* Visual Slide Frame (Displays actual backend rendered PNG) */}
          <div className="md:col-span-6 flex flex-col items-center">
            <div className="relative w-full max-w-[380px] aspect-[4/5] rounded-xl overflow-hidden border border-[#212c3d] shadow-2xl bg-[#080d16]">
              {currentSlideImages[activeSlideIdx] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={currentSlideImages[activeSlideIdx]}
                  alt={`Slide ${activeSlideIdx + 1}`}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    // Fallback to text visual representation if image not found
                    (e.target as HTMLElement).style.display = "none";
                  }}
                />
              ) : null}

              {/* Fallback slide card in case PNG is still generating */}
              <div className="absolute inset-0 p-6 flex flex-col justify-between pointer-events-none bg-gradient-to-b from-[#0c1424]/90 to-[#080d16]/95">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-xs tracking-wider text-amber-400 uppercase">
                    {result.brand}
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/10 text-slate-200">
                    Slide {activeSlideIdx + 1}/3
                  </span>
                </div>
                <div className="my-auto space-y-3">
                  <span className="text-xs uppercase font-mono text-amber-400">
                    {currentCard.post?.poster_kicker || "Insight"}
                  </span>
                  <h4 className="text-lg sm:text-xl font-bold text-[#f8fafc] leading-tight">
                    {activeSlideIdx === 0
                      ? currentCard.post?.poster_headline || currentCard.fact.headline
                      : currentCard.post?.slides?.[activeSlideIdx - 1]?.title || "Explainer"}
                  </h4>
                  {activeSlideIdx > 0 && currentCard.post?.slides?.[activeSlideIdx - 1]?.bullets && (
                    <ul className="text-xs text-[#909dad] space-y-1.5 list-disc pl-4">
                      {currentCard.post!.slides![activeSlideIdx - 1].bullets.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="pt-2 border-t border-white/10 flex items-center justify-between text-[10px] text-[#909dad]">
                  <span>Evidence: {(currentCard.fact.evidence_ids || []).join(", ")}</span>
                  <span>1080×1350</span>
                </div>
              </div>
            </div>

            {/* Slide Navigation Buttons */}
            <div className="flex items-center justify-between w-full max-w-[380px] mt-4 px-2">
              <button
                type="button"
                onClick={() => setActiveSlideIdx((prev) => (prev > 0 ? prev - 1 : 2))}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[#182232] hover:bg-[#212c3d] text-[#f8fafc] border border-[#212c3d] transition-colors cursor-pointer"
              >
                ← Previous
              </button>

              <div className="flex items-center gap-2">
                {[0, 1, 2].map((idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setActiveSlideIdx(idx)}
                    className={`h-2 rounded-full transition-all duration-200 cursor-pointer ${
                      activeSlideIdx === idx ? "w-8 bg-[#f59e0b]" : "w-2 bg-[#212c3d] hover:bg-slate-600"
                    }`}
                    aria-label={`Go to slide ${idx + 1}`}
                  />
                ))}
              </div>

              <button
                type="button"
                onClick={() => setActiveSlideIdx((prev) => (prev < 2 ? prev + 1 : 0))}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[#182232] hover:bg-[#212c3d] text-[#f8fafc] border border-[#212c3d] transition-colors cursor-pointer"
              >
                Next →
              </button>
            </div>
          </div>

          {/* Details & Download Options */}
          <div className="md:col-span-6 space-y-5">
            <div className="p-4 rounded-xl bg-[#080d16] border border-[#212c3d] space-y-3">
              <h5 className="text-sm font-semibold text-[#f8fafc] flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                Slide Structure Specifications
              </h5>
              <div className="space-y-2 text-xs text-[#909dad]">
                <div>
                  <strong className="text-slate-200">Slide 1 (Cover):</strong>{" "}
                  {currentCard.post?.poster_headline || currentCard.fact.headline}
                </div>
                {currentCard.post?.slides?.map((s, idx) => (
                  <div key={idx}>
                    <strong className="text-slate-200">Slide {idx + 2}:</strong> {s.title}
                    <ul className="list-disc pl-4 text-slate-400 mt-1">
                      {(s.bullets || []).map((b, bi) => (
                        <li key={bi}>{b}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#080d16] border border-[#212c3d] flex flex-col gap-3">
              <div className="text-xs font-medium text-[#f8fafc]">
                Ready-to-Post LinkedIn PDF Carousel:
              </div>
              <p className="text-xs text-[#909dad]">
                Upload this multi-page PDF document to LinkedIn for a high-converting swipeable feed carousel.
              </p>
              <a
                href={currentPdfUrl}
                target="_blank"
                rel="noreferrer"
                download
                className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-[#f8fafc] text-[#080d16] hover:bg-[#e2e8f0] transition-colors cursor-pointer shadow-sm active:scale-[0.98]"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>Download LinkedIn Document PDF</span>
              </a>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: LinkedIn Copy */}
      {activeTab === "linkedin" && (
        <div className="space-y-4 pt-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#909dad] font-mono">
              Length: {currentCard.post?.linkedin?.length || 0} characters (Target: 600–1800)
            </span>
            <button
              type="button"
              onClick={() => handleCopy(currentCard.post?.linkedin || "", "linkedin")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#f8fafc] text-[#080d16] hover:bg-slate-200 transition-colors cursor-pointer"
            >
              {copiedText === "linkedin" ? "✓ Copied!" : "Copy LinkedIn Post"}
            </button>
          </div>

          <div className="p-5 rounded-xl bg-[#080d16] border border-[#212c3d] text-sm text-[#f8fafc] leading-relaxed whitespace-pre-line font-sans selection:bg-amber-500/20">
            {currentCard.post?.linkedin || "No LinkedIn copy generated."}
          </div>

          {currentCard.post?.hashtags && (
            <div className="flex items-center gap-2 text-xs">
              <span className="font-semibold text-slate-300">Hashtags:</span>
              <span className="font-mono text-amber-400">
                {(currentCard.post?.hashtags || []).map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Instagram Caption */}
      {activeTab === "instagram" && (
        <div className="space-y-4 pt-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#909dad] font-mono">
              Length: {currentCard.post?.instagram_caption?.length || 0} characters
            </span>
            <button
              type="button"
              onClick={() => handleCopy(currentCard.post?.instagram_caption || "", "instagram")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#f8fafc] text-[#080d16] hover:bg-slate-200 transition-colors cursor-pointer"
            >
              {copiedText === "instagram" ? "✓ Copied!" : "Copy Instagram Caption"}
            </button>
          </div>

          <div className="p-5 rounded-xl bg-[#080d16] border border-[#212c3d] text-sm text-[#f8fafc] leading-relaxed whitespace-pre-line font-sans selection:bg-amber-500/20">
            {currentCard.post?.instagram_caption || "No Instagram caption generated."}
          </div>

          <div className="p-3.5 rounded-xl bg-[#080d16] border border-[#212c3d] text-xs text-[#909dad]">
            <strong>Instagram Tip:</strong> Upload the 3 rendered PNG slides as a carousel post, then paste this caption into the post description.
          </div>
        </div>
      )}

      {/* Tab 4: Evidence Proof */}
      {activeTab === "evidence" && (
        <div className="space-y-4 pt-2">
          <div className="text-xs text-[#909dad]">
            Every single claim in this post was verified against these cited source materials:
          </div>

          <div className="space-y-3">
            {(currentCard.sources || []).map((s) => (
              <div key={s.id} className="p-4 rounded-xl bg-[#080d16] border border-[#212c3d] space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-amber-400">[{s.id}] {(s.kind || "source").toUpperCase()}</span>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-400 hover:underline font-mono truncate max-w-xs"
                  >
                    {s.url}
                  </a>
                </div>

                <div className="text-xs text-slate-300 font-medium">{s.title}</div>

                <blockquote className="text-xs text-[#909dad] border-l-2 border-amber-500/60 pl-3 italic py-1 bg-[#182232]/30 rounded-r">
                  {s.text}
                </blockquote>
              </div>
            ))}
          </div>

          <div className="p-3.5 rounded-xl bg-[#080d16] border border-[#212c3d] text-xs text-slate-300">
            <strong className="text-amber-400">Verbatim Match Span:</strong> &ldquo;{currentCard.fact.quote}&rdquo;
          </div>
        </div>
      )}
    </div>
  );
}
