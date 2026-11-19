export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RunItem {
  id: string;
  task_id: string;
  status: "queued" | "running" | "done" | "failed";
  brand?: string;
  industry?: string;
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
}

export interface RunJobResponse {
  status: "queued" | "running" | "done" | "failed";
  stage?: string;
  job_id: string;
  result?: RunResult;
  error?: string;
  request?: {
    url: string;
    mode: "fast" | "refine";
    industry?: string;
    posts?: number;
  };
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === "ok";
  } catch {
    return false;
  }
}

export async function listRuns(): Promise<RunItem[]> {
  try {
    const res = await fetch(`${API_BASE}/runs`, { cache: "no-store" });
    if (!res.ok) return [];
    return await res.json();
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
  const res = await fetch(`${API_BASE}/runs/${jobId}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to fetch run ${jobId}: ${res.statusText}`);
  }
  return await res.json();
}

export async function getPostsMarkdown(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/runs/${jobId}/posts.md`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch posts.md: ${res.statusText}`);
  }
  return await res.text();
}
