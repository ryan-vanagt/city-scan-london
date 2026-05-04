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

import { useMemo, useState } from "react";
import { X } from "lucide-react";
import type {
  BoroughScore,
  HousingAffordability,
  HealthIndexEntry,
} from "@/lib/types";
import { pearson } from "@/lib/stats";
import DeprivationScatter, {
  type DeprivationXAxisMode,
} from "@/components/charts/DeprivationScatter";
import BoroughRadar from "@/components/charts/BoroughRadar";
import BoroughTimeSeries from "@/components/charts/BoroughTimeSeries";
import EquityPatterns from "@/components/charts/EquityPatterns";
import HealthIndexValidation from "@/components/charts/HealthIndexValidation";
import WorstOrganTable from "@/components/charts/WorstOrganTable";

interface AnalyticsPanelProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
  housingAffordability?: Record<string, HousingAffordability>;
  healthIndex?: Record<string, HealthIndexEntry>;
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
  housingAffordability,
  healthIndex,
  onClose,
}: AnalyticsPanelProps) {
  const correlationInsight = useCorrelationInsight(boroughs, deprivation);
  const [xAxisMode, setXAxisMode] = useState<DeprivationXAxisMode>("imd");
  const housingAvailable =
    !!housingAffordability && Object.keys(housingAffordability).length > 0;
  const healthIndexAvailable =
    !!healthIndex && Object.keys(healthIndex).length > 0;

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

      {/* Scrollable content — order is planner-first:
          actionable triage at the top, comparison and context in the
          middle, methodology + validation at the bottom. */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-8">
        {/* Organ key — bridges the metaphor and the underlying data so
            planners aren't left guessing what "Brain" or "Skin" means.
            Static, invariant — these labels are part of the brand. */}
        <div
          className="text-[10px] font-mono px-3 py-2 rounded"
          style={{
            backgroundColor: "rgba(15, 23, 42, 0.6)",
            border: "1px dashed #1e293b",
            color: "#64748b",
            lineHeight: 1.55,
          }}
        >
          Lungs = air · Arteries = transit · Brain = sentiment · Immune =
          crime + A&E · Skin = green space
        </div>

        {/* 1. Critical organs table — most actionable view, planner first stop */}
        <WorstOrganTable boroughs={boroughs} />

        {/* 2. Scatter plot — health vs deprivation/affordability */}
        <div>
          {housingAvailable && (
            <div className="flex items-center justify-end gap-1 mb-2">
              <span className="text-[10px] uppercase tracking-wider text-slate-500 mr-1">
                X-axis
              </span>
              <button
                onClick={() => setXAxisMode("imd")}
                className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded transition-colors"
                style={{
                  backgroundColor:
                    xAxisMode === "imd" ? "rgba(14,165,233,0.18)" : "transparent",
                  color: xAxisMode === "imd" ? "#0ea5e9" : "#64748b",
                  border: `1px solid ${xAxisMode === "imd" ? "#0ea5e9" : "#1e293b"}`,
                }}
              >
                IMD
              </button>
              <button
                onClick={() => setXAxisMode("housing")}
                className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider rounded transition-colors"
                style={{
                  backgroundColor:
                    xAxisMode === "housing" ? "rgba(14,165,233,0.18)" : "transparent",
                  color: xAxisMode === "housing" ? "#0ea5e9" : "#64748b",
                  border: `1px solid ${xAxisMode === "housing" ? "#0ea5e9" : "#1e293b"}`,
                }}
              >
                Housing
              </button>
            </div>
          )}
          <DeprivationScatter
            boroughs={boroughs}
            deprivation={deprivation}
            housingAffordability={housingAffordability}
            xAxisMode={xAxisMode}
          />
        </div>

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

        {/* 3. Equity patterns — |r| per organ against IMD + Top 5 Unexpected */}
        <EquityPatterns boroughs={boroughs} deprivation={deprivation} />

        {/* 4. Radar comparison */}
        <BoroughRadar boroughs={boroughs} />

        {/* 5. Time series */}
        <BoroughTimeSeries boroughs={boroughs} />

        {/* 6. ONS Health Index validation — methodology / trust artifact at the
            bottom of the panel; statistician-relevant, planner-skippable. */}
        {healthIndexAvailable && healthIndex && (
          <HealthIndexValidation
            boroughs={boroughs}
            healthIndex={healthIndex}
          />
        )}
      </div>
    </div>
  );
}
