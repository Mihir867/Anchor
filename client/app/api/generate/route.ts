import { ENGINE_URL, PUBLIC_ERROR } from "@/lib/engine";

const MODES = new Set(["fast", "refine"]);

// Starts a run. Only whitelisted fields are forwarded, and only the job id comes back.
export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid request." }, { status: 400 });
  }
  const url = typeof body.url === "string" ? body.url.trim() : "";
  if (!url || url.length > 2048) return Response.json({ error: "Please enter a valid website." }, { status: 400 });
  const payload = {
    url,
    mode: MODES.has(body.mode as string) ? body.mode : "fast",
    industry: typeof body.industry === "string" && body.industry ? body.industry : null,
    posts: Math.min(6, Math.max(1, Number(body.posts) || 3)),
  };

  try {
    const res = await fetch(`${ENGINE_URL}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok) {
      console.error("[api/generate] engine responded", res.status, await res.text().catch(() => ""));
      return Response.json({ error: PUBLIC_ERROR }, { status: 502 });
    }
    const { job_id } = (await res.json()) as { job_id: string };
    return Response.json({ job_id });
  } catch (err) {
    console.error("[api/generate] engine unreachable:", err);
    return Response.json({ error: "We couldn't start right now. Please try again in a moment." }, { status: 503 });
  }
}
