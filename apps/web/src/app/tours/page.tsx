"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Play, Search } from "lucide-react";
import { fmtUsd, mediaUrl } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { TourStatus } from "@/lib/types";
import { EmptyState, StatusBadge } from "@/components/ui";

const FILTERS: ("all" | TourStatus)[] = [
  "all", "delivered", "ready", "rendering", "intake", "failed",
];

export default function ToursPage() {
  const { tours } = useApp();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(
    () =>
      tours
        .filter((t) => filter === "all" || t.status === filter)
        .filter(
          (t) =>
            !search ||
            t.address.toLowerCase().includes(search.toLowerCase()) ||
            t.agent_name.toLowerCase().includes(search.toLowerCase()),
        ),
    [tours, filter, search],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="glass flex items-center gap-1 p-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-sm px-3 py-1.5 text-[12px] font-medium capitalize transition-colors ${
                filter === f ? "hairline bg-white/[0.08] text-ink" : "text-ink-3 hover:text-ink-2"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="glass ml-auto flex h-9 w-[260px] items-center gap-2 px-3">
          <Search size={13} strokeWidth={1.5} className="text-ink-3" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by address or agent…"
            className="w-full bg-transparent text-[13px] outline-none placeholder:text-ink-3"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No tours match" hint="Adjust the filter, or create a new tour." />
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
          {filtered.map((t, i) => {
            const thumb = mediaUrl(t.photo_paths[0] ?? null);
            return (
              <motion.div
                key={t.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.04, 0.3), duration: 0.3 }}
              >
                <Link href={`/tours/${t.id}`} className="glass glass-hover group block overflow-hidden !rounded-lg">
                  <div className="relative aspect-video bg-gradient-to-br from-white/[0.05] to-transparent">
                    {thumb && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={thumb} alt="" className="h-full w-full object-cover" />
                    )}
                    <div className="absolute left-3 top-3">
                      <StatusBadge status={t.status} />
                    </div>
                    {t.veo_cost_cents > 0 && (
                      <span className="absolute bottom-3 right-3 rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-medium backdrop-blur">
                        {fmtUsd(t.veo_cost_cents)}
                      </span>
                    )}
                    {(t.master_path || t.preview_path) && (
                      <div className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black/55 backdrop-blur">
                          <Play size={18} className="ml-0.5 text-white" fill="white" />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="p-3.5">
                    <div className="truncate text-[13px] font-semibold">{t.address}</div>
                    <div className="mt-1 truncate text-[11px] text-ink-3">
                      {[t.agent_name || null, `${t.photo_paths.length} photos`, new Date(t.created_at).toLocaleDateString()]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
