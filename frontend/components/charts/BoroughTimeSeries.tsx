"use client";

/**
 * BoroughTimeSeries — Recharts line chart showing organ score history
 * for a selected borough over 7/14/30 day windows.
 *
 * Five coloured lines represent the five organ systems:
 *   Air (Lungs) #3b82f6, Transit (Arteries) #ef4444,
 *   Sentiment (Brain) #a855f7, Immune #22c55e, Green Space (Skin) #84cc16
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

const ORGANS = [
  { key: "air_score", name: "Air (Lungs)", colour: "#3b82f6" },
  { key: "transit_score", name: "Transit (Arteries)", colour: "#ef4444" },
  { key: "sentiment_score", name: "Sentiment (Brain)", colour: "#a855f7" },
  { key: "immune_score", name: "Immune", colour: "#22c55e" },
  { key: "green_space_score", name: "Green Space (Skin)", colour: "#84cc16" },
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
    hour: "2-digit",
    minute: "2-digit",
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
        {formatted}
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
  const chartData = useMemo(() => {
    if (!trend?.trend) return [];
    return trend.trend.map((p) => ({
      ...p,
      // Keep raw timestamp for tooltip, formatted for axis
      ts: p.timestamp,
    }));
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
    </div>
  );
}
