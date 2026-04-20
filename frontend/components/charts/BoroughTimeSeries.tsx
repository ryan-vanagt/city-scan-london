"use client";

/**
 * BoroughTimeSeries — Recharts line chart showing organ score history
 * for a selected borough over 7/14/30 day windows.
 *
 * Four coloured lines represent the time-varying organ systems:
 *   Air (Lungs) #3b82f6, Transit (Arteries) #ef4444,
 *   Sentiment (Brain) #a855f7, Immune #22c55e.
 *
 * Skin (green space) is rendered as a static badge beneath the chart
 * rather than a line, because the underlying GLA Green Cover data is a
 * yearly static snapshot — plotting it on a daily chart implies movement
 * that doesn't exist.
 */

import { useState, useEffect, useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import type { BoroughScore } from "@/lib/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Time-varying organs — plotted as lines on the chart.
// Skin (green space) is excluded: it derives from a yearly static snapshot
// (GLA Green Cover 2024), so a time-series line is misleading. The current
// raw + access-weighted values are shown in a static badge beneath the chart.
const ORGANS = [
  { key: "air_score", name: "Air (Lungs)", colour: "#3b82f6" },
  { key: "transit_score", name: "Transit (Arteries)", colour: "#ef4444" },
  { key: "sentiment_score", name: "Sentiment (Brain)", colour: "#a855f7" },
  { key: "immune_score", name: "Immune", colour: "#22c55e" },
] as const;

const DAY_OPTIONS = [7, 14, 30] as const;

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TrendPoint {
  timestamp: string;
  air_score: number | null;
  transit_score: number | null;
  sentiment_score: number | null;
  immune_score: number | null;
  green_space_score: number | null;
  green_space_access_score: number | null;
  composite_score: number | null;
}

interface TrendResponse {
  borough_code: string;
  days: number;
  data_points: number;
  trend: TrendPoint[];
}

export interface BoroughTimeSeriesProps {
  boroughs: BoroughScore[];
  initialBoroughCode?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Pick the borough with the lowest composite score as default. */
function lowestCompositeCode(boroughs: BoroughScore[]): string {
  let best: BoroughScore | null = null;
  for (const b of boroughs) {
    if (b.composite_score === null) continue;
    if (!best || b.composite_score < (best.composite_score ?? Infinity)) {
      best = b;
    }
  }
  return best?.borough_code ?? boroughs[0]?.borough_code ?? "";
}

/** Format a timestamp string for the X axis. */
function formatTick(ts: string): string {
  const d = new Date(ts);
  const month = d.toLocaleString("en-GB", { month: "short" });
  return `${month} ${d.getDate()}`;
}

/* ------------------------------------------------------------------ */
/*  Custom Tooltip                                                     */
/* ------------------------------------------------------------------ */

interface TooltipPayloadEntry {
  dataKey: string;
  value: number | null;
  color: string;
  name: string;
}

interface CustomTooltipProps {
  active?: boolean;
  label?: string;
  payload?: TooltipPayloadEntry[];
}

function CustomTooltip({ active, label, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0 || !label) return null;

  const d = new Date(label);
  const formatted = d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
  });

  return (
    <div
      className="rounded px-3 py-2 text-xs font-mono"
      style={{
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        border: "1px solid #1e293b",
      }}
    >
      <div
        className="text-slate-300 font-medium mb-1"
        style={{ letterSpacing: "0.05em" }}
      >
        {formatted} · daily mean
      </div>
      {ORGANS.map((organ) => {
        const entry = payload.find((p) => p.dataKey === organ.key);
        const value = entry?.value;
        return (
          <div
            key={organ.key}
            className="flex justify-between gap-4 text-slate-400"
          >
            <span>{organ.name}</span>
            <span style={{ color: organ.colour }}>
              {value !== null && value !== undefined
                ? (Math.round(value * 10) / 10).toFixed(1)
                : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function BoroughTimeSeries({
  boroughs,
  initialBoroughCode,
}: BoroughTimeSeriesProps) {
  const defaultCode = useMemo(
    () => initialBoroughCode ?? lowestCompositeCode(boroughs),
    [initialBoroughCode, boroughs],
  );

  const [selectedCode, setSelectedCode] = useState(defaultCode);
  const [days, setDays] = useState<(typeof DAY_OPTIONS)[number]>(7);
  const [loading, setLoading] = useState(true);
  const [trend, setTrend] = useState<TrendResponse | null>(null);

  // Look up borough name for dropdown display
  const boroughName = useMemo(() => {
    const b = boroughs.find((b) => b.borough_code === selectedCode);
    return b?.borough_name ?? selectedCode;
  }, [boroughs, selectedCode]);

  // Selected borough's static Skin scores (rendered as a badge, not a line)
  const skinScores = useMemo(() => {
    const b = boroughs.find((b) => b.borough_code === selectedCode);
    return {
      coverage: b?.green_space_score ?? null,
      access: b?.green_space_access_score ?? null,
    };
  }, [boroughs, selectedCode]);

  /* Fetch trend data ------------------------------------------------ */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const name = boroughs.find(
      (b) => b.borough_code === selectedCode,
    )?.borough_name;
    if (!name) {
      setLoading(false);
      return;
    }

    const encoded = encodeURIComponent(name);
    fetch(`${API_BASE}/borough/${encoded}/trend?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: TrendResponse) => {
        if (!cancelled) {
          setTrend(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTrend(null);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCode, days, boroughs]);

  /* Chart data ------------------------------------------------------ */
  // Hourly trend points get aggregated to daily means per organ. The chart
  // window is 7–30 days; hourly resolution on that scale is visually noisy
  // and the useful signal is structural day-to-day movement, not minute-to-
  // minute readings. Trade-off: transit disruption spikes within a day get
  // smoothed out. We accept this for readability — live state is available
  // via the header/tooltip elsewhere.
  const chartData = useMemo(() => {
    if (!trend?.trend) return [];
    const groups = new Map<string, TrendPoint[]>();
    for (const p of trend.trend) {
      const day = p.timestamp.slice(0, 10); // YYYY-MM-DD
      if (!groups.has(day)) groups.set(day, []);
      groups.get(day)!.push(p);
    }
    const mean = (xs: (number | null)[]): number | null => {
      const vs = xs.filter((x): x is number => x !== null);
      return vs.length === 0 ? null : vs.reduce((a, b) => a + b, 0) / vs.length;
    };
    const days = [...groups.keys()].sort();
    return days.map((day) => {
      const pts = groups.get(day)!;
      return {
        // Use the day's first timestamp for x-axis sorting + tooltip label
        ts: pts[0].timestamp,
        day,
        air_score: mean(pts.map((p) => p.air_score)),
        transit_score: mean(pts.map((p) => p.transit_score)),
        sentiment_score: mean(pts.map((p) => p.sentiment_score)),
        immune_score: mean(pts.map((p) => p.immune_score)),
        composite_score: mean(pts.map((p) => p.composite_score)),
      };
    });
  }, [trend]);

  const insufficient = !loading && (trend === null || (trend?.data_points ?? 0) < 2);

  /* Sorted borough list for dropdown -------------------------------- */
  const sortedBoroughs = useMemo(
    () => [...boroughs].sort((a, b) => a.borough_name.localeCompare(b.borough_name)),
    [boroughs],
  );

  /* ---------------------------------------------------------------- */
  return (
    <div>
      {/* Title */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: "#0ea5e9" }}
      >
        ORGAN HISTORY
      </div>

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {/* Borough dropdown */}
        <select
          value={selectedCode}
          onChange={(e) => setSelectedCode(e.target.value)}
          className="rounded px-2 py-1 text-xs font-mono outline-none cursor-pointer"
          style={{
            backgroundColor: "#1e293b",
            color: "#94a3b8",
            border: "1px solid #334155",
          }}
        >
          {sortedBoroughs.map((b) => (
            <option key={b.borough_code} value={b.borough_code}>
              {b.borough_name}
            </option>
          ))}
        </select>

        {/* Day toggle buttons */}
        <div className="flex gap-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className="rounded px-2 py-1 text-xs font-mono transition-colors cursor-pointer"
              style={{
                backgroundColor: days === d ? "#0ea5e9" : "#1e293b",
                color: days === d ? "#020617" : "#64748b",
                border: `1px solid ${days === d ? "#0ea5e9" : "#334155"}`,
              }}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center h-[280px] text-slate-500 text-xs font-mono">
          Loading trend data...
        </div>
      )}

      {/* Insufficient data */}
      {insufficient && (
        <div className="flex items-center justify-center h-[280px] text-slate-500 text-xs font-mono text-center px-4">
          Insufficient data — trends populate as the pipeline runs hourly
        </div>
      )}

      {/* Chart */}
      {!loading && !insufficient && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart
            data={chartData}
            margin={{ top: 5, right: 20, bottom: 5, left: 10 }}
          >
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis
              dataKey="ts"
              tickFormatter={(ts: string) => formatTick(ts)}
              tick={{
                fill: "#64748b",
                fontSize: 10,
                fontFamily: "var(--font-jetbrains, monospace)",
              }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
            />
            <YAxis
              domain={[0, 100]}
              tick={{
                fill: "#64748b",
                fontSize: 10,
                fontFamily: "var(--font-jetbrains, monospace)",
              }}
              axisLine={{ stroke: "#475569" }}
              tickLine={{ stroke: "#475569" }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{
                fontSize: 10,
                fontFamily: "var(--font-jetbrains, monospace)",
                color: "#94a3b8",
              }}
            />
            {ORGANS.map((organ) => (
              <Line
                key={organ.key}
                type="monotone"
                dataKey={organ.key}
                name={organ.name}
                stroke={organ.colour}
                strokeWidth={2}
                dot={{ r: 3, fill: organ.colour }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* Static Skin (green space) badge — rendered BELOW the chart because
          it derives from a yearly snapshot, not a time series. Placed under
          the chart/legend so it reads as a supplementary static value rather
          than competing with the line-chart's moving signals. */}
      {(skinScores.coverage !== null || skinScores.access !== null) && (
        <div
          className="flex items-center gap-3 mt-3 text-xs font-mono"
          style={{
            backgroundColor: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 4,
            padding: "6px 10px",
            color: "#94a3b8",
          }}
        >
          <span className="font-semibold" style={{ color: "#cbd5e1" }}>
            Skin (green space)
          </span>
          <span className="text-slate-500">·</span>
          <span>
            Coverage:{" "}
            <span style={{ color: "#84cc16" }}>
              {skinScores.coverage !== null
                ? skinScores.coverage.toFixed(1)
                : "—"}
            </span>
          </span>
          <span className="text-slate-500">·</span>
          <span>
            Access-weighted:{" "}
            <span style={{ color: "#84cc16" }}>
              {skinScores.access !== null ? skinScores.access.toFixed(1) : "—"}
            </span>
          </span>
          <span className="ml-auto text-slate-500 italic">
            GLA 2024 static snapshot
          </span>
        </div>
      )}
    </div>
  );
}
