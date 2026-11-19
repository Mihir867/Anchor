"use client";

import React, { useEffect, useState } from "react";
import { listRuns, RunItem, getRun, RunResult } from "@/lib/api";

interface RecentRunsSectionProps {
  onSelectRun: (res: RunResult) => void;
  selectedTaskId?: string;
}

export function RecentRunsSection({
  onSelectRun,
  selectedTaskId,
}: RecentRunsSectionProps) {
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const fetchRuns = async () => {
    setIsLoading(true);
    const list = await listRuns();
    setRuns(list);
    setIsLoading(false);
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleRunClick = async (item: RunItem) => {
    setLoadingId(item.id);
    try {
      const data = await getRun(item.id);
      if (data.result) {
        onSelectRun(data.result);
      }
    } catch (err) {
      console.error("Failed to load run:", err);
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <section id="recent-runs" className="w-full max-w-6xl mx-auto px-4 sm:px-6 py-12 border-t border-[#212c3d]/60 font-sans">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-xl font-bold text-[#f8fafc] tracking-tight">
            Generated Run Archive
          </h3>
          <p className="text-xs text-[#909dad] mt-1">
            Explore past website crawls and verified post generations stored on the backend.
          </p>
        </div>

        <button
          type="button"
          onClick={fetchRuns}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#182232] hover:bg-[#212c3d] text-[#909dad] hover:text-[#f8fafc] border border-[#212c3d] transition-colors cursor-pointer"
        >
          <svg
            className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>Refresh</span>
        </button>
      </div>

      {runs.length === 0 ? (
        <div className="p-8 rounded-2xl bg-[#0c121d] border border-[#212c3d] text-center text-xs text-[#909dad]">
          {isLoading ? "Loading run archive..." : "No runs found yet. Generate your first brand above!"}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          {runs.map((r) => {
            const isSelected = selectedTaskId === r.task_id || selectedTaskId === r.id;
            const isThisLoading = loadingId === r.id;

            return (
              <div
                key={r.id}
                onClick={() => handleRunClick(r)}
                className={`p-4 rounded-xl border transition-all duration-150 cursor-pointer flex flex-col justify-between shadow-sm group ${
                  isSelected
                    ? "bg-[#182232] border-amber-400/80 shadow-amber-500/5 ring-1 ring-amber-400/30"
                    : "bg-[#0c121d] border-[#212c3d] hover:border-[#38495f] hover:bg-[#111927]"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="font-bold text-sm text-[#f8fafc] group-hover:text-amber-400 transition-colors">
                      {r.brand || r.task_id.split("-")[0]}
                    </span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {r.verified_posts} Verified
                    </span>
                  </div>

                  <p className="text-xs text-[#909dad] font-mono truncate">
                    {r.task_id}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-[#212c3d]/60 flex items-center justify-between text-[11px] text-[#909dad]">
                  <span className="capitalize">{r.industry || "general"}</span>
                  <span className="text-slate-300 group-hover:text-[#f8fafc] font-medium flex items-center gap-1">
                    {isThisLoading ? (
                      "Loading..."
                    ) : (
                      <>
                        <span>View Posts</span>
                        <span>→</span>
                      </>
                    )}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
