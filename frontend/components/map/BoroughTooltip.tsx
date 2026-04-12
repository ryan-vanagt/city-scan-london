"use client";

/**
 * Hover tooltip for a borough on the thermal map.
 *
 * Shows borough name in ALL CAPS, 4 metric scores with short text labels,
 * and the composite score below a divider.
 */

import type { BoroughScore, MetricFilter } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";

interface BoroughTooltipProps {
  borough: BoroughScore;
  position: { x: number; y: number };
  metricFilter: MetricFilter;
}

interface MetricDisplay {
  abbr: string;
  key: keyof BoroughScore;
  source: string;
}

const METRICS: MetricDisplay[] = [
  { abbr: "AIR", key: "air_score", source: "OpenAQ" },
  { abbr: "TRS", key: "transit_score", source: "TfL" },
  { abbr: "SNT", key: "sentiment_score", source: "Reddit/Guardian/BBC" },
  { abbr: "IMM", key: "immune_score", source: "Met Police/NHS" },
];

function formatScore(value: number | null): string {
  if (value === null) return "--";
  return Math.round(value).toString();
}

export default function BoroughTooltip({
  borough,
  position,
  metricFilter,
}: BoroughTooltipProps) {
  const compositeColour = scoreToColour(borough.composite_score);

  // When a metric filter is active, show only that metric and use its colour for the border.
  const visibleMetrics = metricFilter
    ? METRICS.filter(({ key }) => key === metricFilter)
    : METRICS;
  const borderColour = metricFilter
    ? scoreToColour(borough[metricFilter] as number | null)
    : compositeColour;

  return (
    <div
      className="pointer-events-none absolute z-50"
      style={{
        left: position.x,
        top: position.y,
        transform: "translate(-50%, -110%)",
      }}
    >
      <div
        className="rounded-md px-3 py-2 text-xs min-w-[180px]"
        style={{
          backgroundColor: "rgba(15, 23, 42, 0.9)",
          border: `1px solid ${borderColour}`,
          boxShadow: `0 0 12px ${borderColour}40`,
        }}
      >
        {/* Borough name */}
        <div
          className="text-slate-200 text-[11px] font-medium mb-1.5"
          style={{ letterSpacing: "0.15em" }}
        >
          {borough.borough_name.toUpperCase()}
        </div>

        {/* Metric scores row */}
        <div className="flex items-center gap-2.5 font-mono text-[11px]">
          {visibleMetrics.map(({ abbr, key }) => (
            <span key={key} className="flex items-center gap-1">
              <span
                className="text-[9px] font-medium"
                style={{ color: "#0ea5e9", letterSpacing: "0.05em" }}
              >
                {abbr}
              </span>
              <span className="text-white">
                {formatScore(borough[key] as number | null)}
              </span>
            </span>
          ))}
        </div>

        {/* Divider */}
        <div className="my-1.5 border-t border-slate-700" />

        {/* Overall score */}
        <div className="font-mono text-xs text-slate-200">
          Overall:{" "}
          <span className="font-bold" style={{ color: compositeColour }}>
            {formatScore(borough.composite_score)}
          </span>
        </div>
      </div>
    </div>
  );
}
