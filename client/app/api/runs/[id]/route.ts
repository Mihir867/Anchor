import type { NextRequest } from "next/server";
import { dbConfigured, dbGetRun } from "@/lib/db";

export async function GET(_req: NextRequest, ctx: RouteContext<"/api/runs/[id]">) {
  if (!dbConfigured()) {
    return Response.json({ error: "database not configured" }, { status: 503 });
  }
  const { id } = await ctx.params;
  try {
    const run = await dbGetRun(id);
    return run
      ? Response.json(run)
      : Response.json({ error: `unknown run: ${id}` }, { status: 404 });
  } catch (err) {
    console.error(`[api/runs/${id}] query failed:`, err);
    return Response.json({ error: "database query failed" }, { status: 502 });
  }
}
