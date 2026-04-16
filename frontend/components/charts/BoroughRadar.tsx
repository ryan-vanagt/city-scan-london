"use client";

/**
 * BoroughRadar — Recharts radar chart comparing two London boroughs
 * side by side across five health dimensions.
 *
 * Axes: AIR, TRANSIT, SENTIMENT, IMMUNE, GREEN SPACE.
 * Two overlapping polygons at 40% fill opacity (cyan + orange).
 * Dropdowns default to lowest and highest composite score boroughs.
 */

import { useState, useMemo } from "react";
import {
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend,
  Tooltip,
} from "recharts";
import type { BoroughScore } from "@/lib/types";

const AXES = [
  { key: "air_score" as const, label: "AIR" },
  { key: "transit_score" as const, label: "TRANSIT" },
  { key: "sentiment_score" as const, label: "SENTIMENT" },
  { key: "immune_score" as const, label: "IMMUNE" },
  { key: "green_space_score" as const, label: "GREEN SPACE" },
];

interface BoroughRadarProps {
  boroughs: BoroughScore[];
}

function safe(value: number | null): number {
  return value ?? 0;
}

function buildRadarData(a: BoroughScore, b: BoroughScore) {
  return AXES.map(({ key, label }) => ({
    axis: label,
    [a.borough_code]: safe(a[key]),
    [b.borough_code]: safe(b[key]),
  }));
}

interface RadarTooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}

function RadarTooltip({ active, payload, label }: RadarTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div
      className="rounded px-3 py-2 text-xs font-mono"
      style={{
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        border: "1px solid #1e293b",
      }}
    >
      <div className="text-slate-300 font-medium mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex justify-between gap-4 text-slate-400">
          <span>{p.name}</span>
          <span style={{ color: p.color }}>{p.value.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

export default function BoroughRadar({ boroughs }: BoroughRadarProps) {
  const sorted = useMemo(() => {
    const valid = boroughs.filter((b) => b.composite_score !== null);
    return [...valid].sort(
      (a, b) => (a.composite_score ?? 0) - (b.composite_score ?? 0),
    );
  }, [boroughs]);

  const defaultA = sorted.length > 0 ? sorted[0].borough_code : "";
  const defaultB =
    sorted.length > 1 ? sorted[sorted.length - 1].borough_code : "";

  const [codeA, setCodeA] = useState(defaultA);
  const [codeB, setCodeB] = useState(defaultB);

  const boroughMap = useMemo(() => {
    const map = new Map<string, BoroughScore>();
    for (const b of boroughs) map.set(b.borough_code, b);
    return map;
  }, [boroughs]);

  const selectedA = boroughMap.get(codeA);
  const selectedB = boroughMap.get(codeB);

  const data =
    selectedA && selectedB ? buildRadarData(selectedA, selectedB) : null;

  const selectStyle: React.CSSProperties = {
    backgroundColor: "#1e293b",
    color: "#e2e8f0",
    border: "1px solid #334155",
  };

  return (
    <div>
      {/* Title */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: "#0ea5e9" }}
      >
        BOROUGH COMPARISON
      </div>

      {/* Dropdowns */}
      <div className="flex gap-3 mb-4">
        <select
          value={codeA}
          onChange={(e) => setCodeA(e.target.value)}
          className="rounded px-2 py-1 text-xs font-mono flex-1"
          style={selectStyle}
        >
          <option value="">Select borough...</option>
          {sorted.map((b) => (
            <option key={b.borough_code} value={b.borough_code}>
              {b.borough_name}
            </option>
          ))}
        </select>

        <select
          value={codeB}
          onChange={(e) => setCodeB(e.target.value)}
          className="rounded px-2 py-1 text-xs font-mono flex-1"
          style={selectStyle}
        >
          <option value="">Select borough...</option>
          {sorted.map((b) => (
            <option key={b.borough_code} value={b.borough_code}>
              {b.borough_name}
            </option>
          ))}
        </select>
      </div>

      {/* Chart or placeholder */}
      {!data || !selectedA || !selectedB ? (
        <div className="flex items-center justify-center h-64 text-slate-500 text-xs font-mono">
          Select two boroughs to compare
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
              <PolarGrid stroke="#334155" />
              <PolarAngleAxis
                dataKey="axis"
                tick={{
                  fill: "#94a3b8",
                  fontSize: 10,
                  fontFamily: "var(--font-jetbrains, monospace)",
                }}
              />
              <PolarRadiusAxis
                domain={[0, 100]}
                tick={false}
                axisLine={false}
              />
              <Tooltip content={<RadarTooltip />} />
              <Radar
                name={selectedA.borough_name}
                dataKey={selectedA.borough_code}
                stroke="#0ea5e9"
                fill="#0ea5e9"
                fillOpacity={0.4}
              />
              <Radar
                name={selectedB.borough_name}
                dataKey={selectedB.borough_code}
                stroke="#f97316"
                fill="#f97316"
                fillOpacity={0.4}
              />
              <Legend
                wrapperStyle={{
                  fontSize: 11,
                  fontFamily: "var(--font-jetbrains, monospace)",
                  color: "#94a3b8",
                }}
              />
            </RadarChart>
          </ResponsiveContainer>

          {/* Composite score legend */}
          <div className="flex justify-center gap-6 mt-2 text-xs font-mono">
            <span style={{ color: "#0ea5e9" }}>
              {selectedA.borough_name}: {safe(selectedA.composite_score).toFixed(1)}
            </span>
            <span style={{ color: "#f97316" }}>
              {selectedB.borough_name}: {safe(selectedB.composite_score).toFixed(1)}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
