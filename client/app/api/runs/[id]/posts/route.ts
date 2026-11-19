import type { NextRequest } from "next/server";
import { dbConfigured, dbGetPostsMarkdown } from "@/lib/db";

// The run's posts.md as stored in Postgres (download link in the result view).
export async function GET(_req: NextRequest, ctx: RouteContext<"/api/runs/[id]/posts">) {
  if (!dbConfigured()) {
    return new Response("database not configured", { status: 503 });
  }
  const { id } = await ctx.params;
  const md = await dbGetPostsMarkdown(id).catch(() => null);
  if (md === null) return new Response("posts.md not found", { status: 404 });
  return new Response(md, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": `inline; filename="${id}-posts.md"`,
    },
  });
}
