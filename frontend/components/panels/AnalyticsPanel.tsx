"use client";

/**
 * AnalyticsPanel — side panel with four analytics views:
 *
 * 1. Health vs Deprivation scatter plot
 * 2. Cross-domain correlation insight (auto-computed)
 * 3. Borough comparison radar chart
 * 4. Organ history time series
 * 5. Critical organs table
 *
 * Follows the same panel structure as DoctorChat:
 * dark background, left border, header with close button, scrollable content.
 */

import { useMemo } from "react";
import { X } from "lucide-react";
import type { BoroughScore } from "@/lib/types";
import DeprivationScatter from "@/components/charts/DeprivationScatter";
import BoroughRadar from "@/components/charts/BoroughRadar";
import BoroughTimeSeries from "@/components/charts/BoroughTimeSeries";
import WorstOrganTable from "@/components/charts/WorstOrganTable";

interface AnalyticsPanelProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Cross-domain correlation insight                                    */
/* ------------------------------------------------------------------ */

const ORGAN_LABELS: Record<string, string> = {
  air_score: "Air quality",
  transit_score: "Transit",
  sentiment_score: "Sentiment",
  immune_score: "Crime & A&E",
  green_space_score: "Green space",
};

/** Pearson correlation between two arrays (skipping pairs with null). */
function pearson(xs: (number | null)[], ys: (number | null)[]): number | null {
  const pairs: [number, number][] = [];
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] !== null && ys[i] !== null) pairs.push([xs[i]!, ys[i]!]);
  }
  if (pairs.length < 5) return null;
  const n = pairs.length;
  let sx = 0, sy = 0, sxy = 0, sx2 = 0, sy2 = 0;
  for (const [x, y] of pairs) {
    sx += x; sy += y; sxy += x * y; sx2 += x * x; sy2 += y * y;
  }
  const num = n * sxy - sx * sy;
  const den = Math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy));
  if (den === 0) return null;
  return num / den;
}

function useCorrelationInsight(
  boroughs: BoroughScore[],
  deprivation: Record<string, { imd_rank: number; name: string }>,
): string | null {
  return useMemo(() => {
    const matched = boroughs
      .filter((b) => deprivation[b.borough_code] && b.composite_score !== null)
      .map((b) => ({ ...b, imd_rank: deprivation[b.borough_code].imd_rank }));

    if (matched.length < 10) return null;

    const imdRanks = matched.map((b) => b.imd_rank);
    const organs = ["air_score", "transit_score", "sentiment_score", "immune_score", "green_space_score"] as const;

    let strongest: { organ: string; r: number } | null = null;

    for (const organ of organs) {
      const scores = matched.map((b) => b[organ]);
      const r = pearson(imdRanks, scores);
      if (r !== null && (strongest === null || Math.abs(r) > Math.abs(strongest.r))) {
        strongest = { organ, r };
      }
    }

    if (!strongest) return null;

    const label = ORGAN_LABELS[strongest.organ] || strongest.organ;
    const absR = Math.abs(strongest.r).toFixed(2);
    const direction = strongest.r > 0
      ? "poorer boroughs score worse"
      : "poorer boroughs score better";

    return `${label} has the strongest link to deprivation (r=${absR}) — ${direction}.`;
  }, [boroughs, deprivation]);
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AnalyticsPanel({
  boroughs,
  deprivation,
  onClose,
}: AnalyticsPanelProps) {
  const correlationInsight = useCorrelationInsight(boroughs, deprivation);

  return (
    <div
      className="h-full flex flex-col"
      style={{ background: "#0f172a", borderLeft: "1px solid #1e293b" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid #1e293b" }}
      >
        <span
          className="text-sm font-semibold text-slate-100 uppercase tracking-widest"
        >
          ANALYTICS
        </span>
        <button
          onClick={onClose}
          className="p-1 rounded text-[#64748b] hover:text-slate-200 transition-colors duration-200"
          aria-label="Close analytics"
        >
          <X size={16} />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-8">
        {/* 1. Scatter plot */}
        <DeprivationScatter boroughs={boroughs} deprivation={deprivation} />

        {/* Correlation insight */}
        {correlationInsight && (
          <div
            className="text-xs font-mono px-3 py-2 rounded"
            style={{
              backgroundColor: "rgba(14, 165, 233, 0.08)",
              border: "1px solid rgba(14, 165, 233, 0.2)",
              color: "#94a3b8",
            }}
          >
            <span style={{ color: "#0ea5e9" }}>INSIGHT: </span>
            {correlationInsight}
          </div>
        )}

        {/* 2. Radar comparison */}
        <BoroughRadar boroughs={boroughs} />

        {/* 3. Time series */}
        <BoroughTimeSeries boroughs={boroughs} />

        {/* 4. Critical organs table */}
        <WorstOrganTable boroughs={boroughs} />
      </div>
    </div>
  );
}
