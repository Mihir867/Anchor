"use client";

import React, { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";

export function Navbar() {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let isMounted = true;
    checkHealth().then((ok) => {
      if (isMounted) setIsOnline(ok);
    });
    const interval = setInterval(() => {
      checkHealth().then((ok) => {
        if (isMounted) setIsOnline(ok);
      });
    }, 10000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-[#212c3d]/80 bg-[#080d16]/85 backdrop-blur-md font-sans">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        {/* Brand Logo & Name */}
        <a
          href="/"
          className="flex items-center gap-2.5 group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded-lg p-1"
        >
          <div className="w-8 h-8 rounded-lg bg-[#0c121d] border border-[#212c3d] flex items-center justify-center shadow-inner group-hover:border-amber-500/50 transition-colors duration-200">
            {/* Radiant 8-pointed celestial star SVG */}
            <svg
              className="w-4 h-4 text-[#f59e0b] fill-current transform group-hover:scale-105 transition-transform duration-200"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
            </svg>
          </div>
          <span className="text-[#f8fafc] font-semibold text-base sm:text-lg tracking-tight">
            Anchor
          </span>
          <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-[#182232] text-[#909dad] border border-[#212c3d]">
            v2.0
          </span>
        </a>

        {/* Center Nav Links */}
        <nav
          className="hidden md:flex items-center gap-7 text-sm font-medium text-[#909dad]"
          aria-label="Main Navigation"
        >
          <a
            href="#generator"
            className="hover:text-[#f8fafc] transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded px-1"
          >
            Create Run
          </a>
          <a
            href="#recent-runs"
            className="hover:text-[#f8fafc] transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded px-1"
          >
            Run Archive
          </a>
          <a
            href="#features"
            className="hover:text-[#f8fafc] transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded px-1"
          >
            How it works
          </a>
          <a
            href="#harness2"
            className="hover:text-[#f8fafc] transition-colors duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded px-1"
          >
            Harness²
          </a>
        </nav>

        {/* Right Status Pill & CTA */}
        <div className="flex items-center gap-3">
          <div className="inline-flex items-center gap-2 text-xs font-mono text-[#909dad] bg-[#0c121d] px-2.5 py-1 rounded-full border border-[#212c3d]">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isOnline === true
                  ? "bg-emerald-400 animate-pulse"
                  : isOnline === false
                  ? "bg-rose-500"
                  : "bg-amber-400"
              }`}
            />
            <span>
              {isOnline === true
                ? "API :8000 Online"
                : isOnline === false
                ? "API Offline"
                : "Checking API..."}
            </span>
          </div>

          <a
            href="#generator"
            className="inline-flex items-center justify-center px-4 py-1.5 rounded-full text-xs font-semibold bg-[#f8fafc] text-[#080d16] hover:bg-[#e2e8f0] active:scale-[0.98] transition-all duration-150 shadow-sm cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            Launch Run
          </a>
        </div>
      </div>
    </header>
  );
}
