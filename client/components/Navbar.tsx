"use client";

import React from "react";

interface NavbarProps {
  /** Short label for a run in flight ("Writing · 64%"); shows a pill that jumps to it. */
  activeLabel?: string | null;
}

export function Navbar({ activeLabel }: NavbarProps) {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-line/70 bg-canvas/75 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        <a href="#" className="flex items-center gap-2.5 rounded-lg">
          <span className="w-8 h-8 rounded-xl bg-ink flex items-center justify-center shadow-card">
            <svg className="w-4 h-4 text-brand" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" />
            </svg>
          </span>
          <span className="font-semibold text-[17px] tracking-tight">Anchor</span>
        </a>

        <nav className="hidden md:flex items-center gap-7 text-[14px] font-medium text-muted" aria-label="Main">
          <a href="#generator" className="hover:text-ink transition-colors">Create</a>
          <a href="#recent-runs" className="hover:text-ink transition-colors">Library</a>
          <a href="#features" className="hover:text-ink transition-colors">Why Anchor</a>
        </nav>

        <div className="flex items-center gap-2.5">
          {activeLabel && (
            <a
              href="#live-run"
              className="inline-flex items-center gap-2 h-8 pl-2.5 pr-3 rounded-full bg-brand-tint border border-amber-200 text-[12px] font-medium text-brand-deep animate-fade-up"
            >
              <span className="relative flex w-2 h-2">
                <span className="absolute inset-0 rounded-full bg-brand animate-ping opacity-60" />
                <span className="relative w-2 h-2 rounded-full bg-brand" />
              </span>
              <span className="tabular-nums">{activeLabel}</span>
            </a>
          )}
          <a
            href="#generator"
            className="inline-flex items-center h-8 px-4 rounded-full text-[13px] font-semibold bg-ink text-white hover:bg-ink-soft transition-colors"
          >
            Create posts
          </a>
        </div>
      </div>
    </header>
  );
}
