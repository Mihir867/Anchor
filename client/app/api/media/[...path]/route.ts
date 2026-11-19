import type { NextRequest } from "next/server";
import { ENGINE_URL } from "@/lib/engine";

// Fallback for slide images not on the CDN: streams them from the engine without exposing it.
export async function GET(_req: NextRequest, ctx: RouteContext<"/api/media/[...path]">) {
  const { path } = await ctx.params;
  if (!path?.length || path.some((p) => p === ".." || p.includes("\\")) || !/\.(png|jpe?g|webp|pdf)$/i.test(path[path.length - 1])) {
    return new Response("Not found", { status: 404 });
  }
  try {
    const res = await fetch(`${ENGINE_URL}/static/runs/${path.map(encodeURIComponent).join("/")}`, {
      signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok || !res.body) return new Response("Not found", { status: 404 });
    return new Response(res.body, {
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/octet-stream",
        "Cache-Control": "public, max-age=86400, immutable",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
