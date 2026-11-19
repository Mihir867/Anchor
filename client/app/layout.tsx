import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
  weight: ["300", "400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Anchor — Evidence-Grounded Brand Intelligence & Social Engine",
  description: "Autonomous, verified brand intelligence, LinkedIn posts, and visual carousels with zero hallucinations.",
};

export default function RootLayout({
  children,
}: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} dark h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans bg-background text-foreground selection:bg-amber-500/20 selection:text-amber-200">
        {children}
      </body>
    </html>
  );
}
