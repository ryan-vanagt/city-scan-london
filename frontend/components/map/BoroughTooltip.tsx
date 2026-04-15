"use client";

/**
 * Hover tooltip for a borough on the thermal map.
 *
 * Vertical layout showing borough name in ALL CAPS, each metric on its own
 * row with full name labels, composite score below a divider, and optional
 * IMD deprivation rank.
 */

import type { BoroughScore, MetricFilter } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";

interface BoroughTooltipProps {
  borough: BoroughScore;
  position: { x: number; y: number };
  metricFilter: MetricFilter;
  imdRank: number | null;
}

interface MetricDisplay {
  label: string;
  key: keyof BoroughScore;
  source: string;
}

const METRICS: MetricDisplay[] = [
  { label: "Air Quality", key: "air_score", source: "OpenAQ" },
  { label: "Transit", key: "transit_score", source: "TfL" },
  { label: "Sentiment", key: "sentiment_score", source: "Reddit/Guardian/BBC" },
  { label: "Crime & A&E", key: "immune_score", source: "Met Police/NHS" },
  { label: "Green Space", key: "green_space_score", source: "GLA Green Cover" },
];

function formatScore(value: number | null): string {
  if (value === null) return "--";
  return Math.round(value).toString();
}

function ordinalSuffix(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  const mod10 = n % 10;
  if (mod10 === 1) return `${n}st`;
  if (mod10 === 2) return `${n}nd`;
  if (mod10 === 3) return `${n}rd`;
  return `${n}th`;
}

export default function BoroughTooltip({
  borough,
  position,
  metricFilter,
  imdRank,
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
      className="pointer-events-none fixed z-[60]"
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

        {/* Metric scores — vertical layout */}
        <div className="flex flex-col gap-0.5">
          {visibleMetrics.map(({ label, key }) => (
            <div key={key} className="flex items-center justify-between gap-4">
              <span
                className="text-[9px] font-medium"
                style={{ color: "#0ea5e9", letterSpacing: "0.05em" }}
              >
                {label}
              </span>
              <span className="text-white font-mono text-[11px]">
                {formatScore(borough[key] as number | null)}
              </span>
            </div>
          ))}
        </div>

        {/* Divider */}
        <div className="my-1.5 border-t border-slate-700" />

        {/* Overall score */}
        <div className="flex items-center justify-between gap-4">
          <span
            className="text-[9px] font-medium"
            style={{ color: "#0ea5e9", letterSpacing: "0.05em" }}
          >
            Overall
          </span>
          <span className="font-mono text-[11px] font-bold" style={{ color: compositeColour }}>
            {formatScore(borough.composite_score)}
          </span>
        </div>

        {/* IMD Deprivation rank */}
        {imdRank !== null && (
          <div className="flex items-center justify-between gap-4 mt-0.5">
            <span
              className="text-[9px] font-medium"
              style={{ color: "#0ea5e9", letterSpacing: "0.05em" }}
            >
              Deprivation
            </span>
            <span className="font-mono text-[11px] text-slate-300">
              {ordinalSuffix(imdRank)} / 296
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
