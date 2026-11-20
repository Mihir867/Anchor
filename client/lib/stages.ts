import type { RunProgress } from "./api";

// Stage ids are the neutral step ids from lib/db.ts (publicStage), in order. Titles are user-facing and deliberately
// describe outcomes, not how the work is done. `typical` (seconds) only eases the progress bar.
export const STAGES = [
  { id: "discover", title: "Getting to know your brand", short: "Discovering", from: 2, to: 22, typical: 25 },
  { id: "explore", title: "Finding what's worth sharing", short: "Exploring", from: 22, to: 36, typical: 20 },
  { id: "curate", title: "Picking your strongest stories", short: "Curating", from: 36, to: 52, typical: 25 },
  { id: "write", title: "Writing your posts", short: "Writing", from: 52, to: 86, typical: 60 },
  { id: "design", title: "Designing your visuals", short: "Designing", from: 86, to: 95, typical: 15 },
  { id: "polish", title: "Adding the finishing touches", short: "Polishing", from: 95, to: 99, typical: 10 },
] as const;

export type StageId = (typeof STAGES)[number]["id"];

export function stageIndex(stage?: string | null): number {
  if (!stage || stage === "queued") return -1;
  const i = STAGES.findIndex((s) => s.id === stage);
  if (i >= 0) return i;
  return stage === "done" ? STAGES.length : 0;
}

/** Percent complete: the stage's band, filled by post count while writing, otherwise eased by
 * time spent in the stage (never reaching the next band until the engine says so). */
export function estimatePercent(stage: string | undefined, p: RunProgress | undefined, secsInStage: number): number {
  const i = stageIndex(stage);
  if (i < 0) return 1;
  if (i >= STAGES.length) return 100;
  const s = STAGES[i];
  let frac = 1 - Math.exp(-secsInStage / s.typical);
  if (s.id === "write" && p?.post && p?.target) {
    const per = 1 / Math.max(p.target, p.post);
    frac = Math.min(1, (p.post - 1) * per + per * (1 - Math.exp(-secsInStage / 20)));
  }
  return Math.round(s.from + (s.to - s.from) * Math.min(frac, 0.97));
}

/** One plain live line for the current stage, from real progress data. */
export function stageDetail(id: StageId, p: RunProgress = {}): string | null {
  switch (id) {
    case "write":
      return p.post ? `Post ${p.post} of ${Math.max(p.target ?? p.post, p.post)}` : null;
    case "design":
      return p.verified ? `Designing ${p.verified} post${p.verified === 1 ? "" : "s"}` : null;
    default:
      return null;
  }
}
