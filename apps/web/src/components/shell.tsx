"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { Command, Film, LayoutGrid, Plus, Radio } from "lucide-react";
import { useApp } from "@/lib/store";
import { CommandPalette } from "./command-palette";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutGrid },
  { href: "/tours", label: "Tours", icon: Film },
  { href: "/activity", label: "Activity", icon: Radio },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { setPaletteOpen, refresh, loaded } = useApp();

  useEffect(() => {
    if (!loaded) refresh().catch(() => {});
  }, [loaded, refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPaletteOpen]);

  const isLanding = pathname === "/";

  return (
    <>
      <CommandPalette />
      {!isLanding && (
        <header className="sticky top-0 z-40">
          <div className="mx-auto max-w-[1440px] px-6 pt-4">
            <nav className="glass flex h-12 items-center gap-1 px-3">
              <Link
                href="/"
                className="mr-3 flex items-center gap-2 text-[13px] font-semibold tracking-tight"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-[7px] bg-tint/90 text-[11px] font-bold text-white">
                  P
                </span>
                Premier Home Tours
              </Link>
              {NAV.map(({ href, label, icon: Icon }) => {
                const active = pathname.startsWith(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-[13px] transition-colors ${
                      active
                        ? "hairline bg-white/[0.07] text-ink"
                        : "text-ink-2 hover:text-ink"
                    }`}
                  >
                    <Icon size={14} strokeWidth={1.5} />
                    <span className="hidden sm:inline">{label}</span>
                  </Link>
                );
              })}
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={() => setPaletteOpen(true)}
                  className="hairline flex items-center gap-2 rounded-sm bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-ink-3 transition-colors hover:text-ink-2"
                >
                  <Command size={12} strokeWidth={1.5} />K
                </button>
                <Link
                  href="/new"
                  className="flex items-center gap-1.5 rounded-sm bg-tint px-3 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
                >
                  <Plus size={14} strokeWidth={2} />
                  New Tour
                </Link>
              </div>
            </nav>
          </div>
        </header>
      )}
      <main className={isLanding ? "" : "mx-auto max-w-[1440px] px-6 py-6"}>
        {children}
      </main>
    </>
  );
}
