"use client";

import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Film,
  LayoutGrid,
  Plus,
  Power,
  Radio,
  Search,
} from "lucide-react";
import { useApp } from "@/lib/store";

export function CommandPalette() {
  const router = useRouter();
  const { paletteOpen, setPaletteOpen, tours, killswitchLocked, toggleKillswitch } =
    useApp();

  const go = (path: string) => {
    setPaletteOpen(false);
    router.push(path);
  };

  return (
    <AnimatePresence>
      {paletteOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[18vh] backdrop-blur-[20px]"
          onClick={() => setPaletteOpen(false)}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className="glass w-full max-w-[560px] overflow-hidden !rounded-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <Command label="Command palette" loop>
              <div className="flex items-center gap-2.5 border-b-[0.5px] border-white/10 px-4">
                <Search size={15} strokeWidth={1.5} className="text-ink-3" />
                <Command.Input
                  autoFocus
                  placeholder="Search tours, run commands…"
                  className="h-12 w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-3"
                />
              </div>
              <Command.List className="max-h-[320px] overflow-y-auto p-2">
                <Command.Empty className="px-3 py-8 text-center text-[13px] text-ink-3">
                  No results.
                </Command.Empty>

                <Command.Group
                  heading="Navigate"
                  className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
                >
                  {[
                    { label: "Overview", path: "/dashboard", icon: LayoutGrid },
                    { label: "Tours", path: "/tours", icon: Film },
                    { label: "Activity", path: "/activity", icon: Radio },
                    { label: "New Tour", path: "/new", icon: Plus },
                  ].map(({ label, path, icon: Icon }) => (
                    <Command.Item
                      key={path}
                      onSelect={() => go(path)}
                      className="flex cursor-pointer items-center gap-2.5 rounded-sm px-3 py-2 text-[13px] text-ink-2 data-[selected=true]:bg-white/[0.07] data-[selected=true]:text-ink"
                    >
                      <Icon size={14} strokeWidth={1.5} />
                      {label}
                    </Command.Item>
                  ))}
                </Command.Group>

                <Command.Group
                  heading="System"
                  className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
                >
                  <Command.Item
                    onSelect={() => {
                      toggleKillswitch();
                      setPaletteOpen(false);
                    }}
                    className="flex cursor-pointer items-center gap-2.5 rounded-sm px-3 py-2 text-[13px] text-ink-2 data-[selected=true]:bg-white/[0.07] data-[selected=true]:text-ink"
                  >
                    <Power
                      size={14}
                      strokeWidth={1.5}
                      className={killswitchLocked ? "text-success" : "text-danger"}
                    />
                    {killswitchLocked
                      ? "Resume generation"
                      : "HARD STOP — kill all generation"}
                  </Command.Item>
                </Command.Group>

                {tours.length > 0 && (
                  <Command.Group
                    heading="Tours"
                    className="[&_[cmdk-group-heading]]:label-caps [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5"
                  >
                    {tours.slice(0, 8).map((t) => (
                      <Command.Item
                        key={t.id}
                        value={`${t.address} ${t.id}`}
                        onSelect={() => go(`/tours/${t.id}`)}
                        className="flex cursor-pointer items-center gap-2.5 rounded-sm px-3 py-2 text-[13px] text-ink-2 data-[selected=true]:bg-white/[0.07] data-[selected=true]:text-ink"
                      >
                        <Film size={14} strokeWidth={1.5} />
                        {t.address}
                        <span className="ml-auto text-[11px] text-ink-3">{t.status}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
