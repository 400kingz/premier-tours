import { create } from "zustand";
import type { Metrics, Tour } from "./types";
import { api } from "./api";

interface AppState {
  tours: Tour[];
  metrics: Metrics | null;
  killswitchLocked: boolean;
  paletteOpen: boolean;
  loaded: boolean;

  refresh: () => Promise<void>;
  setPaletteOpen: (open: boolean) => void;
  toggleKillswitch: () => Promise<void>;
  upsertTour: (tour: Tour) => void;
}

export const useApp = create<AppState>((set, get) => ({
  tours: [],
  metrics: null,
  killswitchLocked: false,
  paletteOpen: false,
  loaded: false,

  refresh: async () => {
    const [tours, metrics, ks] = await Promise.all([
      api.listTours(),
      api.metrics(),
      api.killswitch(),
    ]);
    set({ tours, metrics, killswitchLocked: ks.locked, loaded: true });
  },

  setPaletteOpen: (open) => set({ paletteOpen: open }),

  toggleKillswitch: async () => {
    const next = !get().killswitchLocked;
    const res = await api.setKillswitch(next);
    set({ killswitchLocked: res.locked });
  },

  upsertTour: (tour) =>
    set((s) => ({
      tours: s.tours.some((t) => t.id === tour.id)
        ? s.tours.map((t) => (t.id === tour.id ? tour : t))
        : [tour, ...s.tours],
    })),
}));
