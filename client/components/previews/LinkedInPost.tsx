"use client";

import React, { useState } from "react";
import { BrandAvatar, Carousel, ClampedText, PhoneFrame, PreviewProps, RichText } from "./shared";

const INK = "rgba(0,0,0,0.9)";
const SUB = "rgba(0,0,0,0.6)";
const BLUE = "#0a66c2";

/** A LinkedIn feed post with a document (PDF-style) carousel, as it renders on desktop or in the
 * mobile app. Like is interactive so the preview feels alive. */
export function LinkedInPost({
  brand,
  domain,
  logoUrl,
  brandColor,
  text,
  images,
  title,
  variant = "desktop",
}: PreviewProps & { variant?: "desktop" | "mobile" }) {
  const [idx, setIdx] = useState(0);
  const [liked, setLiked] = useState(false);
  const [following, setFollowing] = useState(false);
  const n = images.length;
  const mobile = variant === "mobile";

  return (
    <article
      className={`bg-white overflow-hidden ${mobile ? "w-full" : "w-[555px] max-w-full rounded-lg shadow-[0_0_0_1px_rgba(140,140,140,0.2)]"}`}
      style={{ fontFamily: "var(--font-platform)", color: INK }}
    >
      {/* Actor */}
      <header className={`flex items-start gap-2 ${mobile ? "px-3 pt-3" : "px-4 pt-3"} pb-2`}>
        <BrandAvatar brand={brand} logoUrl={logoUrl} color={brandColor} size={48} shape="square" />
        <div className="flex-1 min-w-0 leading-[1.33]">
          <div className="text-[14px] font-semibold truncate hover:underline hover:text-[#0a66c2] cursor-pointer">{brand}</div>
          {domain && (
            <div className="text-[12px] truncate" style={{ color: SUB }}>
              {domain}
            </div>
          )}
          <div className="text-[12px] flex items-center gap-1" style={{ color: SUB }}>
            <span>1h •</span>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-label="Visible to anyone on or off LinkedIn">
              <path d="M8 1a7 7 0 107 7 7 7 0 00-7-7zM3 8a5 5 0 011-3l.64.36A1.27 1.27 0 015.38 6.5v.28a1 1 0 00.5.87l.38.22a1 1 0 01.5.87V10a1 1 0 00.5.87A4.94 4.94 0 013 8zm8.77 3.75l-.4-.4a1.28 1.28 0 00-.9-.35h-.47a.5.5 0 01-.5-.5v-.13a1 1 0 00-.55-.89L8 9V7.5h1.5A1.5 1.5 0 0011 6V4.42a5 5 0 01.77 7.33z" />
            </svg>
          </div>
        </div>
        {!mobile && (
          <button type="button" aria-label="More options" className="w-8 h-8 -mt-1 rounded-full flex items-center justify-center hover:bg-black/[0.08] cursor-pointer" style={{ color: SUB }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M14 12a2 2 0 11-2-2 2 2 0 012 2zM4 10a2 2 0 102 2 2 2 0 00-2-2zm16 0a2 2 0 102 2 2 2 0 00-2-2z" />
            </svg>
          </button>
        )}
        <button
          type="button"
          onClick={() => setFollowing((f) => !f)}
          className="-mt-0.5 flex items-center gap-1 h-8 px-2 rounded text-[16px] font-semibold hover:bg-[#0a66c2]/10 cursor-pointer"
          style={{ color: following ? SUB : BLUE }}
        >
          {following ? (
            <>✓ <span className="text-[14px]">Following</span></>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                <path d="M14 9H9v5H7V9H2V7h5V2h2v5h5z" />
              </svg>
              <span className="text-[14px]">Follow</span>
            </>
          )}
        </button>
      </header>

      {/* Commentary */}
      <div className={`${mobile ? "px-3" : "px-4"} pb-2 text-[14px]`}>
        <ClampedText lines={3} lineHeight={20} moreClass="text-[14px] text-[rgba(0,0,0,0.6)] hover:text-[#0a66c2] hover:underline">
          <RichText text={text} linkClass="font-semibold text-[#0a66c2] hover:underline cursor-pointer" />
        </ClampedText>
      </div>

      {/* Document carousel: title on hover, page controls under the document (as on LinkedIn) */}
      <div className="bg-black/[0.04]">
        <Carousel
          images={images}
          index={idx}
          onIndex={setIdx}
          aspect="4 / 5"
          arrowClass="w-10 h-10 bg-black/60 text-white hover:bg-black/80 shadow-md"
        >
          {n > 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-0 px-3 pt-2.5 pb-8 bg-gradient-to-b from-black/60 to-transparent text-white text-[14px] font-semibold truncate opacity-0 group-hover/carousel:opacity-100 transition-opacity">
              {title || brand} <span className="font-normal opacity-90">• {n} pages</span>
            </div>
          )}
        </Carousel>
        {n > 0 && (
          <div className="h-10 px-3 flex items-center gap-3 bg-[#1d2226] text-white text-[12px]">
            <span className="tabular-nums w-10 shrink-0">
              {idx + 1} / {n}
            </span>
            <input
              type="range"
              min={0}
              max={Math.max(n - 1, 0)}
              value={idx}
              onChange={(e) => setIdx(Number(e.target.value))}
              aria-label="Page"
              className="flex-1 h-1 accent-white cursor-pointer"
            />
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-label="Fullscreen">
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            </svg>
          </div>
        )}
      </div>

      {/* Social counts (only once the viewer reacts: we don't invent engagement) */}
      {liked && (
        <div className={`${mobile ? "px-3" : "px-4"} pt-2 flex items-center gap-1 text-[12px] animate-fade-up`} style={{ color: SUB }}>
          <span className="w-4 h-4 rounded-full bg-[#378fe9] flex items-center justify-center ring-[1.5px] ring-white">
            <ThumbIcon filled className="w-2.5 h-2.5 text-white" />
          </span>
          <span>You</span>
        </div>
      )}

      {/* Actions */}
      <div className={`${mobile ? "mx-1" : "mx-3"} mt-1 border-t border-black/[0.08] flex justify-between py-1`}>
        <Action label="Like" active={liked} onClick={() => setLiked((l) => !l)}>
          <ThumbIcon filled={liked} className={`w-5 h-5 ${liked ? "animate-pop" : ""}`} />
        </Action>
        <Action label="Comment">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M7 9h10v1H7zm0 4h7v-1H7zm16-2a6.78 6.78 0 01-2.84 5.61L12 22v-4H8A7 7 0 018 4h8a7 7 0 017 7zm-2 0a5 5 0 00-5-5H8a5 5 0 000 10h6v2.28L19 15a4.79 4.79 0 002-4z" />
          </svg>
        </Action>
        <Action label="Repost">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M13.96 5H6c-.55 0-1 .45-1 1v10H3V6c0-1.66 1.34-3 3-3h7.96L12 0h2.37L17 4l-2.63 4H12l1.96-3zm5.54 3H19v10c0 .55-.45 1-1 1h-7.96L12 16H9.63L7 20l2.63 4H12l-1.96-3H18c1.66 0 3-1.34 3-3V8h-1.5z" />
          </svg>
        </Action>
        <Action label="Send">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M21 3L0 10l7.66 4.26L16 8l-6.26 8.34L14 24l7-21z" />
          </svg>
        </Action>
      </div>
    </article>
  );
}

function Action({ label, active, onClick, children }: { label: string; active?: boolean; onClick?: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex-1 flex items-center justify-center gap-1.5 h-12 rounded text-[14px] font-semibold hover:bg-black/[0.08] cursor-pointer transition-colors"
      style={{ color: active ? BLUE : SUB }}
    >
      {children}
      <span className="max-[400px]:hidden">{label}</span>
    </button>
  );
}

function ThumbIcon({ filled, className }: { filled?: boolean; className?: string }) {
  return filled ? (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M19.46 11l-3.91-3.91a7 7 0 01-1.69-2.74l-.49-1.47A2.76 2.76 0 0010.76 1 2.75 2.75 0 008 3.74v1.12a9.19 9.19 0 00.46 2.85L8.89 9H4.12A2.12 2.12 0 002 11.12a2.16 2.16 0 00.92 1.76A2.11 2.11 0 002 14.62a2.14 2.14 0 001.28 2 2 2 0 00-.28 1 2.12 2.12 0 002 2.12v.14A2.12 2.12 0 007.12 22h7.49a8.08 8.08 0 003.58-.84l.31-.16H21V11z" />
    </svg>
  ) : (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M19.46 11l-3.91-3.91a7 7 0 01-1.69-2.74l-.49-1.47A2.76 2.76 0 0010.76 1 2.75 2.75 0 008 3.74v1.12a9.19 9.19 0 00.46 2.85L8.89 9H4.12A2.12 2.12 0 002 11.12a2.16 2.16 0 00.92 1.76A2.11 2.11 0 002 14.62a2.14 2.14 0 001.28 2 2 2 0 00-.28 1 2.12 2.12 0 002 2.12v.14A2.12 2.12 0 007.12 22h7.49a8.08 8.08 0 003.58-.84l.31-.16H21V11zM19 19h-1l-.73.37a6.14 6.14 0 01-2.69.63H7.72a1 1 0 01-1-.72l-.25-.87-.85-.41A1 1 0 015 17l.17-1-.76-.74A1 1 0 014.27 14l.66-1.09-.73-1.1a.49.49 0 01.08-.7.48.48 0 01.34-.11h7.05l-1.31-3.92A7 7 0 0110 4.86V3.75a.77.77 0 01.75-.75.75.75 0 01.71.51L12 5a9 9 0 002.13 3.5l4.5 4.5H19z" />
    </svg>
  );
}

/** The post inside the LinkedIn iOS app: search header, feed background, bottom tab bar. */
export function LinkedInApp(props: PreviewProps) {
  return (
    <PhoneFrame>
      <div className="flex flex-col h-full bg-[#f4f2ee]" style={{ fontFamily: "var(--font-platform)" }}>
        <div className="h-12 shrink-0 bg-white px-3 flex items-center gap-2.5 border-b border-black/[0.06]">
          <BrandAvatar brand="You" color="#8c8c8c" size={30} />
          <div className="flex-1 h-8 rounded bg-[#edf3f8] flex items-center gap-2 px-2.5 text-[14px] text-[rgba(0,0,0,0.6)]">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="M20 20l-4.6-4.6" strokeLinecap="round" />
            </svg>
            Search
          </div>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="rgba(0,0,0,0.6)" aria-hidden>
            <path d="M16 4H8a7 7 0 000 14h4v4l8.16-5.39A6.78 6.78 0 0023 11a7 7 0 00-7-7zm-8 8.25A1.25 1.25 0 119.25 11 1.25 1.25 0 018 12.25zm4 0A1.25 1.25 0 1113.25 11 1.25 1.25 0 0112 12.25zm4 0A1.25 1.25 0 1117.25 11 1.25 1.25 0 0116 12.25z" />
          </svg>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar pt-2 pb-4">
          <LinkedInPost {...props} variant="mobile" />
        </div>
        <nav className="h-[78px] shrink-0 bg-white border-t border-black/[0.08] grid grid-cols-5 pt-2 text-[10px] text-[rgba(0,0,0,0.6)]" aria-hidden>
          {[
            ["Home", "M23 9v2h-2v7a3 3 0 01-3 3h-4v-6h-4v6H6a3 3 0 01-3-3v-7H1V9l11-7z"],
            ["My Network", "M12 16v6H3v-6a3 3 0 013-3h3a3 3 0 013 3zm5.5-3A3.5 3.5 0 1014 9.5a3.5 3.5 0 003.5 3.5zm1 2h-2a2.5 2.5 0 00-2.5 2.5V22h7v-4.5a2.5 2.5 0 00-2.5-2.5zM7.5 2A4.5 4.5 0 1012 6.5 4.49 4.49 0 007.5 2z"],
            ["Post", "M18 3H6a3 3 0 00-3 3v12a3 3 0 003 3h12a3 3 0 003-3V6a3 3 0 00-3-3zm-1 10h-4v4h-2v-4H7v-2h4V7h2v4h4z"],
            ["Notifications", "M22 19h-8.28a2 2 0 11-3.44 0H2v-1a4.52 4.52 0 011.17-2.83l1-1.17h15.7l1 1.17A4.42 4.42 0 0122 18zM18.21 7.44A6.27 6.27 0 0012 2a6.27 6.27 0 00-6.21 5.44L5 13h14z"],
            ["Jobs", "M17 6V5a3 3 0 00-3-3h-4a3 3 0 00-3 3v1H2v4a3 3 0 003 3h14a3 3 0 003-3V6zM9 5a1 1 0 011-1h4a1 1 0 011 1v1H9zm10 9a4 4 0 003-1.38V17a3 3 0 01-3 3H5a3 3 0 01-3-3v-4.38A4 4 0 005 14z"],
          ].map(([label, d], i) => (
            <span key={label} className={`flex flex-col items-center gap-0.5 ${i === 0 ? "text-black" : ""}`}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d={d} />
              </svg>
              {label}
            </span>
          ))}
        </nav>
      </div>
    </PhoneFrame>
  );
}
