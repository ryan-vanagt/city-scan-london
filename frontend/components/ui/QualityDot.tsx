"use client";

/**
 * QualityDot — small data-quality indicator next to a score.
 *
 * Renders a single coloured dot (green / amber / red) with a hover-only
 * tooltip surfacing the underlying detail: bootstrap CI for bootstrappable
 * organs, disclosure note for static/invariant signals, sample size, etc.
 *
 * Tooltip is rendered into a React portal (document.body) and positioned
 * via getBoundingClientRect so it can escape any `overflow: hidden|auto`
 * ancestor — important here because WorstOrganTable lives inside a scroll
 * container that would otherwise clip the tooltip on the right edge and
 * along the bottom boundary.
 *
 * Designed for the planner UX: the dot itself is the primary signal
 * ("can I trust this number?"), while the statistical detail is gated
 * behind hover for analyst drilldown.
 */

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import type { OrganQuality, QualityFlag } from "@/lib/types";

const COLOURS: Record<QualityFlag, string> = {
  green: "#22c55e",
  amber: "#f59e0b",
  red: "#ef4444",
};

/**
 * Reliability levels — describe how STABLE the score is, not whether the
 * score itself is good or bad. A score of 7.9 with HIGH reliability means
 * "we are confident the real value is around 7.9" — not "7.9 is a good score".
 */
const FLAG_LABELS: Record<QualityFlag, string> = {
  green: "HIGH",
  amber: "MEDIUM",
  red: "LOW",
};

interface QualityDotProps {
  quality: OrganQuality | undefined;
  size?: number;
}

const TOOLTIP_WIDTH = 240;
const TOOLTIP_GAP = 8;

export default function QualityDot({ quality, size = 8 }: QualityDotProps) {
  const [hover, setHover] = useState(false);
  const [coords, setCoords] = useState<{ left: number; top: number } | null>(null);
  const dotRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!hover || !dotRef.current) {
      setCoords(null);
      return;
    }
    const rect = dotRef.current.getBoundingClientRect();
    // Default: tooltip centered horizontally on the dot, above it.
    let left = rect.left + rect.width / 2 - TOOLTIP_WIDTH / 2;
    // Clamp within the viewport so we never overflow the right edge.
    const maxLeft = window.innerWidth - TOOLTIP_WIDTH - 8;
    if (left > maxLeft) left = maxLeft;
    if (left < 8) left = 8;
    const top = rect.top - TOOLTIP_GAP;
    setCoords({ left, top });
  }, [hover]);

  if (!quality) return null;

  const colour = COLOURS[quality.flag];

  return (
    <>
      <span
        ref={dotRef}
        aria-label={`Score quality: ${FLAG_LABELS[quality.flag]}`}
        className="inline-block"
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          backgroundColor: colour,
          boxShadow: `0 0 4px ${colour}66`,
          verticalAlign: "middle",
          cursor: "help",
        }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      />
      {hover && coords && typeof document !== "undefined" &&
        createPortal(
          <div
            className="fixed z-[1000] rounded px-3 py-2 text-[10px] font-mono pointer-events-none"
            style={{
              left: coords.left,
              top: coords.top,
              transform: "translateY(-100%)",
              width: TOOLTIP_WIDTH,
              backgroundColor: "rgba(15, 23, 42, 0.97)",
              border: `1px solid ${colour}`,
              color: "#cbd5e1",
              lineHeight: 1.45,
            }}
          >
            <div
              style={{
                color: colour,
                fontWeight: 600,
                marginBottom: 4,
                letterSpacing: "0.05em",
              }}
            >
              Score quality: {FLAG_LABELS[quality.flag]}
            </div>
            {quality.ci_low !== null && quality.ci_high !== null && quality.width !== null ? (
              <div style={{ color: "#94a3b8" }}>
                30-day mean precise to ±{(quality.width / 2).toFixed(1)} pts
                <span style={{ color: "#64748b" }}>
                  {" "}(95% CI {quality.ci_low.toFixed(1)}–{quality.ci_high.toFixed(1)})
                </span>
                {quality.sd !== undefined && quality.sd !== null && (
                  <div style={{ color: "#64748b", marginTop: 1 }}>
                    Day-to-day SD: ±{quality.sd.toFixed(1)} pts
                  </div>
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
              Based on {quality.n} recent observations
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
