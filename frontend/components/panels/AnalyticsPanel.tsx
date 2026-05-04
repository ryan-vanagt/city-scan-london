"use client";

/**
 * AnalyticsPanel — planner-first analytics side panel.
 *
 * Order is intentional:
 * 1. Critical organs (most actionable triage view)
 * 2. Health vs Deprivation scatter (with IMD/Housing toggle)
 * 3. Equity patterns + Top 5 Unexpected divergences
 * 4. Borough radar comparison
 * 5. Organ time series
 * 6. ONS Health Index validation (methodology / trust artifact, last)
 *
 * Follows the same panel structure as DoctorChat:
 * dark background, left border, header with close button, scrollable content.
 */

import { useState } from "react";
import { X } from "lucide-react";
import type {
  BoroughScore,
  HousingAffordability,
  HealthIndexEntry,
} from "@/lib/types";
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

export default function AnalyticsPanel({
  boroughs,
  deprivation,
  housingAffordability,
  healthIndex,
  onClose,
}: AnalyticsPanelProps) {
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
          middle, methodology + validation at the bottom. The organ-key
          legend lives at the bottom as a footnote so it doesn't break
          the flow into actionable content. */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-8">
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

        {/* 3. Equity patterns — |r| per organ against IMD + Top 5 Unexpected.
            (Old standalone "INSIGHT" callout removed — its content was
            duplicated by EquityPatterns chart + caption below.) */}
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

        {/* Organ-key footnote — quiet legend at the bottom decodes the
            metaphor for anyone who skipped the in-context labels above. */}
        <div
          className="text-[10px] font-mono pt-2 mt-4"
          style={{
            color: "#475569",
            borderTop: "1px solid #1e293b",
            lineHeight: 1.55,
          }}
        >
          Lungs = air · Arteries = transit · Brain = sentiment · Immune =
          crime + A&E · Skin = green space
        </div>
      </div>
    </div>
  );
}
