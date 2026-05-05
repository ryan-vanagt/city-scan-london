"use client";

/**
 * Hover tooltip for a borough on the thermal map.
 *
 * Vertical layout showing borough name in ALL CAPS, each metric on its own
 * row with full name labels, composite score below a divider, and optional
 * IMD deprivation rank.
 */

import type { BoroughScore, MetricFilter, TransitAccess } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";

interface BoroughTooltipProps {
  borough: BoroughScore;
  position: { x: number; y: number };
  metricFilter: MetricFilter;
  imdRank: number | null;
  transitAccess?: TransitAccess;
}

interface MetricDisplay {
  label: string;
  key: keyof BoroughScore;
  source: string;
}

// Key is the filter identifier (matches MetricFilter in types.ts).
// For green space, the filter is "green_space_score" (historical name) but
// the DISPLAYED value is the ward-pop-weighted access variant when available.
// Variant detail (raw coverage, modelled air) is rendered only when the
// matching filter is active — the default all-organs tooltip stays clean.
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
  transitAccess,
}: BoroughTooltipProps) {
  const compositeColour = scoreToColour(borough.composite_score);

  // When a metric filter is active, show only that metric and use its colour for the border.
  const visibleMetrics = metricFilter
    ? METRICS.filter(({ key }) => key === metricFilter)
    : METRICS;
  // For the green-space filter, use the access-weighted value for colouring
  // (falling back to raw coverage) so the tooltip's border matches the map fill.
  const filterValue = metricFilter === "green_space_score"
    ? (borough.green_space_access_score ?? borough.green_space_score)
    : metricFilter
      ? (borough[metricFilter] as number | null)
      : null;
  const borderColour = metricFilter
    ? scoreToColour(filterValue)
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

        {/* Metric scores — vertical layout */}
        <div className="flex flex-col gap-0.5">
          {visibleMetrics.map(({ label, key }) => {
            const isGreen = key === "green_space_score";
            const isAir = key === "air_score";
            const isTransit = key === "transit_score";
            // For green space, prefer access-weighted, fall back to raw coverage.
            const displayValue = isGreen
              ? (borough.green_space_access_score ?? borough.green_space_score)
              : (borough[key] as number | null);
            return (
              <div key={key} className="flex flex-col">
                <div className="flex items-center justify-between gap-4">
                  <span
                    className="text-[9px] font-medium"
                    style={{ color: "#0ea5e9", letterSpacing: "0.05em" }}
                  >
                    {label}
                  </span>
                  <span className="text-white font-mono text-[11px]">
                    {formatScore(displayValue)}
                  </span>
                </div>
                {isGreen
                  && metricFilter === "green_space_score"
                  && borough.green_space_score !== null
                  && borough.green_space_access_score !== null && (
                  <div className="flex items-center justify-between gap-4 text-[8px] text-slate-500">
                    <span style={{ letterSpacing: "0.05em" }}>coverage</span>
                    <span className="font-mono">
                      {formatScore(borough.green_space_score)}
                    </span>
                  </div>
                )}
                {isAir
                  && metricFilter === "air_score"
                  && borough.air_quality_modelled_score !== null && (
                  <div className="flex items-center justify-between gap-4 text-[8px] text-slate-500">
                    <span style={{ letterSpacing: "0.05em" }}>modelled</span>
                    <span className="font-mono">
                      {formatScore(borough.air_quality_modelled_score)}
                    </span>
                  </div>
                )}
                {isTransit
                  && metricFilter === "transit_score"
                  && transitAccess
                  && transitAccess.ptal_band && (
                  <div className="flex items-center justify-between gap-4 text-[8px] text-slate-500">
                    <span style={{ letterSpacing: "0.05em" }}>
                      PTAL access (2015)
                    </span>
                    <span className="font-mono">
                      {transitAccess.ptal_band}
                      {transitAccess.score !== null && (
                        <span style={{ color: "#475569" }}>
                          {" "}· idx {formatScore(transitAccess.score)}
                        </span>
                      )}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
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
