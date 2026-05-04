"use client";

/**
 * QualityDot — small data-quality indicator next to a score.
 *
 * Renders a single coloured dot (green / amber / red) with a hover-only
 * tooltip surfacing the underlying detail: bootstrap CI for bootstrappable
 * organs, disclosure note for static/invariant signals, sample size, etc.
 *
 * Designed for the planner UX: the dot itself is the primary signal
 * ("can I trust this number for fine-grained decisions?"), while the
 * statistical detail is gated behind hover for analyst drilldown.
 */

import { useState } from "react";
import type { OrganQuality, QualityFlag } from "@/lib/types";

const COLOURS: Record<QualityFlag, string> = {
  green: "#22c55e",
  amber: "#f59e0b",
  red: "#ef4444",
};

const FLAG_LABELS: Record<QualityFlag, string> = {
  green: "Trustworthy",
  amber: "Use with care",
  red: "Indicative only",
};

interface QualityDotProps {
  quality: OrganQuality | undefined;
  size?: number;        // dot diameter in px (default 8)
  inline?: boolean;     // if true, displays inline-block; otherwise positioned absolute by parent
}

export default function QualityDot({ quality, size = 8, inline = true }: QualityDotProps) {
  const [hover, setHover] = useState(false);

  if (!quality) return null;

  const colour = COLOURS[quality.flag];

  return (
    <span
      className="relative"
      style={{ display: inline ? "inline-block" : "block" }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <span
        aria-label={`Data quality: ${FLAG_LABELS[quality.flag]}`}
        style={{
          display: "inline-block",
          width: size,
          height: size,
          borderRadius: "50%",
          backgroundColor: colour,
          boxShadow: `0 0 4px ${colour}66`,
          verticalAlign: "middle",
          cursor: "help",
        }}
      />
      {hover && (
        <span
          className="absolute z-50 rounded px-2.5 py-2 text-[10px] font-mono pointer-events-none"
          style={{
            backgroundColor: "rgba(15, 23, 42, 0.97)",
            border: `1px solid ${colour}`,
            color: "#cbd5e1",
            minWidth: 200,
            maxWidth: 260,
            whiteSpace: "normal",
            lineHeight: 1.45,
            bottom: size + 6,
            left: "50%",
            transform: "translateX(-50%)",
          }}
        >
          <div style={{ color: colour, fontWeight: 600, marginBottom: 4 }}>
            {FLAG_LABELS[quality.flag]}
          </div>
          {quality.ci_low !== null && quality.ci_high !== null ? (
            <div style={{ color: "#94a3b8" }}>
              95% CI: {quality.ci_low.toFixed(1)} – {quality.ci_high.toFixed(1)}
              {quality.width !== null && (
                <span style={{ color: "#64748b" }}>
                  {" "}(width {quality.width.toFixed(1)})
                </span>
              )}
            </div>
          ) : null}
          {quality.note && (
            <div style={{ color: "#94a3b8", marginTop: 2 }}>{quality.note}</div>
          )}
          {quality.flag_basis && (
            <div style={{ color: "#94a3b8", marginTop: 2 }}>{quality.flag_basis}</div>
          )}
          <div style={{ color: "#475569", marginTop: 4 }}>
            n = {quality.n}
          </div>
        </span>
      )}
    </span>
  );
}
