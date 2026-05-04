"use client";

/**
 * EquityPatterns — horizontal bar chart of |r| between each organ score
 * and IMD deprivation rank across the 33 boroughs.
 *
 * Surfaces the three-finding narrative: green space has a meaningful
 * deprivation gradient, modelled air quality shows a London-specific
 * inversion (weaker signal, rendered as an outlier story in the caption),
 * and most other organs are effectively IMD-independent. The chart is
 * computed at runtime from already-fetched boroughs + deprivation data so
 * it stays fresh as live signals drift.
 */

import { useMemo } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Cell,
  Tooltip,
  ReferenceLine,
} from "recharts";
import type { BoroughScore } from "@/lib/types";
import {
  organImdCorrelation,
  boroughDivergence,
  type OrganKey,
} from "@/lib/stats";

interface EquityPatternsProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
}

interface OrganDef {
  key: OrganKey;
  label: string;
  footnote: string;
}

/**
 * Display order is top-to-bottom (chart renders reversed so we list from
 * "expected high signal" to "expected low signal").
 */
const ORGANS: OrganDef[] = [
  {
    key: "green_space_access_score",
    label: "Green (access-weighted)",
    footnote: "ward-pop weighted, static GLA 2024",
  },
  {
    key: "green_space_score",
    label: "Green (coverage)",
    footnote: "raw borough-level, static GLA 2024",
  },
  {
    key: "air_quality_modelled_score",
    label: "Air (modelled)",
    footnote: "LAEI 2022 structural baseline, 33/33 coverage",
  },
  {
    key: "transit_score",
    label: "Transit",
    footnote: "live tube-status snapshot; noisy day-to-day",
  },
  {
    key: "immune_score",
    label: "Crime + A&E",
    footnote: "log-transformed per-capita; multi-driver in London",
  },
  {
    key: "air_score",
    label: "Air (live)",
    footnote: "OpenAQ sensor readings; sparse (24/33)",
  },
  {
    key: "sentiment_score",
    label: "Public sentiment",
    footnote: "London-wide signal; does not vary by borough",
  },
];

/**
 * Signal-strength colour bands.
 * Green ≥ 0.3 (meaningful), Amber 0.15–0.30 (suggestive), Grey < 0.15.
 * `null` r (e.g. sentiment) renders as a dashed grey stub.
 */
function colourForR(r: number | null): string {
  if (r === null) return "#475569"; // flat/undefined — slate
  const mag = Math.abs(r);
  if (mag >= 0.3) return "#22c55e";  // green
  if (mag >= 0.15) return "#f59e0b"; // amber
  return "#64748b";                   // grey
}

function formatR(r: number | null): string {
  if (r === null) return "—";
  const sign = r >= 0 ? "+" : "−";
  return `${sign}${Math.abs(r).toFixed(2)}`;
}

interface BarDatum {
  label: string;
  magR: number;       // bar length — clamped to [0, 0.5]
  rRaw: number | null;
  rLabel: string;     // pre-formatted "±x.xx (n=N)" for the bar label
  footnote: string;
  n: number;
}

export default function EquityPatterns({
  boroughs,
  deprivation,
}: EquityPatternsProps) {
  const data: BarDatum[] = useMemo(() => {
    return ORGANS.map((o) => {
      const corr = organImdCorrelation(boroughs, deprivation, o.key);
      const magR =
        corr.r === null ? 0.01 : Math.min(0.5, Math.abs(corr.r));
      return {
        label: o.label,
        magR,
        rRaw: corr.r,
        rLabel: formatR(corr.r),  // short label — n moves to tooltip only
        footnote: o.footnote,
        n: corr.n,
      };
    });
  }, [boroughs, deprivation]);

  // Flip order so the strongest signal is visually at the top
  const chartData = useMemo(() => [...data].reverse(), [data]);

  // Pull live r-values for each organ so the caption reflects current data,
  // not stale hardcoded numbers. Formatting falls back to "—" if null.
  const captionValues = useMemo(() => {
    const byOrgan = Object.fromEntries(
      data.map((d, i) => [ORGANS[i].key, d.rRaw]),
    );
    return {
      green: formatR(byOrgan["green_space_access_score"] ?? null),
      airModelled: formatR(byOrgan["air_quality_modelled_score"] ?? null),
      crime: formatR(byOrgan["immune_score"] ?? null),
    };
  }, [data]);

  // Per-borough divergence vs IMD-predicted composite. Surfaces named
  // outliers — boroughs whose health is better/worse than IMD alone would
  // predict — alongside the organ pulling them away from prediction.
  const divergence = useMemo(
    () => boroughDivergence(boroughs, deprivation, 5),
    [boroughs, deprivation],
  );

  return (
    <div>
      {/* Title */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: "#0ea5e9" }}
      >
        EQUITY PATTERNS · |r| vs IMD deprivation rank
      </div>

      <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 30)}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 5, right: 60, bottom: 5, left: 20 }}
        >
          <XAxis
            type="number"
            domain={[0, 0.5]}
            ticks={[0, 0.15, 0.3, 0.5]}
            tick={{ fill: "#64748b", fontSize: 10, fontFamily: "var(--font-jetbrains, monospace)" }}
            axisLine={{ stroke: "#475569" }}
            tickLine={{ stroke: "#475569" }}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fill: "#cbd5e1", fontSize: 11 }}
            axisLine={{ stroke: "#475569" }}
            tickLine={false}
            width={160}
          />
          <Tooltip
            cursor={false}
            allowEscapeViewBox={{ x: false, y: false }}
            wrapperStyle={{ outline: "none", zIndex: 50 }}
            content={({ active, payload }) => {
              if (!active || !payload || payload.length === 0) return null;
              const d = payload[0].payload as BarDatum;
              return (
                <div
                  className="rounded px-3 py-2 text-xs font-mono"
                  style={{
                    backgroundColor: "rgba(15, 23, 42, 0.95)",
                    border: "1px solid #1e293b",
                    color: "#94a3b8",
                    maxWidth: 240,
                    whiteSpace: "normal",
                    lineHeight: 1.35,
                  }}
                >
                  <div className="text-slate-200 font-semibold mb-1">{d.label}</div>
                  <div>r = {formatR(d.rRaw)} · n = {d.n}</div>
                  <div className="text-slate-500 mt-1">{d.footnote}</div>
                </div>
              );
            }}
          />
          <ReferenceLine x={0.3} stroke="#22c55e" strokeDasharray="3 3" strokeOpacity={0.35} />
          <ReferenceLine x={0.15} stroke="#f59e0b" strokeDasharray="3 3" strokeOpacity={0.35} />
          <Bar
            dataKey="magR"
            isAnimationActive={false}
            barSize={14}
            activeBar={false}
            label={{
              position: "right",
              fill: "#94a3b8",
              fontSize: 10,
              fontFamily: "var(--font-jetbrains, monospace)",
              dataKey: "rLabel",
            }}
          >
            {chartData.map((d) => (
              <Cell
                key={d.label}
                fill={colourForR(d.rRaw)}
                fillOpacity={d.rRaw === null ? 0.25 : 0.6}
                stroke={d.rRaw === null ? "#475569" : undefined}
                strokeDasharray={d.rRaw === null ? "4 3" : undefined}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Short data-aware caption — r-values pulled live; specific-borough
          narrative + significance analysis lives in README, not here. */}
      <div
        className="mt-2 text-[11px] font-mono px-3 py-2 rounded"
        style={{
          backgroundColor: "rgba(14, 165, 233, 0.05)",
          border: "1px solid rgba(14, 165, 233, 0.15)",
          color: "#94a3b8",
          lineHeight: 1.55,
        }}
      >
        Green (r={captionValues.green}) tracks deprivation · Modelled air
        (r={captionValues.airModelled}) weaker, inverted in central London ·
        Crime (r={captionValues.crime}) IMD-independent.
      </div>

      {/* Per-borough divergence — named outliers vs IMD-predicted composite.
          Sits below the organ-level chart as the borough-level finding. */}
      {divergence.length > 0 && (
        <div
          className="mt-3 px-3 py-3 rounded"
          style={{
            backgroundColor: "rgba(14, 165, 233, 0.05)",
            border: "1px solid rgba(14, 165, 233, 0.15)",
          }}
        >
          <div
            className="text-[10px] font-semibold uppercase tracking-wider mb-2"
            style={{ color: "#0ea5e9" }}
          >
            TOP 5 UNEXPECTED · score vs IMD-predicted (LOO)
          </div>
          <div className="space-y-1">
            {divergence.map((d) => {
              const positive = d.residual >= 0;
              const sign = positive ? "+" : "−";
              const colour = positive ? "#22c55e" : "#ef4444";
              return (
                <div
                  key={d.borough_code}
                  className="flex items-center text-[11px] font-mono"
                  style={{ lineHeight: 1.5 }}
                >
                  <div className="flex-1 text-slate-200 truncate pr-2">
                    {d.borough_name}
                  </div>
                  <div
                    className="w-14 text-right tabular-nums"
                    style={{ color: colour }}
                  >
                    {sign}
                    {Math.abs(d.residual).toFixed(1)}
                  </div>
                  <div className="w-20 text-right text-slate-400 pl-3">
                    {d.driving_organ_label}
                  </div>
                </div>
              );
            })}
          </div>
          <div
            className="text-[10px] mt-2 leading-relaxed"
            style={{ color: "#64748b", lineHeight: 1.55 }}
          >
            Composite vs IMD-predicted regression residual.{" "}
            <span style={{ color: "#22c55e" }}>+</span> healthier than expected ·{" "}
            <span style={{ color: "#ef4444" }}>−</span> more stressed than
            expected. Driver = organ deviating most from its own IMD-predicted
            value in the same direction.
          </div>
        </div>
      )}
    </div>
  );
}
