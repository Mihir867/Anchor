import type { NextRequest } from "next/server";
import { dbCancelRun, dbConfigured } from "@/lib/db";
import { ENGINE_URL } from "@/lib/engine";

// Stop a generation. The engine stops the work; if it can't be reached, the row is still marked
// cancelled so the UI never stays stuck on a run nobody is working on.
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/runs/[id]/cancel">) {
  const { id } = await ctx.params;
  if (!/^[\w-]{1,64}$/.test(id)) return Response.json({ error: "Not found" }, { status: 404 });
  let engineOk = false;
  try {
    const res = await fetch(`${ENGINE_URL}/runs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      signal: AbortSignal.timeout(8_000),
    });
    engineOk = res.ok;
    if (!res.ok) console.error(`[api/runs/${id}/cancel] engine responded`, res.status);
  } catch (err) {
    console.error(`[api/runs/${id}/cancel] engine unreachable:`, err);
  }
  if (dbConfigured()) {
    try {
      await dbCancelRun(id);
    } catch (err) {
      console.error(`[api/runs/${id}/cancel] db update failed:`, err);
      if (!engineOk) return Response.json({ error: "Couldn't stop right now. Please try again." }, { status: 502 });
    }
  }
  return Response.json({ status: "cancelled" });
}
