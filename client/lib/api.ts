/** URL for an asset: CDN URLs pass through, same-origin /api/ routes stay relative, and
 * anything else is streamed through /api/media so the browser never talks to the engine. */
export function assetUrl(u: string): string {
  if (/^https?:\/\//.test(u) || u.startsWith("/api/")) return u;
  return `/api/media/${u.replace(/^\/?(static\/runs\/)?/, "")}`;
}

// The browser only ever talks to this app's /api routes: runs are read from Postgres, and new
// runs are started through /api/generate, which proxies to the engine server-side.
export class HttpError extends Error {
  constructor(public status: number) {
    super(`Request failed (${status})`);
  }
}

async function fromDb<T>(path: string, timeoutMs = 12_000): Promise<T> {
  // A hung request must never stall polling: give up and let the caller retry.
  const res = await fetch(path, {
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new HttpError(res.status);
  return (await res.json()) as T;
}

export type RunStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface RunItem {
  id: string;
  task_id: string;
  status: RunStatus;
  brand?: string;
  url?: string;
  industry?: string;
  /** Live engine stage while running (crawling, researching, mining, writing, rendering, saving). */
  stage?: string;
  verified_posts: number;
  created_at?: string;
  mode?: string;
}

export interface SlideItem {
  title: string;
  bullets: string[];
}

export interface PostCard {
  id: string;
  status: "verified" | "rejected";
  /** Delivered although not every check passed, so a run never ends empty. Review before posting. */
  fallback?: boolean;
  notes?: string[];
  fact: {
    headline: string;
    category?: string;
    quote: string;
    metrics: string[];
    named_entities: string[];
    why_it_matters?: string;
  };
  post?: {
    voice?: string;
    linkedin: string;
    instagram_caption: string;
    hashtags: string[];
    poster_headline: string;
    poster_kicker: string;
    poster_stat?: string;
    slides: SlideItem[];
  } | null;
  sources: Array<{
    url: string;
    title: string;
    date: string | null;
  }>;
  /** Slide image URLs, cover first. */
  slide_urls?: string[];
  pdf_url?: string;
}

export interface RunResult {
  task_id: string;
  brand: string;
  industry: string;
  mode: string;
  verified_posts: number;
  deck?: {
    task_id: string;
    brand: string;
    industry: string;
    cards: PostCard[];
  };
  posts_md_url?: string;
  note?: string;
  logo_url?: string;
  /** Brand primary color and domain from the crawled brand kit. */
  brand_color?: string;
  domain?: string;
}

/** Live details shown while a run is in flight (a public subset; see publicProgress in db.ts). */
export interface RunProgress {
  brand?: string;
  post?: number;
  target?: number;
  verified?: number;
  headline?: string;
}

export interface RunJobResponse {
  status: RunStatus;
  stage?: string;
  job_id: string;
  result?: RunResult;
  error?: string;
  progress?: RunProgress;
  created_at?: string;
  finished_at?: string;
  request?: {
    url: string;
    mode: "fast" | "refine";
    posts?: number;
  };
}

export async function listRuns(): Promise<RunItem[]> {
  try {
    return await fromDb<RunItem[]>("/api/runs");
  } catch (err) {
    console.error("Failed to list runs:", err);
    return [];
  }
}

export async function createRun(payload: {
  url: string;
  mode: "fast" | "refine";
  industry?: string | null;
  posts?: number;
}): Promise<string> {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json().catch(() => ({}))) as { job_id?: string; error?: string };
  if (!res.ok || !data.job_id) throw new Error(data.error || "We couldn't start right now. Please try again.");
  return data.job_id;
}

export async function getRun(jobId: string): Promise<RunJobResponse> {
  return fromDb<RunJobResponse>(`/api/runs/${encodeURIComponent(jobId)}`);
}

/** Stop a run that is queued or in progress. */
export async function cancelRun(jobId: string): Promise<void> {
  const res = await fetch(`/api/runs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error("Couldn't stop right now. Please try again.");
}
