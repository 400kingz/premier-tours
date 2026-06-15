"use client";

import { useEffect, useRef, useState } from "react";
import { jobEventSource } from "@/lib/api";
import type { RenderJob, Tour } from "@/lib/types";

/** Subscribe to the SSE render-progress stream for one tour. */
export function useJobStream(tourId: string | null, initial: RenderJob | null = null) {
  const [job, setJob] = useState<RenderJob | null>(initial);
  const [tour, setTour] = useState<Tour | null>(null);
  const [live, setLive] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!tourId) return;
    const es = jobEventSource(tourId);
    sourceRef.current = es;
    setLive(true);

    es.addEventListener("job", (e) => setJob(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("tour", (e) => setTour(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("end", () => {
      setLive(false);
      es.close();
    });
    es.onerror = () => setLive(false);

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [tourId]);

  return { job, tourUpdate: tour, live };
}
