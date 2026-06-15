export type TourStatus =
  | "draft"
  | "intake"
  | "rendering"
  | "ready"
  | "delivered"
  | "failed";

export type JobStatus =
  | "queued"
  | "screenplay"
  | "rendering"
  | "compositing"
  | "uploading"
  | "done"
  | "failed";

export type ShotStatus =
  | "queued"
  | "generating"
  | "qa"
  | "accepted"
  | "rejected"
  | "failed";

export interface Shot {
  idx: number;
  room_type: string;
  prompt: string;
  status: ShotStatus;
  motion: number;
  qa_verdict: string | null;
  qa_attempts: number;
  cost_cents: number;
  clip_path: string | null;
  source_photo: string | null;
  error: string | null;
}

export interface RenderJob {
  id: string;
  tour_id: string;
  status: JobStatus;
  stage_detail: string;
  shots_total: number;
  shots_done: number;
  veo_cost_cents: number;
  shots: Shot[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
  updated_at: string;
}

export interface Tour {
  id: string;
  address: string;
  agent_name: string;
  agent_email: string;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  price_cents: number | null;
  status: TourStatus;
  source: "upload" | "listing_url" | "drive_url";
  source_url: string | null;
  photo_paths: string[];
  master_path: string | null;
  preview_path: string | null;
  reel_path: string | null;
  share_url: string | null;
  veo_cost_cents: number;
  created_at: string;
  updated_at: string;
}

export interface Metrics {
  revenue_cents: number;
  tours_delivered: number;
  in_queue: number;
  veo_spend_cents: number;
  avg_cost_per_tour_cents: number;
  gross_margin_pct: number;
}

export interface Activity {
  kind: "info" | "success" | "danger";
  title: string;
  detail: string;
  tour_id: string | null;
  at: string;
}
