"use client";

import { motion } from "framer-motion";
import type { JobStatus, TourStatus } from "@/lib/types";

const STATUS_COLOR: Record<string, string> = {
  delivered: "var(--green)",
  ready: "var(--tint)",
  rendering: "var(--amber)",
  compositing: "var(--amber)",
  uploading: "var(--amber)",
  screenplay: "var(--amber)",
  queued: "var(--text-3)",
  intake: "var(--purple)",
  draft: "var(--text-3)",
  failed: "var(--red)",
  done: "var(--green)",
  accepted: "var(--green)",
  generating: "var(--amber)",
  qa: "var(--tint)",
  rejected: "var(--red)",
};

export function StatusBadge({ status }: { status: TourStatus | JobStatus | string }) {
  const color = STATUS_COLOR[status] ?? "var(--text-3)";
  return (
    <span
      className="hairline inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium"
      style={{ color }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: color }}
      />
      {status}
    </span>
  );
}

export function MetricCard({
  label,
  value,
  sub,
  accent = "var(--tint)",
  index = 0,
}: {
  label: string;
  value: string;
  sub: string;
  accent?: string;
  index?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="glass glass-hover p-4"
    >
      <div className="label-caps">{label}</div>
      <div
        className="mt-2 text-[26px] font-bold leading-none tracking-tight"
        style={{ color: accent }}
      >
        {value}
      </div>
      <div className="mt-1.5 text-[12px] text-ink-3">{sub}</div>
    </motion.div>
  );
}

export function Progress({ pct }: { pct: number }) {
  return (
    <div className="progress-track h-1.5 w-full">
      <div className="progress-fill h-full" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="glass flex flex-col items-center justify-center py-16 text-center">
      <div className="text-[14px] font-medium text-ink-2">{title}</div>
      <div className="mt-1 text-[12px] text-ink-3">{hint}</div>
    </div>
  );
}
