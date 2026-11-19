export const API_BASE = process.env.NEXT_API_URL || "http://localhost:8000";

/** Absolute URL for an asset: Cloudinary URLs pass through, same-origin /api/ routes stay
 * relative, and engine paths (/static/runs/..., /runs/...) are served by the engine. */
export function assetUrl(u: string): string {
  if (/^https?:\/\//.test(u) || u.startsWith("/api/")) return u;
  return `${API_BASE}${u.startsWith("/") ? "" : "/"}${u}`;
}

// Runs are read only from Postgres via this app's /api/runs routes; the engine is used only to
// start new runs (POST /runs), and it records every job in the database as soon as it is queued.
async function fromDb<T>(path: string, timeoutMs = 12_000): Promise<T> {
  // A hung request must never stall polling: give up and let the caller retry.
  const res = await fetch(path, {
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} failed (${res.status}): ${body}`);
  }
  return (await res.json()) as T;
}

export interface RunItem {
  id: string;
  task_id: string;
  status: "queued" | "running" | "done" | "failed";
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
  fact: {
    headline: string;
    category?: string;
    evidence_ids: string[];
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
    id: string;
    kind: string;
    url: string;
    title: string;
    date: string | null;
    text: string;
  }>;
  attempts?: number;
  problems?: string[];
  notes?: string[];
  poster_path?: string;
  slide_paths?: string[];
  pdf_path?: string;
  /** From Postgres: Cloudinary (or engine-relative) URLs, cover first. */
  slide_urls?: string[];
  pdf_url?: string;
}

export interface RunResult {
  task_id: string;
  brand: string;
  industry: string;
  mode: string;
  verified_posts: number;
  output_dir?: string;
  deck?: {
    task_id: string;
    brand: string;
    industry: string;
    cards: PostCard[];
  };
  posters?: string[];
  carousels?: string[];
  poster_urls?: string[];
  carousel_urls?: string[];
  posts_md_url?: string;
  note?: string;
  logo_url?: string;
  /** Brand primary color and domain from the crawled brand kit. */
  brand_color?: string;
  domain?: string;
}

/** Live details the engine reports while a run is in flight (ai-engine/anchor/progress.py). */
export interface RunProgress {
  url?: string;
  brand?: string;
  industry?: string;
  pages?: number;
  site_evidence?: number;
  evidence?: number;
  news?: number;
  facts?: number;
  post?: number;
  target?: number;
  verified?: number;
  headline?: string;
}

export interface RunJobResponse {
  status: "queued" | "running" | "done" | "failed";
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
    industry?: string;
    posts?: number;
  };
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === "ok";
  } catch {
    return false;
  }
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
  const res = await fetch(`${API_BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to create run (${res.status}): ${errorText}`);
  }
  const data = await res.json();
  return data.job_id;
}

export async function getRun(jobId: string): Promise<RunJobResponse> {
  return fromDb<RunJobResponse>(`/api/runs/${encodeURIComponent(jobId)}`);
}
