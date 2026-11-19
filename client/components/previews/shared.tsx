"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { assetUrl } from "@/lib/api";

export interface PreviewProps {
  brand: string;
  handle: string;
  domain?: string;
  logoUrl?: string;
  brandColor?: string;
  text: string;
  images: string[];
  title?: string;
}

/** Instagram-style handle from the domain (salesforce.com -> salesforce) or the brand name. */
export function handleFor(brand: string, domain?: string): string {
  const fromDomain = domain?.replace(/^www\./, "").split(".")[0];
  return (fromDomain || brand).toLowerCase().replace(/[^a-z0-9._]/g, "") || "brand";
}

// ---- avatar ------------------------------------------------------------------------------

export function BrandAvatar({
  brand,
  logoUrl,
  color,
  size,
  shape = "circle",
}: {
  brand: string;
  logoUrl?: string;
  color?: string;
  size: number;
  shape?: "circle" | "square";
}) {
  const [failed, setFailed] = useState(false);
  const radius = shape === "circle" ? "9999px" : `${Math.round(size * 0.08)}px`;
  return (
    <span
      className="shrink-0 overflow-hidden flex items-center justify-center bg-white"
      style={{ width: size, height: size, borderRadius: radius, boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.08)" }}
    >
      {logoUrl && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={assetUrl(logoUrl)} alt="" onError={() => setFailed(true)} className="w-full h-full object-contain p-[8%]" />
      ) : (
        <span
          className="w-full h-full flex items-center justify-center text-white font-semibold"
          style={{ background: color || "#0a66c2", fontSize: size * 0.44 }}
        >
          {brand.trim().charAt(0).toUpperCase() || "B"}
        </span>
      )}
    </span>
  );
}

// ---- rich text ---------------------------------------------------------------------------

const WITH_LINKS = /(#[\p{L}\p{N}_]+|@[\p{L}\p{N}_.]+|https?:\/\/[^\s]+|www\.[^\s]+)/giu;
const TAGS_ONLY = /(#[\p{L}\p{N}_]+|@[\p{L}\p{N}_.]+)/giu;

/** Hashtags and @mentions highlighted; URLs too when the platform links them (LinkedIn does,
 * Instagram captions don't). */
export function RichText({ text, linkClass, links = true }: { text: string; linkClass: string; links?: boolean }) {
  return (
    <>
      {text.split(links ? WITH_LINKS : TAGS_ONLY).map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className={linkClass}>
            {part}
          </span>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}

/** Text clamped to N lines with an inline "…more" pinned to the end of the last line, the way
 * LinkedIn and Instagram truncate captions. Expands in place on click. */
export function ClampedText({
  lines,
  lineHeight,
  more = "more",
  moreClass,
  bg = "#ffffff",
  children,
}: {
  lines: number;
  lineHeight: number;
  more?: string;
  moreClass: string;
  bg?: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [expanded, children]);

  return (
    <div className="relative" style={{ lineHeight: `${lineHeight}px` }}>
      <div
        ref={ref}
        className="whitespace-pre-wrap break-words"
        style={expanded ? undefined : { maxHeight: lines * lineHeight, overflow: "hidden" }}
      >
        {children}
      </div>
      {overflows && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className={`absolute right-0 bottom-0 pl-6 cursor-pointer ${moreClass}`}
          style={{ background: `linear-gradient(to right, transparent, ${bg} 1.25rem)` }}
        >
          …{more}
        </button>
      )}
    </div>
  );
}

// ---- carousel ----------------------------------------------------------------------------

export function Carousel({
  images,
  index,
  onIndex,
  aspect = "4 / 5",
  onDoubleTap,
  children,
  arrowClass,
}: {
  images: string[];
  index: number;
  onIndex: (i: number) => void;
  aspect?: string;
  onDoubleTap?: () => void;
  /** Overlays (counters, hearts, control bars) rendered above the slides. */
  children?: React.ReactNode;
  arrowClass: string;
}) {
  const [loaded, setLoaded] = useState<Record<number, boolean>>({});
  const [broken, setBroken] = useState<Record<number, boolean>>({});
  const [drag, setDrag] = useState(0);
  const start = useRef<{ x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const n = images.length;

  const go = useCallback((i: number) => onIndex(Math.max(0, Math.min(n - 1, i))), [n, onIndex]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(index + 1);
      if (e.key === "ArrowLeft") go(index - 1);
    };
    el.addEventListener("keydown", key);
    return () => el.removeEventListener("keydown", key);
  }, [go, index]);

  if (n === 0) {
    return (
      <div className="w-full flex items-center justify-center bg-[#f3f2ef] text-sm text-[#666]" style={{ aspectRatio: aspect }}>
        No slides were stored for this post.
      </div>
    );
  }

  const width = box.current?.clientWidth || 1;
  const arrow = `absolute top-1/2 -translate-y-1/2 z-10 flex items-center justify-center rounded-full cursor-pointer transition-opacity ${arrowClass}`;

  return (
    <div
      ref={box}
      tabIndex={0}
      aria-roledescription="carousel"
      className="relative w-full overflow-hidden bg-[#f3f2ef] select-none outline-none group/carousel touch-pan-y"
      style={{ aspectRatio: aspect }}
      onDoubleClick={onDoubleTap}
      onPointerDown={(e) => {
        if (e.pointerType === "mouse") return;
        start.current = { x: e.clientX, y: e.clientY };
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const dx = e.clientX - start.current.x;
        if (Math.abs(dx) > Math.abs(e.clientY - start.current.y)) setDrag(dx);
      }}
      onPointerUp={() => {
        if (start.current && Math.abs(drag) > width * 0.18) go(index + (drag < 0 ? 1 : -1));
        start.current = null;
        setDrag(0);
      }}
      onPointerCancel={() => {
        start.current = null;
        setDrag(0);
      }}
    >
      <div
        className="flex h-full"
        style={{
          transform: `translateX(calc(${-index * 100}% + ${drag}px))`,
          transition: drag ? "none" : "transform 380ms cubic-bezier(0.25, 0.8, 0.25, 1)",
        }}
      >
        {images.map((src, i) => (
          <div key={src} className="relative w-full h-full shrink-0">
            {!loaded[i] && !broken[i] && <div className="absolute inset-0 skeleton" />}
            {broken[i] ? (
              <div className="w-full h-full flex items-center justify-center text-sm text-[#666]">Image unavailable</div>
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt={`Slide ${i + 1} of ${n}`}
                draggable={false}
                loading={Math.abs(i - index) <= 1 ? "eager" : "lazy"}
                onLoad={() => setLoaded((l) => ({ ...l, [i]: true }))}
                onError={() => setBroken((b) => ({ ...b, [i]: true }))}
                className={`w-full h-full object-cover transition-opacity duration-300 ${loaded[i] ? "opacity-100" : "opacity-0"}`}
              />
            )}
          </div>
        ))}
      </div>

      {n > 1 && index > 0 && (
        <button type="button" aria-label="Previous slide" onClick={() => go(index - 1)} className={`${arrow} left-2.5`}>
          <Chevron dir="left" />
        </button>
      )}
      {n > 1 && index < n - 1 && (
        <button type="button" aria-label="Next slide" onClick={() => go(index + 1)} className={`${arrow} right-2.5`}>
          <Chevron dir="right" />
        </button>
      )}
      {children}
    </div>
  );
}

export function Chevron({ dir, className = "w-4 h-4" }: { dir: "left" | "right"; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
      <path d={dir === "left" ? "M15 18l-6-6 6-6" : "M9 6l6 6-6 6"} />
    </svg>
  );
}

// ---- phone frame -------------------------------------------------------------------------

export function PhoneFrame({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return (
    <div className="relative w-[390px] max-w-full rounded-[54px] bg-[#1b1b1d] p-[11px] shadow-[0_30px_80px_-20px_rgba(22,19,15,0.45),inset_0_0_0_2px_#3a3a3d]">
      <div className={`relative h-[760px] rounded-[44px] overflow-hidden flex flex-col ${dark ? "bg-black text-white" : "bg-white text-black"}`}>
        {/* status bar + dynamic island */}
        <div className="relative h-[50px] shrink-0 flex items-center justify-between px-8 pt-1 text-[15px] font-semibold" style={{ fontFamily: "var(--font-platform)" }}>
          <span>9:41</span>
          <span className="absolute left-1/2 top-[11px] -translate-x-1/2 w-[118px] h-[33px] rounded-full bg-black" />
          <span className="flex items-center gap-1.5">
            <svg width="18" height="12" viewBox="0 0 18 12" fill="currentColor" aria-hidden>
              <rect x="0" y="8" width="3" height="4" rx="1" />
              <rect x="5" y="5.5" width="3" height="6.5" rx="1" />
              <rect x="10" y="3" width="3" height="9" rx="1" />
              <rect x="15" y="0" width="3" height="12" rx="1" />
            </svg>
            <svg width="16" height="12" viewBox="0 0 16 12" fill="currentColor" aria-hidden>
              <path d="M8 2.4c2.3 0 4.4.9 6 2.4l1.2-1.3A10.3 10.3 0 008 .6 10.3 10.3 0 00.8 3.5L2 4.8a8.5 8.5 0 016-2.4zm0 3.6c1.3 0 2.5.5 3.4 1.3l1.2-1.3A6.7 6.7 0 008 4.2a6.7 6.7 0 00-4.6 1.8l1.2 1.3A5 5 0 018 6zm0 3.5l2.1-2.2A3 3 0 008 6.5a3 3 0 00-2.1.8L8 9.5z" />
            </svg>
            <span className="relative w-[26px] h-[12.5px] rounded-[4px] border border-current/40 p-[1.5px]">
              <span className="block h-full w-[80%] rounded-[2px] bg-current" />
            </span>
          </span>
        </div>
        <div className="flex-1 min-h-0 flex flex-col">{children}</div>
        <div className="absolute bottom-[7px] left-1/2 -translate-x-1/2 w-[134px] h-[5px] rounded-full bg-current opacity-90" />
      </div>
    </div>
  );
}
