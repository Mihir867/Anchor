import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Variable Inter; matched fallback metrics so the font swap does not shift layout.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
  adjustFontFallback: true,
});

export const metadata: Metadata = {
  title: "Anchor — On-brand social posts from your website",
  description: "Paste your website and get on-brand LinkedIn posts and Instagram carousels, backed by real sources.",
};

export default function RootLayout({
  children,
}: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full`}>
      <body className="min-h-full flex flex-col font-sans bg-bg text-fg">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:px-3 focus:h-8 focus:inline-flex focus:items-center focus:rounded-md focus:bg-bg focus:text-sm focus:font-medium focus:shadow-popover"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
