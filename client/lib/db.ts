// Server-only: Postgres access for route handlers. Never import this from a "use client" file —
// it reads DATABASE_URL, which must not reach the browser.
//
// The engine (ai-engine/anchor/storage.py) owns the schema and writes these tables; the client
// only reads them. Keep the column names here in sync with storage.SCHEMA.
import { Pool } from "pg";
import type { PostCard, RunItem, RunJobResponse } from "./api";
import { PUBLIC_ERROR } from "./engine";

// Engine stage names describe the pipeline; the browser gets neutral step ids instead.
const STAGE_IDS: Record<string, string> = {
  crawling: "discover",
  researching: "explore",
  mining: "curate",
  writing: "write",
  rendering: "design",
  saving: "polish",
};
function publicStage(stage: string | null, status: string): string {
  const s = stage ?? status;
  return STAGE_IDS[s] ?? (["queued", "done", "failed", "cancelled"].includes(s) ? s : "discover");
}

// Only these live-progress fields reach the browser; the rest describe how the engine works.
function publicProgress(p: RunJobResponse["progress"] | null): RunJobResponse["progress"] | undefined {
  if (!p) return undefined;
  const { brand, post, target, verified, headline } = p;
  return { brand, post, target, verified, headline };
}

declare global {
  // Reuse one pool across hot reloads in dev.
  var __anchorPgPool: Pool | undefined;
}

export function dbConfigured(): boolean {
  return Boolean(process.env.DATABASE_URL);
}

function pool(): Pool {
  if (!globalThis.__anchorPgPool) {
    const url = process.env.DATABASE_URL!;
    const local = /@(localhost|127\.0\.0\.1)[:/]/.test(url);
    globalThis.__anchorPgPool = new Pool({
      connectionString: url,
      max: 5,
      idleTimeoutMillis: 30_000,
      // Never let a dropped connection (Neon/Supabase close idle sockets) hang a request: the
      // UI polls these routes, and a stalled pool would freeze it on "generating".
      connectionTimeoutMillis: 8_000,
      query_timeout: 10_000,
      statement_timeout: 10_000,
      keepAlive: true,
      // Hosted Postgres (Neon, Supabase, RDS) requires TLS; local dev usually has none.
      // Respect an explicit sslmode in the URL; otherwise use TLS for non-local hosts.
      ssl: /sslmode=/.test(url) || local ? undefined : { rejectUnauthorized: false },
    });
    // An idle client erroring (server closed it) must not crash the process; the pool replaces it.
    globalThis.__anchorPgPool.on("error", (err) => console.error("[db] idle client error:", err.message));
  }
  return globalThis.__anchorPgPool;
}

interface RunRow {
  id: string;
  task_id: string | null;
  url: string;
  brand: string | null;
  industry: string | null;
  mode: string | null;
  status: RunItem["status"];
  stage: string | null;
  error: string | null;
  note: string | null;
  verified_posts: number;
  request: RunJobResponse["request"] | null;
  logo_url: string | null;
  progress: RunJobResponse["progress"] | null;
  brand_color: string | null;
  brand_domain: string | null;
  created_at: Date;
  finished_at: Date | null;
}

interface PostRow {
  card_id: string;
  status: PostCard["status"];
  voice: string | null;
  linkedin: string | null;
  instagram_caption: string | null;
  hashtags: string[];
  poster_headline: string | null;
  poster_kicker: string | null;
  poster_stat: string | null;
  slides: { title: string; bullets: string[] }[];
  fact: PostCard["fact"];
  sources: PostCard["sources"];
  slide_urls: string[];
  pdf_url: string | null;
}

export async function dbListRuns(limit = 50): Promise<RunItem[]> {
  const { rows } = await pool().query<RunRow>(
    `SELECT id, task_id, url, brand, industry, mode, status, stage, verified_posts, created_at
       FROM runs ORDER BY created_at DESC LIMIT $1`,
    [limit],
  );
  return rows.map((r) => ({
    id: r.id,
    task_id: r.task_id ?? r.id,
    status: r.status,
    brand: r.brand ?? r.url,
    url: r.url,
    industry: r.industry ?? undefined,
    stage: r.stage ? publicStage(r.stage, r.status) : undefined,
    verified_posts: r.verified_posts,
    created_at: r.created_at.toISOString(),
    mode: r.mode ?? "fast",
  }));
}

export async function dbGetRun(id: string): Promise<RunJobResponse | null> {
  const { rows } = await pool().query<RunRow>(
    `SELECT id, task_id, url, brand, industry, mode, status, stage, error, note, verified_posts,
            request, logo_url, progress, brand_kit->>'primary_color' AS brand_color,
            brand_kit->>'domain' AS brand_domain, created_at, finished_at
       FROM runs WHERE id = $1 OR task_id = $1 LIMIT 1`,
    [id],
  );
  const run = rows[0];
  if (!run) return null;
  const base: RunJobResponse = {
    job_id: run.id,
    status: run.status,
    stage: publicStage(run.stage, run.status),
    // The raw error (stack traces, tool names) stays in the database and server logs.
    error: run.status === "failed" ? PUBLIC_ERROR : undefined,
    request: run.request ? { url: run.request.url, mode: run.request.mode, posts: run.request.posts } : undefined,
    progress: publicProgress(run.progress),
    created_at: run.created_at.toISOString(),
    finished_at: run.finished_at?.toISOString(),
  };
  if (run.status !== "done") return base;

  const posts = await pool().query<PostRow>(
    `SELECT card_id, status, voice, linkedin, instagram_caption, hashtags, poster_headline,
            poster_kicker, poster_stat, slides, fact, sources, slide_urls, pdf_url
       FROM posts WHERE run_id = $1 ORDER BY position`,
    [run.id],
  );
  const taskId = run.task_id ?? run.id;
  const cards: PostCard[] = posts.rows.map((p) => ({
    id: p.card_id,
    status: p.status,
    fact: {
      headline: p.fact?.headline ?? "",
      category: p.fact?.category,
      quote: p.fact?.quote ?? "",
      metrics: p.fact?.metrics ?? [],
      named_entities: p.fact?.named_entities ?? [],
      why_it_matters: p.fact?.why_it_matters,
    },
    post: p.linkedin
      ? {
          voice: p.voice ?? undefined,
          linkedin: p.linkedin,
          instagram_caption: p.instagram_caption ?? "",
          hashtags: p.hashtags,
          poster_headline: p.poster_headline ?? "",
          poster_kicker: p.poster_kicker ?? "",
          poster_stat: p.poster_stat ?? "",
          slides: p.slides,
        }
      : null,
    sources: (p.sources ?? []).map((src) => ({ url: src.url, title: src.title, date: src.date })),
    slide_urls: p.slide_urls,
    pdf_url: p.pdf_url ?? undefined,
  }));
  return {
    ...base,
    result: {
      task_id: taskId,
      brand: run.brand ?? run.url,
      industry: run.industry ?? "general",
      mode: run.mode ?? "fast",
      verified_posts: run.verified_posts,
      note: run.note ?? undefined,
      logo_url: run.logo_url ?? undefined,
      brand_color: run.brand_color ?? undefined,
      domain: run.brand_domain ?? undefined,
      deck: { task_id: taskId, brand: run.brand ?? "", industry: run.industry ?? "", cards },
      posts_md_url: `/api/runs/${encodeURIComponent(run.id)}/posts`,
    },
  };
}

/** Mark an in-flight run cancelled (fallback when the engine can't be reached). */
export async function dbCancelRun(id: string): Promise<void> {
  await pool().query(
    `UPDATE runs SET status = 'cancelled', stage = 'cancelled', error = NULL, updated_at = now(), finished_at = now()
      WHERE (id = $1 OR task_id = $1) AND status IN ('queued', 'running')`,
    [id],
  );
}

export async function dbGetPostsMarkdown(id: string): Promise<string | null> {
  const { rows } = await pool().query<{ posts_md: string | null }>(
    "SELECT posts_md FROM runs WHERE id = $1 OR task_id = $1 LIMIT 1",
    [id],
  );
  return rows[0]?.posts_md ?? null;
}
