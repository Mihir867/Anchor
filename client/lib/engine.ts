// Server-only: talks to the generation engine. The browser never sees the engine's URL or its
// raw responses; it only calls this app's /api routes.
export const ENGINE_URL = (process.env.ENGINE_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

/** What the browser is shown when anything goes wrong. Details stay in the server logs. */
export const PUBLIC_ERROR = "Something went wrong while creating your posts. Please try again.";
