"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Link2, Loader2, UploadCloud, X } from "lucide-react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/store";

type Mode = "upload" | "url";

export default function NewTour() {
  const router = useRouter();
  const { upsertTour } = useApp();
  const [mode, setMode] = useState<Mode>("upload");
  const [address, setAddress] = useState("");
  const [agentName, setAgentName] = useState("");
  const [agentEmail, setAgentEmail] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addFiles = useCallback((list: FileList | null) => {
    if (!list) return;
    const imgs = Array.from(list).filter((f) => f.type.startsWith("image/"));
    setFiles((prev) => [...prev, ...imgs].slice(0, 12));
  }, []);

  const submit = async () => {
    if (!address.trim()) {
      setError("Address is required");
      return;
    }
    if (mode === "upload" && files.length < 3) {
      setError("Upload at least 3 photos");
      return;
    }
    if (mode === "url" && !sourceUrl.trim()) {
      setError("Paste a listing or Drive URL");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const isDrive = sourceUrl.includes("drive.google.com");
      let tour = await api.createTour({
        address: address.trim(),
        agent_name: agentName.trim(),
        agent_email: agentEmail.trim(),
        ...(mode === "url"
          ? { source: isDrive ? "drive_url" : "listing_url", source_url: sourceUrl.trim() }
          : { source: "upload" }),
      });
      if (mode === "upload") {
        tour = await api.uploadPhotos(tour.id, files);
      }
      upsertTour(tour);
      router.push(`/tours/${tour.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[640px]">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        <h1 className="text-[22px] font-bold tracking-tight">New Tour</h1>
        <p className="mt-1 text-[13px] text-ink-3">
          Photos in, cinematic flythrough out. 3–12 photos, one per room works best.
        </p>

        <div className="glass mt-5 space-y-4 p-5">
          <div>
            <label className="label-caps mb-1.5 block">Property address</label>
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="912 Marigold Ct, Austin TX"
              className="hairline w-full rounded-sm bg-white/[0.03] px-3 py-2.5 text-[14px] outline-none transition-shadow placeholder:text-ink-3 focus:shadow-[inset_0_0_0_1px_var(--tint)]"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-caps mb-1.5 block">Agent name</label>
              <input
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                placeholder="Dana Keller"
                className="hairline w-full rounded-sm bg-white/[0.03] px-3 py-2.5 text-[14px] outline-none transition-shadow placeholder:text-ink-3 focus:shadow-[inset_0_0_0_1px_var(--tint)]"
              />
            </div>
            <div>
              <label className="label-caps mb-1.5 block">Agent email</label>
              <input
                value={agentEmail}
                onChange={(e) => setAgentEmail(e.target.value)}
                placeholder="dana@realty.com"
                type="email"
                className="hairline w-full rounded-sm bg-white/[0.03] px-3 py-2.5 text-[14px] outline-none transition-shadow placeholder:text-ink-3 focus:shadow-[inset_0_0_0_1px_var(--tint)]"
              />
            </div>
          </div>

          <div className="hairline flex gap-1 rounded-sm bg-white/[0.02] p-1">
            {(
              [
                { key: "upload", label: "Upload photos", icon: UploadCloud },
                { key: "url", label: "Listing / Drive URL", icon: Link2 },
              ] as const
            ).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setMode(key)}
                className={`flex flex-1 items-center justify-center gap-2 rounded-[8px] py-2 text-[13px] font-medium transition-colors ${
                  mode === key ? "hairline bg-white/[0.07] text-ink" : "text-ink-3 hover:text-ink-2"
                }`}
              >
                <Icon size={14} strokeWidth={1.5} />
                {label}
              </button>
            ))}
          </div>

          {mode === "upload" ? (
            <div>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  addFiles(e.dataTransfer.files);
                }}
                onClick={() => document.getElementById("file-input")?.click()}
                className={`flex cursor-pointer flex-col items-center justify-center rounded-sm border border-dashed py-10 transition-colors ${
                  dragging ? "border-tint bg-tint/5" : "border-white/15 hover:border-white/30"
                }`}
              >
                <UploadCloud size={22} strokeWidth={1.25} className="text-ink-3" />
                <div className="mt-2 text-[13px] text-ink-2">
                  Drop listing photos or click to browse
                </div>
                <div className="mt-0.5 text-[11px] text-ink-3">JPG, PNG, WebP · up to 12</div>
                <input
                  id="file-input"
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => addFiles(e.target.files)}
                />
              </div>
              {files.length > 0 && (
                <div className="mt-3 grid grid-cols-4 gap-2">
                  {files.map((f, i) => (
                    <div key={i} className="group relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={URL.createObjectURL(f)}
                        alt=""
                        className="hairline aspect-square w-full rounded-sm object-cover"
                      />
                      <button
                        onClick={() => setFiles(files.filter((_, j) => j !== i))}
                        className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full bg-black/80 group-hover:flex"
                      >
                        <X size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div>
              <input
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="https://drive.google.com/… or listing page URL"
                className="hairline w-full rounded-sm bg-white/[0.03] px-3 py-2.5 text-[14px] outline-none transition-shadow placeholder:text-ink-3 focus:shadow-[inset_0_0_0_1px_var(--tint)]"
              />
              <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
                Major portals (Zillow, Redfin) block automated access — for those,
                download the photos and use Upload, or share a Drive folder link.
              </p>
            </div>
          )}

          {error && <div className="text-[12px] text-danger">{error}</div>}

          <button
            onClick={submit}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-sm bg-tint py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy && <Loader2 size={15} className="animate-spin" />}
            {busy ? "Creating tour…" : "Create Tour"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
