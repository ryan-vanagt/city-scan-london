"use client";

/**
 * DeprivationScatter — Recharts scatter plot showing a deprivation/affordability
 * proxy on the X-axis vs composite health score on the Y-axis for all 33
 * London boroughs.
 *
 * Two X-axis modes:
 *   - "imd"     — IMD rank (most deprived on left)
 *   - "housing" — ONS Housing Affordability Ratio (most affordable on left,
 *                 least on right)
 *
 * Y-axis: Composite health score (0-100).
 * Each dot is coloured using the thermal gradient from lib/colours.ts.
 */

import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import type { BoroughScore, HousingAffordability } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";
import { pearson, strengthWord } from "@/lib/stats";

export type DeprivationXAxisMode = "imd" | "housing";

/**
 * Per-mode labelled outliers — chosen to match the extremes of THAT view's
 * X-axis plus the most distinctive composite-score outliers. Re-uses
 * Westminster + City of London across both modes (they're outliers either way).
 */
const LABEL_BOROUGHS_BY_MODE: Record<DeprivationXAxisMode, Set<string>> = {
  imd: new Set([
    "City of London",       // lowest health, least deprived — outlier
    "Westminster",          // low health, moderate deprivation
    "Richmond upon Thames", // high health, least deprived
    "Newham",               // most deprived
    "Bromley",              // high health, low deprivation
  ]),
  housing: new Set([
    "Kensington and Chelsea", // most expensive — far right
    "Tower Hamlets",          // most affordable — far left
    "Westminster",            // expensive AND low health (compound stress)
    "Bromley",                // mid-priced, highest health
    "City of London",         // mid-priced, lowest health
  ]),
};

interface DeprivationScatterProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
  housingAffordability?: Record<string, HousingAffordability>;
  xAxisMode?: DeprivationXAxisMode;
}

interface ScatterPoint {
  x: number;
  y: number;
  borough_name: string;
  borough_code: string;
  xLabel: string;     // e.g. "IMD Rank" or "Affordability Ratio"
  xValue: number;
  composite_score: number;
  fill: string;
  isLabelled: boolean;
}

function mergeData(
  boroughs: BoroughScore[],
  deprivation: Record<string, { imd_rank: number; name: string }>,
  housingAffordability: Record<string, HousingAffordability> | undefined,
  mode: DeprivationXAxisMode,
): ScatterPoint[] {
  const labelSet = LABEL_BOROUGHS_BY_MODE[mode];
  const points: ScatterPoint[] = [];
  for (const b of boroughs) {
    if (b.composite_score === null) continue;

    let xValue: number | null = null;
    let xLabel = "";
    if (mode === "imd") {
      const dep = deprivation[b.borough_code];
      if (!dep) continue;
      xValue = dep.imd_rank;
      xLabel = "IMD Rank";
    } else {
      const housing = housingAffordability?.[b.borough_code];
      if (!housing || housing.ratio === null) continue;
      xValue = housing.ratio;
      xLabel = "Affordability Ratio";
    }

    points.push({
      x: xValue,
      y: Math.round(b.composite_score * 10) / 10,
      borough_name: b.borough_name,
      borough_code: b.borough_code,
      xLabel,
      xValue,
      composite_score: Math.round(b.composite_score * 10) / 10,
      fill: scoreToColour(b.composite_score),
      isLabelled: labelSet.has(b.borough_name),
    });
  }
  return points;
}

interface CustomDotProps {
  cx?: number;
  cy?: number;
  payload?: ScatterPoint;
}

function CustomDot({ cx, cy, payload }: CustomDotProps) {
  if (cx === undefined || cy === undefined || !payload) return null;
  const isLabelled = payload.isLabelled;
  return (
    <g>
      <circle
        cx={cx}
        cy={cy}
        r={isLabelled ? 6 : 5}
        fill={payload.fill}
        stroke={isLabelled ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.2)"}
        strokeWidth={isLabelled ? 1 : 0.5}
      />
      {isLabelled && (
        <text
          x={cx}
          y={cy - 10}
          textAnchor="middle"
          fill="#94a3b8"
          fontSize={8}
          fontFamily="var(--font-jetbrains, monospace)"
        >
          {payload.borough_name}
        </text>
      )}
    </g>
  );
}

interface TooltipPayloadEntry {
  payload: ScatterPoint;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const data = payload[0].payload;
  return (
    <div
      className="rounded px-3 py-2 text-xs font-mono"
      style={{
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        border: "1px solid #1e293b",
      }}
    >
      <div className="text-slate-200 font-medium mb-1" style={{ letterSpacing: "0.1em" }}>
        {data.borough_name.toUpperCase()}
      </div>
      <div className="flex justify-between gap-4 text-slate-400">
        <span>{data.xLabel}</span>
        <span className="text-white">
          {Number.isInteger(data.xValue) ? data.xValue : data.xValue.toFixed(2)}
        </span>
      </div>
      <div className="flex justify-between gap-4 text-slate-400">
        <span>Health Score</span>
        <span style={{ color: data.fill }}>{data.composite_score}</span>
      </div>
    </div>
  );
}

/** Simple linear regression: returns {slope, intercept} for y = slope*x + intercept */
function linearRegression(points: ScatterPoint[]): { slope: number; intercept: number } | null {
  if (points.length < 2) return null;
  const n = points.length;
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (const p of points) {
    sumX += p.x;
    sumY += p.y;
    sumXY += p.x * p.y;
    sumX2 += p.x * p.x;
  }
  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return null;
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

export default function DeprivationScatter({
  boroughs,
  deprivation,
  housingAffordability,
  xAxisMode = "imd",
}: DeprivationScatterProps) {
  const data = mergeData(boroughs, deprivation, housingAffordability, xAxisMode);
  const regression = linearRegression(data);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-xs font-mono">
        {xAxisMode === "imd"
          ? "No deprivation data available"
          : "No housing affordability data available"}
      </div>
    );
  }

  const title = xAxisMode === "imd" ? "HEALTH vs DEPRIVATION" : "HEALTH vs HOUSING AFFORDABILITY";
  const xAxisLabel =
    xAxisMode === "imd"
      ? "← Most Deprived          IMD Rank          Least Deprived →"
      : "← More Affordable                                                Less Affordable →";

  // R² for the on-screen rigor signal. pearson() returns null if <5 pairs or
  // zero variance; the caption falls back gracefully in that case.
  const r =
    data.length >= 5
      ? pearson(data.map((d) => d.x), data.map((d) => d.y))
      : null;
  const rSquared = r !== null ? r * r : null;

  // Caption is built entirely from computed values — no hardcoded interpretive
  // claims that could go stale or contradict the data.
  // For IMD mode: x is rank (most-deprived has SMALLEST x). For Housing mode:
  // x is the ratio (most-affordable has SMALLEST x). Either way, the
  // smallest-x point is the "most" and the largest-x is the "least".
  const captionText: string = (() => {
    if (data.length < 5 || r === null) {
      return data.length === 0
        ? ""
        : `n = ${data.length} — sample too small for stable correlation.`;
    }
    const sorted = [...data].sort((a, b) => a.x - b.x);
    const compositeRanked = [...data].sort((a, b) => b.y - a.y); // best first
    const rankByCode: Record<string, number> = {};
    compositeRanked.forEach((p, i) => {
      rankByCode[p.borough_code] = i + 1;
    });
    const lowX = sorted[0];
    const highX = sorted[sorted.length - 1];
    const strength = strengthWord(r);
    const r2Text = (r * r).toFixed(3);

    if (xAxisMode === "imd") {
      // smallest IMD rank = most deprived
      return (
        `IMD rank ${strength} predicts composite health (r² = ${r2Text}, n = ${data.length}). ` +
        `Most deprived (${lowX.borough_name}) ranks ${rankByCode[lowX.borough_code]}/${data.length} by health; ` +
        `least deprived (${highX.borough_name}) ranks ${rankByCode[highX.borough_code]}/${data.length}.`
      );
    }
    // housing mode: smallest ratio = most affordable
    return (
      `Housing affordability ${strength} predicts composite health (r² = ${r2Text}, n = ${data.length}). ` +
      `Most expensive (${highX.borough_name}, ${highX.x.toFixed(1)}×) ranks ${rankByCode[highX.borough_code]}/${data.length} by health; ` +
      `most affordable (${lowX.borough_name}, ${lowX.x.toFixed(1)}×) ranks ${rankByCode[lowX.borough_code]}/${data.length}.`
    );
  })();

  return (
    <div>
      {/* Title row — title left, R² + n right */}
      <div className="flex items-baseline justify-between mb-3">
        <div
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: "#0ea5e9" }}
        >
          {title}
        </div>
        {rSquared !== null && (
          <div
            className="text-[10px] font-mono"
            style={{ color: "#64748b", letterSpacing: "0.05em" }}
          >
            r² = {rSquared.toFixed(3)} · n = {data.length}
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <XAxis
            type="number"
            dataKey="x"
            name={xAxisMode === "imd" ? "IMD Rank" : "Affordability Ratio"}
            domain={
              xAxisMode === "imd"
                ? ["dataMin - 5", "dataMax + 5"]
                : ["dataMin - 1", "dataMax + 1"]
            }
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
            label={{
              value: xAxisLabel,
              position: "bottom",
              offset: 12,
              style: { fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" },
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="Health Score"
            domain={[0, 100]}
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
            label={{
              value: "Health Score",
              angle: -90,
              position: "insideLeft",
              offset: 0,
              style: { fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" },
            }}
          />
          <Tooltip content={<CustomTooltip />} cursor={false} />
          <Scatter
            data={data}
            shape={<CustomDot />}
          />
          {regression && (() => {
            const xMin = Math.min(...data.map(d => d.x));
            const xMax = Math.max(...data.map(d => d.x));
            const trendData = [
              { x: xMin, y: regression.slope * xMin + regression.intercept },
              { x: xMax, y: regression.slope * xMax + regression.intercept },
            ];
            return (
              <Scatter
                data={trendData}
                line={{ stroke: "rgba(14, 165, 233, 0.4)", strokeWidth: 1.5, strokeDasharray: "6 3" }}
                shape={() => null}
                legendType="none"
                isAnimationActive={false}
              />
            );
          })()}
        </ScatterChart>
      </ResponsiveContainer>

      {/* Mode-aware caption — pulls the headline finding into plain text. */}
      <div
        className="mt-2 text-[11px] font-mono px-3 py-2 rounded"
        style={{
          backgroundColor: "rgba(14, 165, 233, 0.05)",
          border: "1px solid rgba(14, 165, 233, 0.15)",
          color: "#94a3b8",
          lineHeight: 1.55,
        }}
      >
        {captionText}
      </div>
    </div>
  );
}
