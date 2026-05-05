"use client";

/**
 * Full-viewport notice shown in place of the main dashboard on narrow
 * screens. CityScan is a desktop tool — the SVG thermal map, Recharts
 * analytics, and slide-out Doctor chat all need horizontal real estate
 * that phones don't have. Rather than ship a half-broken mobile layout
 * we render this screen and nothing else.
 */

import { Monitor } from "lucide-react";

export default function MobileNotice() {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-6 py-12 text-center"
      style={{
        background: "#020617",
        fontFamily: "var(--font-jetbrains, monospace)",
      }}
    >
      <div className="flex flex-col items-center gap-6 max-w-sm">
        <div
          className="rounded-full p-4"
          style={{
            background: "rgba(14, 165, 233, 0.08)",
            border: "1px solid rgba(14, 165, 233, 0.25)",
          }}
        >
          <Monitor size={40} color="#0ea5e9" strokeWidth={1.5} />
        </div>

        <div className="flex flex-col gap-2">
          <h1
            className="text-lg font-semibold uppercase tracking-widest"
            style={{ color: "#0ea5e9" }}
          >
            CityScan London
          </h1>
          <p className="text-xs text-slate-400 uppercase tracking-widest">
            Desktop experience
          </p>
        </div>

        <div
          className="text-sm leading-relaxed px-4 py-4 rounded"
          style={{
            color: "#cbd5e1",
            background: "rgba(15, 23, 42, 0.6)",
            border: "1px solid #1e293b",
            lineHeight: 1.6,
          }}
        >
          This project was built for larger screens. The thermal map, the
          analytics panel, and the Doctor agent need the room only a
          laptop can give them.
          <br />
          <br />
          <span className="text-slate-500">
            Come back on a desktop browser to see the live signals.
          </span>
        </div>

        <div className="text-[10px] text-slate-600 tracking-widest uppercase mt-2">
          cityscanldn.app · Open on a laptop
        </div>
      </div>
    </div>
  );
}
