"use client";

import React, { useEffect, useState } from "react";
import { Spinner } from "./ui/icons";
import { buttonClass } from "./ui/button";

interface NavbarProps {
  /** Short label for a run in flight ("Writing"); links to the live run. */
  activeLabel?: string | null;
}

export function Navbar({ activeLabel }: NavbarProps) {
  // Hairline under the bar only once the page has scrolled.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 w-full bg-bg transition-colors duration-[160ms] ease-out border-b ${
        scrolled ? "border-border" : "border-transparent"
      }`}
    >
      <div className="max-w-[1120px] mx-auto px-5 sm:px-8 h-14 flex items-center justify-between gap-4">
        <a href="#" className="text-[15px] font-semibold tracking-[-0.01em] text-fg rounded-md">
          Anchor
        </a>

        <nav className="hidden md:flex items-center gap-6 text-sm font-medium text-fg-2" aria-label="Main">
          <a href="#generator" className="hover:text-fg transition-colors duration-[120ms] rounded-md">
            Create
          </a>
          <a href="#recent-runs" className="hover:text-fg transition-colors duration-[120ms] rounded-md">
            Library
          </a>
          <a href="#how-it-works" className="hover:text-fg transition-colors duration-[120ms] rounded-md">
            How it works
          </a>
        </nav>

        <div className="flex items-center gap-3">
          {activeLabel && (
            <a
              href="#live-run"
              className="inline-flex items-center gap-2 h-8 px-2 rounded-md text-[13px] font-medium text-fg-2 hover:bg-bg-subtle hover:text-fg transition-colors duration-[120ms] animate-fade"
            >
              <Spinner className="w-3.5 h-3.5 text-fg-3" />
              {activeLabel}
            </a>
          )}
          <a href="#generator" className={buttonClass("primary", "md")}>
            Create posts
          </a>
        </div>
      </div>
    </header>
  );
}
