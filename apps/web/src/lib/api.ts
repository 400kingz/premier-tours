import type { Activity, Metrics, RenderJob, Tour } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const GCS_BASE = "https://storage.googleapis.com/premier-tours-media";

export function mediaUrl(objectPath: string | null): string | null {
  if (!objectPath) return null;
  if (objectPath.startsWith("http")) return objectPath;
  if (objectPath.startsWith("tours/")) return `${GCS_BASE}/${objectPath}`;
  // Local dev path under OUTPUT_DIR/UPLOAD_DIR — served by the API.
  const name = objectPath.split("/").slice(-2).join("/");
  return objectPath.includes("/uploads/")
    ? `${API_BASE}/media/uploads/${name}`
    : `${API_BASE}/media/renders/${name}`;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listTours: () => request<Tour[]>("/api/tours"),
  getTour: (id: string) => request<Tour>(`/api/tours/${id}`),
  latestJob: (tourId: string) =>
    request<RenderJob | null>(`/api/tours/${tourId}/job`),

  createTour: (body: {
    address: string;
    agent_name?: string;
    agent_email?: string;
    source?: "upload" | "listing_url" | "drive_url";
    source_url?: string;
    beds?: number;
    baths?: number;
    sqft?: number;
  }) => request<Tour>("/api/intake", { method: "POST", body: JSON.stringify(body) }),

  uploadPhotos: async (tourId: string, files: File[]): Promise<Tour> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${API_BASE}/api/intake/${tourId}/photos`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(res.status, body.detail ?? res.statusText);
    }
    return res.json();
  },

  startRender: (tourId: string, opts?: { max_shots?: number; dry_run?: boolean }) =>
    request<RenderJob>("/api/render", {
      method: "POST",
      body: JSON.stringify({ tour_id: tourId, ...opts }),
    }),

  metrics: () => request<Metrics>("/api/admin/metrics"),
  queue: () => request<Omit<RenderJob, "shots">[]>("/api/admin/queue"),
  activity: () => request<Activity[]>("/api/admin/activity"),
  killswitch: () => request<{ locked: boolean }>("/api/admin/killswitch"),
  setKillswitch: (locked: boolean) =>
    request<{ locked: boolean }>("/api/admin/killswitch", {
      method: "POST",
      body: JSON.stringify({ locked }),
    }),
};

export function jobEventSource(tourId: string): EventSource {
  return new EventSource(`${API_BASE}/api/events/tours/${tourId}`);
}

export const fmtUsd = (cents: number) =>
  (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: cents % 100 === 0 ? 0 : 2 });
