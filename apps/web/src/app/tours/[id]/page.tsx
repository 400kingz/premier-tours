"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import { Clapperboard, Play, RotateCw } from "lucide-react";
import { api, fmtUsd, mediaUrl } from "@/lib/api";
import type { RenderJob, Tour } from "@/lib/types";
import { useJobStream } from "@/hooks/use-job-stream";
import { PipelineFlow } from "@/components/pipeline-flow";
import { Progress, StatusBadge } from "@/components/ui";

const ROOM_EMOJI: Record<string, string> = {
  aerial: "🚁", front_exterior: "🏠", entryway: "🚪", living_room: "🛋️",
  dining_room: "🍽️", kitchen: "🍳", primary_bedroom: "🛏️", bedroom: "🛏️",
  bathroom: "🛁", backyard: "🌳", pool: "🏊", patio: "☂️",
};

export default function TourDetail() {
  const { id } = useParams<{ id: string }>();
  const [tour, setTour] = useState<Tour | null>(null);
  const [initialJob, setInitialJob] = useState<RenderJob | null>(null);
  const [video, setVideo] = useState<"master" | "preview" | "reel">("preview");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const isActive =
    initialJob != null && !["done", "failed"].includes(initialJob.status);
  const { job: liveJob, tourUpdate } = useJobStream(isActive ? id : null, initialJob);
  const job = liveJob ?? initialJob;

  useEffect(() => {
    api.getTour(id).then(setTour).catch(() => setError("Tour not found"));
    api.latestJob(id).then(setInitialJob).catch(() => {});
  }, [id]);

  useEffect(() => {
    if (tourUpdate) setTour(tourUpdate);
  }, [tourUpdate]);

  const startRender = async () => {
    setStarting(true);
    setError(null);
    try {
      const j = await api.startRender(id);
      setInitialJob(j);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start render");
    } finally {
      setStarting(false);
    }
  };

  if (error && !tour) {
    return <div className="py-20 text-center text-[13px] text-ink-3">{error}</div>;
  }
  if (!tour) {
    return <div className="py-20 text-center text-[13px] text-ink-3">Loading…</div>;
  }

  const videoPath =
    video === "master" ? tour.master_path : video === "reel" ? tour.reel_path : tour.preview_path;
  const videoUrl = mediaUrl(videoPath);
  const pct = job && job.shots_total > 0 ? (job.shots_done / job.shots_total) * 100 : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-bold tracking-tight">{tour.address}</h1>
        <StatusBadge status={tour.status} />
        <div className="ml-auto flex items-center gap-2">
          {tour.veo_cost_cents > 0 && (
            <span className="text-[12px] text-ink-3">Veo {fmtUsd(tour.veo_cost_cents)}</span>
          )}
          <button
            onClick={startRender}
            disabled={starting || isActive || tour.photo_paths.length === 0}
            className="flex items-center gap-1.5 rounded-sm bg-tint px-3.5 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {isActive ? <RotateCw size={13} className="animate-spin" /> : <Clapperboard size={13} />}
            {isActive ? "Rendering…" : tour.master_path ? "Re-render" : "Render Tour"}
          </button>
        </div>
      </div>
      {error && <div className="text-[12px] text-danger">{error}</div>}

      <PipelineFlow job={job} />
      {job && job.shots_total > 0 && (
        <div className="space-y-1.5">
          <Progress pct={job.status === "done" ? 100 : pct} />
          <div className="flex justify-between text-[11px] text-ink-3">
            <span>{job.stage_detail}</span>
            <span>{job.shots_done}/{job.shots_total} shots</span>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <div className="glass overflow-hidden !rounded-lg">
            <div className={`relative bg-black ${video === "reel" ? "mx-auto aspect-[9/16] max-h-[560px]" : "aspect-video"}`}>
              {videoUrl ? (
                <video
                  key={videoUrl}
                  src={videoUrl}
                  controls
                  playsInline
                  className="h-full w-full"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-[13px] text-ink-3">
                  <Play size={28} strokeWidth={1} className="mr-2 opacity-40" />
                  {isActive ? "Render in progress…" : "No video yet — render the tour."}
                </div>
              )}
            </div>
            <div className="flex items-center gap-1 p-2">
              {(["preview", "master", "reel"] as const).map((v) => {
                const available =
                  v === "master" ? !!tour.master_path : v === "reel" ? !!tour.reel_path : !!tour.preview_path;
                return (
                  <button
                    key={v}
                    onClick={() => setVideo(v)}
                    disabled={!available}
                    className={`rounded-sm px-3 py-1.5 text-[12px] font-medium capitalize transition-colors ${
                      video === v ? "hairline bg-white/[0.08] text-ink" : "text-ink-3 hover:text-ink-2"
                    } disabled:opacity-30`}
                  >
                    {v === "reel" ? "Social Reel 9:16" : v === "master" ? "Master 16:9" : "Preview"}
                  </button>
                );
              })}
            </div>
          </div>

          {job && job.shots.length > 0 && (
            <div className="glass p-4">
              <div className="label-caps mb-3">Shots</div>
              <div className="space-y-2">
                {job.shots.map((s) => (
                  <motion.div
                    key={s.idx}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: s.idx * 0.04 }}
                    className="hairline rounded-sm bg-white/[0.02] p-3"
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="text-[15px]">{ROOM_EMOJI[s.room_type] ?? "📷"}</span>
                      <span className="text-[12px] font-semibold capitalize">
                        {s.room_type.replace(/_/g, " ")}
                      </span>
                      <StatusBadge status={s.status} />
                      <span className="ml-auto text-[11px] text-ink-3">
                        {s.motion > 0 && `motion ${s.motion.toFixed(2)} · `}
                        {s.qa_attempts > 1 && `${s.qa_attempts} attempts · `}
                        {s.cost_cents > 0 && fmtUsd(s.cost_cents)}
                      </span>
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-ink-3">
                      {s.prompt}
                    </p>
                    {s.error && <p className="mt-1 text-[11px] text-danger">{s.error}</p>}
                    {s.qa_verdict && !s.error && (
                      <p className="mt-1 text-[11px] text-ink-3">QA: {s.qa_verdict}</p>
                    )}
                  </motion.div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="glass p-4">
            <div className="label-caps mb-3">Listing</div>
            <dl className="space-y-2 text-[12px]">
              {[
                ["Agent", tour.agent_name || "—"],
                ["Email", tour.agent_email || "—"],
                ["Beds", tour.beds ?? "—"],
                ["Baths", tour.baths ?? "—"],
                ["Sq ft", tour.sqft?.toLocaleString() ?? "—"],
                ["Source", tour.source.replace("_", " ")],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between">
                  <dt className="text-ink-3">{k}</dt>
                  <dd className="font-medium">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>

          {tour.photo_paths.length > 0 && (
            <div className="glass p-4">
              <div className="label-caps mb-3">Photos ({tour.photo_paths.length})</div>
              <div className="grid grid-cols-3 gap-1.5">
                {tour.photo_paths.map((p, i) => {
                  const url = mediaUrl(p);
                  return url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={i}
                      src={url}
                      alt=""
                      className="hairline aspect-square rounded-sm object-cover"
                    />
                  ) : null;
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
