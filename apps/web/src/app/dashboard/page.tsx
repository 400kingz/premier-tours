"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Power } from "lucide-react";
import { api, fmtUsd } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { RenderJob } from "@/lib/types";
import { MetricCard, StatusBadge, EmptyState } from "@/components/ui";
import { PipelineFlow } from "@/components/pipeline-flow";

type QueueRow = Omit<RenderJob, "shots">;

export default function Dashboard() {
  const { tours, metrics, killswitchLocked, toggleKillswitch, refresh } = useApp();
  const [queue, setQueue] = useState<QueueRow[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load = () => api.queue().then(setQueue).catch(() => {});
    load();
    const t = setInterval(() => {
      load();
      refresh().catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const activeJob =
    (queue.find((q) => !["done", "failed"].includes(q.status)) as RenderJob | undefined) ?? null;
  const activeTour = activeJob ? tours.find((t) => t.id === activeJob.tour_id) : null;

  const counts = tours.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div>
        <PipelineFlow job={activeJob} />
        {activeTour && (
          <div className="mt-2 px-1 text-[12px] text-ink-3">
            Rendering <span className="text-ink-2">{activeTour.address}</span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          index={0}
          label="Revenue"
          value={metrics ? fmtUsd(metrics.revenue_cents) : "—"}
          sub={`${metrics?.tours_delivered ?? 0} tours delivered`}
          accent="var(--tint)"
        />
        <MetricCard
          index={1}
          label="In Queue"
          value={String(metrics?.in_queue ?? 0)}
          sub="active render jobs"
          accent="var(--amber)"
        />
        <MetricCard
          index={2}
          label="Veo Spend"
          value={metrics ? fmtUsd(metrics.veo_spend_cents) : "—"}
          sub={metrics?.avg_cost_per_tour_cents ? `~${fmtUsd(metrics.avg_cost_per_tour_cents)} / tour` : "no renders yet"}
          accent="var(--green)"
        />
        <MetricCard
          index={3}
          label="Gross Margin"
          value={metrics?.gross_margin_pct ? `${metrics.gross_margin_pct}%` : "—"}
          sub="after render cost"
          accent="var(--purple)"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <div className="glass p-5">
            <div className="label-caps mb-3">Tour Status</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(counts).map(([status, n]) => (
                <div key={status} className="flex items-center gap-2 text-[12px] text-ink-2">
                  <StatusBadge status={status} />
                  <span className="font-semibold text-ink">{n}</span>
                </div>
              ))}
              {tours.length === 0 && (
                <span className="text-[12px] text-ink-3">No tours yet.</span>
              )}
            </div>
          </div>

          <div className="glass p-5">
            <div className="label-caps mb-3">Render Queue</div>
            {queue.length === 0 ? (
              <div className="py-6 text-center text-[12px] text-ink-3">Queue is empty.</div>
            ) : (
              <div className="space-y-1">
                {queue.slice(0, 8).map((j) => {
                  const tour = tours.find((t) => t.id === j.tour_id);
                  const Icon =
                    j.status === "failed" ? AlertTriangle : j.status === "done" ? Check : Loader2;
                  return (
                    <Link
                      key={j.id}
                      href={`/tours/${j.tour_id}`}
                      className="hairline glass-hover flex items-center gap-3 rounded-sm bg-white/[0.02] px-3 py-2.5"
                    >
                      <Icon
                        size={14}
                        strokeWidth={1.5}
                        className={
                          j.status === "failed"
                            ? "text-danger"
                            : j.status === "done"
                              ? "text-success"
                              : "animate-spin text-warning"
                        }
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium">
                          {tour?.address ?? j.tour_id}
                        </div>
                        <div className="truncate text-[11px] text-ink-3">{j.stage_detail}</div>
                      </div>
                      <StatusBadge status={j.status} />
                      <span className="w-14 text-right text-[12px] text-ink-3">
                        {fmtUsd(j.veo_cost_cents)}
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="glass p-5">
            <div className="label-caps mb-3">Generation Control</div>
            <div className="mb-3 flex items-center gap-2 text-[13px] font-medium">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: killswitchLocked ? "var(--red)" : "var(--green)" }}
              />
              {killswitchLocked ? "HARD STOPPED" : "LIVE — Generating allowed"}
            </div>
            <button
              onClick={async () => {
                setBusy(true);
                await toggleKillswitch().finally(() => setBusy(false));
              }}
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-sm px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: killswitchLocked ? "var(--green)" : "var(--red)" }}
            >
              <Power size={14} strokeWidth={2} />
              {killswitchLocked ? "CONTINUE — Allow Generation" : "HARD STOP — Kill All"}
            </button>
            <p className="mt-2.5 text-[11px] leading-relaxed text-ink-3">
              When stopped, new renders return HTTP 423 and in-flight jobs halt
              before their next Veo call.
            </p>
          </div>

          {tours.length === 0 && (
            <EmptyState title="No tours yet" hint="Create your first tour with ⌘K or the New Tour button." />
          )}
        </div>
      </div>
    </div>
  );
}
