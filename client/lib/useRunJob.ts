"use client";

// Tracks the one active generation run: starts it, polls the database until it finishes, and
// survives refreshes and tab switches.
//
// Why not a plain setInterval: browsers throttle timers in background tabs (to once a minute
// after a few minutes), and a stalled request used to leave the UI on "Generating" even though
// the run was already done in Postgres. Here every poll has a timeout, failures back off and
// retry, and the run is re-checked the moment the tab becomes visible, regains focus, or comes
// back online. The job id lives in localStorage, so a refresh resumes where it left off.
import { useCallback, useEffect, useRef, useState } from "react";
import { HttpError, cancelRun, createRun, getRun, RunJobResponse, RunResult } from "./api";

const STORAGE_KEY = "anchor.activeRun";
const POLL_MS = 2_000;
const MAX_BACKOFF_MS = 15_000;
/** A run the database doesn't know (deleted) is dropped on the first 404 when resumed; a run we
 * just started gets a few polls of grace in case its row is still being written. */
const NEW_RUN_404_GRACE = 3;
/** A remembered run older than this is not resumed after a refresh. */
const MAX_RESUME_AGE_MS = 6 * 60 * 60 * 1000;

export interface StartPayload {
  url: string;
  mode: "fast" | "refine";
  industry?: string | null;
  posts?: number;
}

interface Stored {
  id: string;
  url: string;
  mode: "fast" | "refine";
  startedAt: number;
}

export type JobPhase = "idle" | "starting" | "active" | "done" | "failed";

export interface RunJobState {
  phase: JobPhase;
  jobId: string | null;
  url: string | null;
  mode: "fast" | "refine";
  job: RunJobResponse | null;
  startedAt: number | null;
  error: string | null;
  /** Consecutive failed polls; >0 means we are retrying a flaky connection. */
  failures: number;
}

const idle: RunJobState = {
  phase: "idle",
  jobId: null,
  url: null,
  mode: "fast",
  job: null,
  startedAt: null,
  error: null,
  failures: 0,
};

function readStored(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const stored = raw ? (JSON.parse(raw) as Stored) : null;
    if (stored && (!stored.id || Date.now() - (stored.startedAt || 0) > MAX_RESUME_AGE_MS)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return stored;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function useRunJob(onDone?: (result: RunResult) => void) {
  const [state, setState] = useState<RunJobState>(idle);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef(false);
  const activeId = useRef<string | null>(null);
  const failures = useRef(0);
  const notFound = useRef(0);
  const notFoundLimit = useRef(1);

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const poll = useCallback(async () => {
    const id = activeId.current;
    if (!id || inFlight.current) return;
    inFlight.current = true;
    clearTimer();
    let next = POLL_MS;
    try {
      const job = await getRun(id);
      if (activeId.current !== id) return; // superseded by another run
      failures.current = 0;
      notFound.current = 0;
      if (job.status === "cancelled") {
        // Stopped (here or in another tab): nothing to follow any more.
        activeId.current = null;
        localStorage.removeItem(STORAGE_KEY);
        setState(idle);
        return;
      }
      if (job.status === "done" || job.status === "failed") {
        activeId.current = null;
        localStorage.removeItem(STORAGE_KEY);
        setState((s) => ({
          ...s,
          job,
          failures: 0,
          phase: job.status === "done" ? "done" : "failed",
          error:
            job.status === "failed" ? job.error || "Something went wrong." : null,
        }));
        if (job.status === "done" && job.result)
          onDoneRef.current?.(job.result);
        return;
      }
      setState((s) => ({
        ...s,
        job,
        failures: 0,
        phase: "active",
        startedAt: job.created_at ? Date.parse(job.created_at) : s.startedAt,
      }));
    } catch (err) {
      if (activeId.current !== id) return;
      // The run no longer exists (deleted, or never recorded): stop following it instead of
      // showing progress for work nobody is doing.
      if (err instanceof HttpError && err.status === 404 && ++notFound.current >= notFoundLimit.current) {
        activeId.current = null;
        localStorage.removeItem(STORAGE_KEY);
        setState(idle);
        return;
      }
      // A timeout, a blip, or the server restarting: retry with backoff.
      failures.current += 1;
      next = Math.min(
        POLL_MS * 2 ** Math.min(failures.current, 3),
        MAX_BACKOFF_MS,
      );
      setState((s) => ({ ...s, failures: failures.current }));
    } finally {
      inFlight.current = false;
      if (activeId.current === id) timer.current = setTimeout(poll, next);
    }
  }, []);

  const track = useCallback(
    (stored: Stored, fresh = false) => {
      activeId.current = stored.id;
      failures.current = 0;
      notFound.current = 0;
      notFoundLimit.current = fresh ? NEW_RUN_404_GRACE : 1;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
      setState({
        ...idle,
        phase: "active",
        jobId: stored.id,
        url: stored.url,
        mode: stored.mode,
        startedAt: stored.startedAt,
      });
      poll();
    },
    [poll],
  );

  const start = useCallback(
    async (payload: StartPayload) => {
      setState({
        ...idle,
        phase: "starting",
        url: payload.url,
        mode: payload.mode,
        startedAt: Date.now(),
      });
      try {
        const id = await createRun(payload);
        track(
          {
            id,
            url: payload.url,
            mode: payload.mode,
            startedAt: Date.now(),
          },
          true,
        );
      } catch (err) {
        setState((s) => ({
          ...s,
          phase: "failed",
          error:
            err instanceof Error && !(err instanceof TypeError)
              ? err.message
              : "We couldn't start right now. Please check your connection and try again.",
        }));
      }
    },
    [track],
  );

  /** Follow a run that is already in flight (e.g. clicked in the archive). */
  const attach = useCallback(
    (id: string, url: string, mode: "fast" | "refine" = "fast") =>
      track({ id, url, mode, startedAt: Date.now() }),
    [track],
  );

  /** Stop the run in flight. The UI moves on at once; the server stops the work. */
  const cancel = useCallback(async () => {
    const id = activeId.current;
    if (!id) return;
    await cancelRun(id); // throws if the stop could not be recorded; the run keeps showing
    if (activeId.current !== id) return;
    activeId.current = null;
    clearTimer();
    localStorage.removeItem(STORAGE_KEY);
    setState(idle);
  }, []);

  const reset = useCallback(() => {
    activeId.current = null;
    clearTimer();
    localStorage.removeItem(STORAGE_KEY);
    setState(idle);
  }, []);

  // Resume after a refresh, and re-check immediately whenever the user comes back.
  useEffect(() => {
    const stored = readStored();
    if (stored) track(stored);
    const wake = () => {
      if (document.visibilityState === "visible" && activeId.current) poll();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    window.addEventListener("online", wake);
    return () => {
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
      window.removeEventListener("online", wake);
      clearTimer();
    };
  }, [poll, track]);

  return { state, start, attach, reset, cancel };
}
