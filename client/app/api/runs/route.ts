import { dbConfigured, dbListRuns } from "@/lib/db";

// Runs straight from Postgres (the only source the UI reads). 503 when DATABASE_URL is not set.
export async function GET() {
  if (!dbConfigured()) {
    return Response.json({ error: "database not configured" }, { status: 503 });
  }
  try {
    return Response.json(await dbListRuns());
  } catch (err) {
    console.error("[api/runs] query failed:", err);
    return Response.json({ error: "database query failed" }, { status: 502 });
  }
}
