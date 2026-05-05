"use client";

/**
 * HealthIndexValidation — convergent-validity scatter.
 *
 * X-axis: CityScan composite score (live, 0–100 normalised across the 33
 *         London boroughs).
 * Y-axis: ONS Health Index latest score (England-2015 baseline = 100).
 *         Built from inputs entirely outside CityScan's pipeline (life
 *         expectancy, mortality, mental health prevalence, behaviours).
 *
 * A non-trivial R² supports the composite as a leading indicator of an
 * independent gold-standard outcome — i.e. construct/convergent validity.
 *
 * Notes:
 *  - n = 32 because ONS excludes City of London from the Health Index.
 *  - Caption is fully derived from data: r, R², strength word, and named
 *    largest-residual borough are all computed live; no hardcoded prose.
 *  - Health Index is multi-year-lagged (latest 2021); the chart therefore
 *    measures retrospective convergent validity.
 */

import { useMemo } from "react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import type { BoroughScore, HealthIndexEntry } from "@/lib/types";
import { pearson } from "@/lib/stats";
import { scoreToColour } from "@/lib/colours";

interface HealthIndexValidationProps {
  boroughs: BoroughScore[];
  healthIndex: Record<string, HealthIndexEntry>;
}

interface Point {
  x: number;             // CityScan composite
  y: number;             // ONS Health Index score
  borough_name: string;
  borough_code: string;
  fill: string;
  isLabelled: boolean;
}

function buildPoints(
  boroughs: BoroughScore[],
  healthIndex: Record<string, HealthIndexEntry>,
): Point[] {
  // Compute residuals first to identify the most divergent boroughs to label.
  const candidates: { code: string; name: string; x: number; y: number }[] = [];
  for (const b of boroughs) {
    const hi = healthIndex[b.borough_code];
    if (!hi || hi.score === null || b.composite_score === null) continue;
    candidates.push({
      code: b.borough_code,
      name: b.borough_name,
      x: b.composite_score,
      y: hi.score,
    });
  }
  if (candidates.length < 5) return [];

  const n = candidates.length;
  let sx = 0, sy = 0, sxy = 0, sxx = 0;
  for (const c of candidates) {
    sx += c.x; sy += c.y; sxy += c.x * c.y; sxx += c.x * c.x;
  }
  const mx = sx / n;
  const my = sy / n;
  const denom = sxx - n * mx * mx;
  const slope = denom === 0 ? 0 : (sxy - n * mx * my) / denom;
  const intercept = my - slope * mx;

  // Label: top borough by Health Index, bottom borough by Health Index, plus
  // top 2 by |residual|. Stable choices that work across reasonable data shifts.
  const sortedByHI = [...candidates].sort((a, b) => b.y - a.y);
  const sortedByResidual = [...candidates]
    .map((c) => ({ ...c, resid: c.y - (slope * c.x + intercept) }))
    .sort((a, b) => Math.abs(b.resid) - Math.abs(a.resid));

  const labelSet = new Set<string>([
    sortedByHI[0].code,
    sortedByHI[sortedByHI.length - 1].code,
    sortedByResidual[0].code,
    sortedByResidual[1].code,
  ]);

  return candidates.map((c) => ({
    x: c.x,
    y: c.y,
    borough_name: c.name,
    borough_code: c.code,
    fill: scoreToColour(c.x),
    isLabelled: labelSet.has(c.code),
  }));
}

interface CustomDotProps {
  cx?: number;
  cy?: number;
  payload?: Point;
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

interface CustomTooltipProps {
  active?: boolean;
  payload?: { payload: Point }[];
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <div
      className="rounded px-3 py-2 text-xs font-mono"
      style={{
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        border: "1px solid #1e293b",
      }}
    >
      <div
        className="text-slate-200 font-medium mb-1"
        style={{ letterSpacing: "0.1em" }}
      >
        {d.borough_name.toUpperCase()}
      </div>
      <div className="flex justify-between gap-4 text-slate-400">
        <span>CityScan composite</span>
        <span style={{ color: d.fill }}>{d.x.toFixed(1)}</span>
      </div>
      <div className="flex justify-between gap-4 text-slate-400">
        <span>ONS Health Index</span>
        <span className="text-white">{d.y.toFixed(1)}</span>
      </div>
    </div>
  );
}

export default function HealthIndexValidation({
  boroughs,
  healthIndex,
}: HealthIndexValidationProps) {
  const data = useMemo(
    () => buildPoints(boroughs, healthIndex),
    [boroughs, healthIndex],
  );

  // Pearson r + R² + regression line + largest-residual borough — all live.
  const stats = useMemo(() => {
    if (data.length < 5) return null;
    const xs = data.map((p) => p.x);
    const ys = data.map((p) => p.y);
    const r = pearson(xs, ys);
    if (r === null || !Number.isFinite(r)) return null;
    const n = data.length;
    let sx = 0, sy = 0, sxy = 0, sxx = 0;
    for (const p of data) {
      sx += p.x; sy += p.y; sxy += p.x * p.y; sxx += p.x * p.x;
    }
    const mx = sx / n;
    const my = sy / n;
    const denom = sxx - n * mx * mx;
    const slope = denom === 0 ? 0 : (sxy - n * mx * my) / denom;
    const intercept = my - slope * mx;

    // Largest-|residual| borough to surface in caption.
    let topResid = data[0];
    let topResidValue = 0;
    for (const p of data) {
      const resid = p.y - (slope * p.x + intercept);
      if (Math.abs(resid) > Math.abs(topResidValue)) {
        topResidValue = resid;
        topResid = p;
      }
    }

    return { r, slope, intercept, n, topResid, topResidValue };
  }, [data]);

  const year = data.length > 0
    ? Object.values(healthIndex).find((h) => h.year !== null)?.year ?? null
    : null;

  if (data.length === 0 || stats === null) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-xs font-mono">
        No Health Index data available for validation
      </div>
    );
  }

  const xMin = Math.min(...data.map((d) => d.x));
  const xMax = Math.max(...data.map((d) => d.x));
  const trendData = [
    { x: xMin, y: stats.slope * xMin + stats.intercept },
    { x: xMax, y: stats.slope * xMax + stats.intercept },
  ];

  const r = stats.r;
  const rSquared = r * r;
  // For the agreement summary we anchor the verbal label to r² (shared
  // variance), not |r|. r = 0.5 sounds "strong" via Cohen's |r|
  // thresholds but only accounts for 25% of cross-borough variance —
  // calling that "strongly agrees" overclaims. Cut-offs (in r²): <0.05
  // weak, 0.05–0.20 moderate, 0.20–0.50 substantial, ≥0.50 very strong.
  const r2Word =
    rSquared < 0.05 ? "weakly"
    : rSquared < 0.20 ? "moderately"
    : rSquared < 0.50 ? "substantially"
    : "very strongly";
  const yMin = Math.min(...data.map((d) => d.y));
  const yMax = Math.max(...data.map((d) => d.y));

  return (
    <div>
      {/* Title row — title left, R² + n right */}
      <div className="flex items-baseline justify-between mb-3">
        <div
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: "#0ea5e9" }}
        >
          VALIDATION · vs ONS Health Index
        </div>
        <div
          className="text-[10px] font-mono"
          style={{ color: "#64748b", letterSpacing: "0.05em" }}
        >
          r = {r >= 0 ? "+" : "−"}{Math.abs(r).toFixed(3)} · r² ={" "}
          {rSquared.toFixed(3)} · n = {stats.n}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <XAxis
            type="number"
            dataKey="x"
            name="CityScan composite"
            domain={[Math.floor(xMin) - 2, Math.ceil(xMax) + 2]}
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
            label={{
              value: "← Lower CityScan          composite          Higher CityScan →",
              position: "bottom",
              offset: 12,
              style: {
                fill: "#64748b",
                fontSize: 10,
                fontFamily: "var(--font-jetbrains, monospace)",
              },
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="ONS Health Index"
            domain={[Math.floor(yMin) - 2, Math.ceil(yMax) + 2]}
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
            label={{
              value: "ONS Health Index",
              angle: -90,
              position: "insideLeft",
              offset: 0,
              style: {
                fill: "#64748b",
                fontSize: 10,
                fontFamily: "var(--font-jetbrains, monospace)",
              },
            }}
          />
          <Tooltip content={<CustomTooltip />} cursor={false} />
          <Scatter data={data} shape={<CustomDot />} />
          <Scatter
            data={trendData}
            line={{
              stroke: "rgba(14, 165, 233, 0.4)",
              strokeWidth: 1.5,
              strokeDasharray: "6 3",
            }}
            shape={() => <></>}
            legendType="none"
            isAnimationActive={false}
          />
        </ScatterChart>
      </ResponsiveContainer>

      {/* Caption — fully data-derived. Leads with the planner-relevant
          trust signal (CityScan agrees with ONS); stats and overlap caveat
          follow. */}
      <div
        className="mt-2 text-[11px] font-mono px-3 py-2 rounded"
        style={{
          backgroundColor: "rgba(14, 165, 233, 0.05)",
          border: "1px solid rgba(14, 165, 233, 0.15)",
          color: "#94a3b8",
          lineHeight: 1.55,
        }}
      >
        CityScan {r2Word} agrees with the ONS Health Index{year ? ` ${year}` : ""}{" "}
        across {stats.n} LTLAs (r² = {rSquared.toFixed(2)}, Pearson r = {r >= 0 ? "+" : "−"}
        {Math.abs(r).toFixed(2)}; {Math.round(rSquared * 100)}% of cross-borough
        variance shared). Cross-sectional snapshot of today's CityScan
        composite against the static 2021 Health Index — convergent validity,
        not a forecast and not a like-for-like benchmark (the Health Index is
        annual; CityScan refreshes hourly). Largest divergence:{" "}
        {stats.topResid.borough_name} ({stats.topResidValue >= 0 ? "+" : "−"}
        {Math.abs(stats.topResidValue).toFixed(1)} pts vs CityScan's predicted
        value). The Health Index draws on outcomes CityScan does not feed
        (life expectancy, mortality, mental-health prevalence); some
        environmental inputs overlap (air pollution, green space), so this is
        convergent validity rather than a fully independent benchmark.
      </div>
    </div>
  );
}
