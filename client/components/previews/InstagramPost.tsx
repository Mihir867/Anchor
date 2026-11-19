"use client";

import React, { useRef, useState } from "react";
import { BrandAvatar, Carousel, ClampedText, PhoneFrame, PreviewProps, RichText } from "./shared";

/** An Instagram feed carousel post inside the iOS app chrome. Double-tap the image or tap the
 * heart to like; swipe or use the arrows to move through slides. */
export function InstagramPost({ brand, handle, logoUrl, brandColor, text, images }: PreviewProps) {
  const [idx, setIdx] = useState(0);
  const [liked, setLiked] = useState(false);
  const [saved, setSaved] = useState(false);
  const [burst, setBurst] = useState(0);
  const burstTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const n = images.length;

  const doubleTap = () => {
    setLiked(true);
    setBurst((b) => b + 1);
    if (burstTimer.current) clearTimeout(burstTimer.current);
    burstTimer.current = setTimeout(() => setBurst(0), 950);
  };

  return (
    <PhoneFrame>
      <div className="flex flex-col h-full" style={{ fontFamily: "var(--font-platform)" }}>
        {/* App top bar */}
        <div className="h-11 shrink-0 px-4 flex items-center justify-between">
          <span className="text-[24px] font-semibold tracking-tight" style={{ fontFamily: "'Snell Roundhand','Brush Script MT',cursive" }}>
            Instagram
          </span>
          <span className="flex items-center gap-5">
            <IgIcon d="M16.8 3C19.6 3 22 5.4 22 8.5c0 5.6-7.4 10.6-10 12.5C9.4 19.1 2 14.1 2 8.5 2 5.4 4.4 3 7.2 3c1.9 0 3.6 1 4.8 2.6C13.2 4 14.9 3 16.8 3z" />
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" aria-hidden>
              <path d="M12 2.5C6.6 2.5 2.5 6.4 2.5 11.5c0 2.7 1.1 5 3 6.6v3.4l3.2-1.8c1 .3 2.1.4 3.3.4 5.4 0 9.5-3.9 9.5-9S17.4 2.5 12 2.5z" />
              <path d="M6.5 14l3.5-3.7 2.5 2.4 5-3.2-3.5 3.7-2.5-2.4z" fill="currentColor" />
            </svg>
          </span>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar">
          {/* Post header */}
          <header className="flex items-center gap-2.5 px-3 py-2">
            <span className="rounded-full p-[2px] bg-[conic-gradient(from_200deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5,#feda75)]">
              <span className="block rounded-full p-[1.5px] bg-white">
                <BrandAvatar brand={brand} logoUrl={logoUrl} color={brandColor} size={32} />
              </span>
            </span>
            <div className="flex-1 min-w-0 leading-tight">
              <div className="flex items-center gap-1 text-[14px] font-semibold">
                <span className="truncate">{handle}</span>
                <svg width="13" height="13" viewBox="0 0 40 40" aria-label="Verified">
                  <path fill="#0095f6" d="M19.998 3.094 14.638 0l-2.972 5.15H5.432v6.354L0 14.64 3.094 20 0 25.359l5.432 3.137v5.905h5.975L14.638 40l5.36-3.094L25.358 40l3.232-5.6h6.162v-6.01L40 25.359 36.905 20 40 14.641l-5.248-3.03v-6.46h-6.419L25.358 0l-5.36 3.094Zm7.415 11.225 2.254 2.287-11.43 11.5-6.835-6.93 2.244-2.258 4.587 4.581 9.18-9.18Z" />
                </svg>
              </div>
            </div>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-label="More options">
              <circle cx="12" cy="12" r="1.5" />
              <circle cx="6" cy="12" r="1.5" />
              <circle cx="18" cy="12" r="1.5" />
            </svg>
          </header>

          {/* Media */}
          <Carousel
            images={images}
            index={idx}
            onIndex={setIdx}
            aspect="4 / 5"
            onDoubleTap={doubleTap}
            arrowClass="w-7 h-7 bg-white/85 text-[#262626] shadow opacity-0 group-hover/carousel:opacity-100"
          >
            {n > 1 && (
              <span className="pointer-events-none absolute top-3 right-3 rounded-full bg-[#121212]/70 px-2 py-[3px] text-[12px] font-medium text-white tabular-nums">
                {idx + 1}/{n}
              </span>
            )}
            {burst > 0 && (
              <span key={burst} className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <svg className="w-24 h-24 animate-heart drop-shadow-[0_4px_16px_rgba(0,0,0,0.35)]" viewBox="0 0 24 24" fill="white" aria-hidden>
                  <path d="M16.8 3C19.6 3 22 5.4 22 8.5c0 5.6-7.4 10.6-10 12.5C9.4 19.1 2 14.1 2 8.5 2 5.4 4.4 3 7.2 3c1.9 0 3.6 1 4.8 2.6C13.2 4 14.9 3 16.8 3z" />
                </svg>
              </span>
            )}
          </Carousel>

          {/* Actions */}
          <div className="relative flex items-center px-3 pt-2.5 pb-1">
            <div className="flex items-center gap-4">
              <button type="button" aria-label={liked ? "Unlike" : "Like"} onClick={() => setLiked((l) => !l)} className="cursor-pointer">
                <svg
                  key={String(liked)}
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  className={liked ? "animate-pop" : ""}
                  fill={liked ? "#ff3040" : "none"}
                  stroke={liked ? "#ff3040" : "currentColor"}
                  strokeWidth="1.9"
                  aria-hidden
                >
                  <path d="M16.8 3C19.6 3 22 5.4 22 8.5c0 5.6-7.4 10.6-10 12.5C9.4 19.1 2 14.1 2 8.5 2 5.4 4.4 3 7.2 3c1.9 0 3.6 1 4.8 2.6C13.2 4 14.9 3 16.8 3z" />
                </svg>
              </button>
              <IgIcon d="M20.66 16.93A9.5 9.5 0 1 0 17.2 20.4L21.5 21.5Z" />
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" aria-hidden>
                <path d="M22 3 9.2 10.1M22 3l-7.6 18.3-5.2-11.2L2 6.7z" />
              </svg>
            </div>
            {n > 1 && (
              <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-[4px]">
                {images.map((_, i) => (
                  <span
                    key={i}
                    className={`rounded-full transition-all duration-200 ${i === idx ? "w-[6px] h-[6px] bg-[#0095f6]" : "w-[6px] h-[6px] bg-[#a8a8a8]"}`}
                  />
                ))}
              </div>
            )}
            <button type="button" aria-label="Save" onClick={() => setSaved((s) => !s)} className="ml-auto cursor-pointer">
              <svg width="24" height="24" viewBox="0 0 24 24" fill={saved ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" aria-hidden>
                <path d="M20 21 12 13.44 4 21V3h16z" />
              </svg>
            </button>
          </div>

          {/* Likes, caption, time */}
          <div className="px-3 pb-6 text-[14px] text-[#0c1014] space-y-1">
            {liked && <div className="font-semibold animate-fade-up">Liked by you</div>}
            <ClampedText lines={2} lineHeight={18} moreClass="text-[14px] text-[#737373]">
              <span className="font-semibold mr-1.5">{handle}</span>
              <RichText text={text} links={false} linkClass="text-[#00376b]" />
            </ClampedText>
            <div className="text-[#737373] text-[14px]">Add a comment…</div>
            <div className="text-[12px] text-[#737373]">Just now</div>
          </div>
        </div>

        {/* Tab bar */}
        <nav className="h-[78px] shrink-0 border-t border-[#dbdbdb] flex items-start justify-around pt-3 bg-white" aria-hidden>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor">
            <path d="M22 23h-6.001a1 1 0 0 1-1-1v-5.455a2.997 2.997 0 1 0-5.993 0V22a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V11.543a1.002 1.002 0 0 1 .31-.724l10-9.543a1.001 1.001 0 0 1 1.38 0l10 9.543a1.002 1.002 0 0 1 .31.724V22a1 1 0 0 1-1 1Z" />
          </svg>
          <IgIcon d="M10.5 3.5a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5.6-5.6" size={26} />
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden>
            <rect x="2.5" y="2.5" width="19" height="19" rx="5" />
            <path d="M12 7.5v9M7.5 12h9" strokeLinecap="round" />
          </svg>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden>
            <rect x="2.5" y="2.5" width="19" height="19" rx="5" />
            <path d="M2.5 8h19M9 2.5 12 8M15 2.5 18 8" />
            <path d="M10 11.5v6l5-3z" fill="currentColor" stroke="none" />
          </svg>
          <BrandAvatar brand={brand} logoUrl={logoUrl} color={brandColor} size={26} />
        </nav>
      </div>
    </PhoneFrame>
  );
}

function IgIcon({ d, size = 24 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}
