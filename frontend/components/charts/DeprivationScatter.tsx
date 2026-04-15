"use client";

/**
 * DeprivationScatter — Recharts scatter plot showing IMD rank vs composite
 * health score for all 33 London boroughs.
 *
 * X-axis: IMD rank (reversed so most deprived is on the left).
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
  ReferenceLine,
  Label,
} from "recharts";
import type { BoroughScore } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";

/** Label the N most extreme points (highest/lowest health, most/least deprived). */
const LABEL_BOROUGHS = new Set([
  "City of London",      // lowest health, least deprived — outlier
  "Westminster",         // low health, moderate deprivation
  "Richmond upon Thames", // high health, least deprived
  "Newham",              // most deprived
  "Bromley",             // high health, low deprivation
]);

interface DeprivationScatterProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
}

interface ScatterPoint {
  x: number;
  y: number;
  borough_name: string;
  borough_code: string;
  imd_rank: number;
  composite_score: number;
  fill: string;
}

function mergeData(
  boroughs: BoroughScore[],
  deprivation: Record<string, { imd_rank: number; name: string }>,
): ScatterPoint[] {
  const points: ScatterPoint[] = [];
  for (const b of boroughs) {
    const dep = deprivation[b.borough_code];
    if (!dep || b.composite_score === null) continue;
    points.push({
      x: dep.imd_rank,
      y: Math.round(b.composite_score * 10) / 10,
      borough_name: b.borough_name,
      borough_code: b.borough_code,
      imd_rank: dep.imd_rank,
      composite_score: Math.round(b.composite_score * 10) / 10,
      fill: scoreToColour(b.composite_score),
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
  const isLabelled = LABEL_BOROUGHS.has(payload.borough_name);
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
        <span>IMD Rank</span>
        <span className="text-white">{data.imd_rank}</span>
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
}: DeprivationScatterProps) {
  const data = mergeData(boroughs, deprivation);
  const regression = linearRegression(data);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-xs font-mono">
        No deprivation data available
      </div>
    );
  }

  return (
    <div>
      {/* Title */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: "#0ea5e9" }}
      >
        HEALTH vs DEPRIVATION
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <XAxis
            type="number"
            dataKey="x"
            name="IMD Rank"
            reversed
            domain={["dataMin - 5", "dataMax + 5"]}
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
            label={{
              value: "IMD Rank (1 = most deprived)",
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
    </div>
  );
}
