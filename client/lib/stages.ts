import type { RunProgress } from "./api";

// Stage ids match what the engine reports (ai-engine/anchor/progress.py), in order.
export const STAGES = [
  { id: "crawling", title: "Reading the website", short: "Crawl", from: 2, to: 22, typical: 25 },
  { id: "researching", title: "Researching press & news", short: "Research", from: 22, to: 36, typical: 20 },
  { id: "mining", title: "Mining verifiable facts", short: "Facts", from: 36, to: 52, typical: 25 },
  { id: "writing", title: "Writing & fact-checking posts", short: "Write", from: 52, to: 86, typical: 60 },
  { id: "rendering", title: "Designing carousel slides", short: "Design", from: 86, to: 95, typical: 15 },
  { id: "saving", title: "Publishing to your library", short: "Save", from: 95, to: 99, typical: 10 },
] as const;

export type StageId = (typeof STAGES)[number]["id"];

export function stageIndex(stage?: string | null): number {
  if (!stage || stage === "queued") return -1;
  const i = STAGES.findIndex((s) => s.id === stage);
  if (i >= 0) return i;
  return stage === "done" ? STAGES.length : 0; // "running"/"processing" from older engines
}

/** Percent complete: the stage's band, filled by post count while writing, otherwise eased by
 * time spent in the stage (never reaching the next band until the engine says so). */
export function estimatePercent(stage: string | undefined, p: RunProgress | undefined, secsInStage: number): number {
  const i = stageIndex(stage);
  if (i < 0) return 1;
  if (i >= STAGES.length) return 100;
  const s = STAGES[i];
  let frac = 1 - Math.exp(-secsInStage / s.typical);
  if (s.id === "writing" && p?.post && p?.target) {
    const per = 1 / Math.max(p.target, p.post);
    frac = Math.min(1, (p.post - 1) * per + per * (1 - Math.exp(-secsInStage / 20)));
  }
  return Math.round(s.from + (s.to - s.from) * Math.min(frac, 0.97));
}

/** One live line under each stage, built from what the engine has found so far. */
export function stageDetail(id: StageId, p: RunProgress = {}): string | null {
  switch (id) {
    case "crawling":
      return p.brand ? `Found ${p.brand}${p.industry ? ` · ${p.industry} playbook` : ""}` : null;
    case "researching":
      return p.pages ? `${p.pages} pages read · ${p.site_evidence ?? 0} on-site facts` : null;
    case "mining":
      return p.evidence ? `${p.evidence} evidence items${p.news ? ` · ${p.news} from press` : ""}` : null;
    case "writing":
      return p.post
        ? `Post ${p.post} of ${Math.max(p.target ?? p.post, p.post)}${p.verified ? ` · ${p.verified} verified` : ""}`
        : p.facts
          ? `${p.facts} candidate facts`
          : null;
    case "rendering":
      return p.verified != null ? `${p.verified} verified post${p.verified === 1 ? "" : "s"} → 3 slides each` : null;
    case "saving":
      return "Uploading slides";
  }
}

export const TIPS = [
  "Every sentence in a post must trace back to a quote from the brand's site or press coverage.",
  "A second model from a different family reviews each draft. It gets no say in writing it.",
  "Posts that can't be grounded in evidence get dropped, not shipped.",
  "Slides use the colors and fonts pulled from the brand's own stylesheet.",
  "Numbers in a post have to appear verbatim in a cited source, or the post fails verification.",
  "Runs are saved to your library, so you can leave this page and come back later.",
];

export function formatDuration(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const m = Math.floor(s / 60);
  return m ? `${m}:${String(s % 60).padStart(2, "0")}` : `${s}s`;
}
