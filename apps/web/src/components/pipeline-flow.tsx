"use client";

import {
  Check,
  Clapperboard,
  FileVideo,
  ScanEye,
  Send,
  Sparkles,
  Upload,
} from "lucide-react";
import type { JobStatus, RenderJob } from "@/lib/types";

const STAGES: { key: string; label: string; icon: typeof Upload; covers: JobStatus[] }[] = [
  { key: "upload", label: "Intake", icon: Upload, covers: ["queued"] },
  { key: "screenplay", label: "Screenplay", icon: Clapperboard, covers: ["screenplay"] },
  { key: "veo", label: "Veo", icon: Sparkles, covers: ["rendering"] },
  { key: "qa", label: "QA Gate", icon: ScanEye, covers: ["rendering"] },
  { key: "composite", label: "Composite", icon: FileVideo, covers: ["compositing"] },
  { key: "delivery", label: "Delivery", icon: Send, covers: ["uploading"] },
];

const ORDER: JobStatus[] = ["queued", "screenplay", "rendering", "compositing", "uploading", "done"];

function stageState(idx: number, job: RenderJob | null): "done" | "active" | "waiting" | "failed" {
  if (!job) return "waiting";
  // The dashboard queue endpoint omits `shots` to keep the payload small —
  // default to [] so this works whether or not shots are present.
  const shots = job.shots ?? [];
  const jobIdx = ORDER.indexOf(job.status === "failed" ? "queued" : job.status);
  const stageOrder = [0, 1, 2, 2, 3, 4]; // map stage idx → ORDER position
  const pos = stageOrder[idx];
  if (job.status === "failed") {
    // mark the stage we died in as failed, prior ones done
    const failPos = 2;
    return pos < failPos ? "done" : pos === failPos ? "failed" : "waiting";
  }
  if (job.status === "done") return "done";
  if (pos < jobIdx) return "done";
  if (pos === jobIdx) {
    // Veo vs QA share a position; alternate by shot state
    if (idx === 3 && shots.some((s) => s.status === "qa")) return "active";
    if (idx === 2 && shots.some((s) => s.status === "qa")) return "done";
    return "active";
  }
  return "waiting";
}

const STATE_STYLE = {
  done: { color: "var(--green)", bg: "rgba(48,209,88,0.12)" },
  active: { color: "var(--tint)", bg: "rgba(10,132,255,0.12)" },
  waiting: { color: "var(--text-3)", bg: "rgba(255,255,255,0.04)" },
  failed: { color: "var(--red)", bg: "rgba(255,69,58,0.12)" },
};

export function PipelineFlow({ job }: { job: RenderJob | null }) {
  return (
    <div className="glass p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <span className="label-caps">Pipeline</span>
        {job && (
          <span className="text-[12px] text-ink-3">
            {job.stage_detail}
            {job.shots_total > 0 && ` — ${job.shots_done}/${job.shots_total} shots`}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {STAGES.map((stage, i) => {
          const state = stageState(i, job);
          const s = STATE_STYLE[state];
          const Icon = state === "done" ? Check : stage.icon;
          return (
            <div key={stage.key} className="flex items-center gap-2">
              <div className="flex min-w-[86px] flex-col items-center gap-1.5">
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-full ${
                    state === "active" ? "pulse-ring" : ""
                  }`}
                  style={{ background: s.bg, color: s.color, opacity: state === "waiting" ? 0.5 : 1 }}
                >
                  <Icon size={15} strokeWidth={1.5} />
                </div>
                <span
                  className="text-[11px] font-medium"
                  style={{ color: s.color, opacity: state === "waiting" ? 0.5 : 1 }}
                >
                  {stage.label}
                </span>
              </div>
              {i < STAGES.length - 1 && (
                <div
                  className="h-px w-6 shrink-0"
                  style={{
                    background: state === "done" ? "var(--green)" : "var(--glass-border)",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
