"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Clapperboard, ScanEye, Sparkles } from "lucide-react";

const FEATURES = [
  {
    icon: Sparkles,
    title: "Zero-touch intake",
    body: "Drop listing photos or a share link. Gemini Vision curates hero shots and writes the flight plan.",
  },
  {
    icon: Clapperboard,
    title: "Cinematic FPV motion",
    body: "Veo renders each room; whip transitions punch through doorways like a real FPV drone.",
  },
  {
    icon: ScanEye,
    title: "Self-healing QA",
    body: "Every clip is inspected against the source photo. Architectural hallucinations are auto-rejected and re-rendered.",
  },
];

export default function Landing() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="max-w-[720px] text-center"
      >
        <div className="label-caps mb-4">Premier Home Tours</div>
        <h1 className="text-balance text-5xl font-bold leading-[1.06] tracking-tight sm:text-6xl">
          Drone tours without
          <br />
          <span className="bg-gradient-to-r from-tint to-[#5ac8fa] bg-clip-text text-transparent">
            the drone.
          </span>
        </h1>
        <p className="mx-auto mt-5 max-w-[480px] text-[15px] leading-relaxed text-ink-2">
          A listing’s photos in, a cinematic 22-second FPV flythrough out —
          MLS-compliant master plus a vertical social reel, in minutes.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link
            href="/new"
            className="flex items-center gap-2 rounded-[12px] bg-tint px-5 py-2.5 text-[14px] font-medium text-white transition-opacity hover:opacity-90"
          >
            Create a tour <ArrowRight size={15} strokeWidth={2} />
          </Link>
          <Link
            href="/dashboard"
            className="glass glass-hover px-5 py-2.5 text-[14px] font-medium text-ink-2 hover:text-ink"
          >
            Open dashboard
          </Link>
        </div>
      </motion.div>

      <div className="mt-16 grid w-full max-w-[860px] gap-3 sm:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body }, i) => (
          <motion.div
            key={title}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.08, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="glass glass-hover p-5 text-left"
          >
            <Icon size={17} strokeWidth={1.5} className="text-tint" />
            <div className="mt-3 text-[13px] font-semibold">{title}</div>
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">{body}</p>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
