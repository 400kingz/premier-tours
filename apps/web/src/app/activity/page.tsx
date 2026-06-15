"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Activity } from "@/lib/types";
import { EmptyState } from "@/components/ui";

const DOT: Record<Activity["kind"], string> = {
  info: "var(--tint)",
  success: "var(--green)",
  danger: "var(--red)",
};

export default function ActivityPage() {
  const [items, setItems] = useState<Activity[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.activity().then(setItems).finally(() => setLoaded(true));
    const t = setInterval(() => api.activity().then(setItems).catch(() => {}), 8000);
    return () => clearInterval(t);
  }, []);

  if (loaded && items.length === 0) {
    return <EmptyState title="No activity yet" hint="Events appear here as tours move through the pipeline." />;
  }

  return (
    <div className="mx-auto max-w-[720px] space-y-1.5">
      {items.map((a, i) => (
        <div key={i} className="glass glass-hover flex items-start gap-3 p-3.5">
          <span
            className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
            style={{ background: DOT[a.kind] }}
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-semibold">{a.title}</span>
              <span className="ml-auto shrink-0 text-[11px] text-ink-3">
                {new Date(a.at).toLocaleString()}
              </span>
            </div>
            {a.detail && <div className="mt-0.5 text-[12px] text-ink-3">{a.detail}</div>}
            {a.tour_id && (
              <Link href={`/tours/${a.tour_id}`} className="mt-1 inline-block text-[11px] text-tint hover:underline">
                View tour →
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
