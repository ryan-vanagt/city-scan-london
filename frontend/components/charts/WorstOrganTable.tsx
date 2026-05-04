"use client";

/**
 * WorstOrganTable — Sortable table showing each borough's weakest organ.
 *
 * For each borough, finds the organ with the lowest non-null score and
 * displays it alongside the second-worst. Sorted by worst score ascending
 * (most critical first). Filterable by organ type.
 */

import { useState, useMemo } from "react";
import type { BoroughScore, BoroughScoreQuality } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";
import QualityDot from "@/components/ui/QualityDot";

const ORGAN_MAP: Record<string, string> = {
  air_score: "LUNGS",
  transit_score: "ARTERIES",
  sentiment_score: "BRAIN",
  immune_score: "IMMUNE",
  green_space_score: "SKIN",
};

const SCORE_KEYS = Object.keys(ORGAN_MAP) as (keyof typeof ORGAN_MAP)[];

interface OrganEntry {
  key: string;
  label: string;
  score: number;
}

interface RowData {
  borough_code: string;
  borough_name: string;
  worst: OrganEntry;
  secondWorst: OrganEntry | null;
}

function extractWorstOrgans(b: BoroughScore): RowData | null {
  const entries: OrganEntry[] = [];
  for (const key of SCORE_KEYS) {
    const val = b[key as keyof BoroughScore] as number | null;
    if (val !== null && val !== undefined) {
      entries.push({ key, label: ORGAN_MAP[key], score: val });
    }
  }
  if (entries.length === 0) return null;

  entries.sort((a, b) => a.score - b.score);

  return {
    borough_code: b.borough_code,
    borough_name: b.borough_name,
    worst: entries[0],
    secondWorst: entries.length > 1 ? entries[1] : null,
  };
}

interface WorstOrganTableProps {
  boroughs: BoroughScore[];
  scoreQuality?: Record<string, BoroughScoreQuality>;
}

export default function WorstOrganTable({ boroughs, scoreQuality }: WorstOrganTableProps) {
  const [filter, setFilter] = useState<string>("ALL");

  const rows = useMemo(() => {
    const result: RowData[] = [];
    for (const b of boroughs) {
      const row = extractWorstOrgans(b);
      if (row) result.push(row);
    }
    result.sort((a, b) => a.worst.score - b.worst.score);
    return result;
  }, [boroughs]);

  const filtered = useMemo(() => {
    if (filter === "ALL") return rows;
    return rows.filter((r) => r.worst.label === filter);
  }, [rows, filter]);

  const organOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const r of rows) seen.add(r.worst.label);
    return Array.from(seen).sort();
  }, [rows]);

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-500 text-xs font-mono">
        No organ data available
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
        CRITICAL ORGANS
      </div>

      {/* Filter dropdown */}
      <div className="mb-2">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs px-2 py-1 rounded cursor-pointer outline-none"
          style={{
            backgroundColor: "rgba(15, 23, 42, 0.95)",
            border: "1px solid #1e293b",
            color: "#94a3b8",
            fontFamily: "var(--font-jetbrains, monospace)",
            fontSize: "10px",
            letterSpacing: "0.05em",
          }}
        >
          <option value="ALL">ALL ORGANS</option>
          {organOptions.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div
        className="overflow-y-auto"
        style={{ maxHeight: "300px" }}
      >
        <table className="w-full" style={{ borderCollapse: "collapse" }}>
          <thead
            className="sticky top-0"
            style={{ backgroundColor: "#0f172a", zIndex: 1 }}
          >
            <tr
              style={{
                borderBottom: "1px solid #1e293b",
              }}
            >
              {[
              { key: "borough", label: "BOROUGH" },
              { key: "worst", label: "WORST ORGAN" },
              { key: "score1", label: "SCORE" },
              { key: "second", label: "2ND WORST" },
              { key: "score2", label: "SCORE" },
            ].map((h) => (
                  <th
                    key={h.key}
                    className="text-left py-1.5 px-2"
                    style={{
                      color: "#64748b",
                      fontSize: "9px",
                      fontFamily: "var(--font-jetbrains, monospace)",
                      letterSpacing: "0.1em",
                      fontWeight: 600,
                    }}
                  >
                    {h.label}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row, i) => (
              <tr
                key={row.borough_name}
                style={{
                  borderBottom: "1px solid #1e293b",
                  backgroundColor:
                    i % 2 === 1 ? "rgba(30, 41, 59, 0.25)" : "transparent",
                }}
              >
                {/* Borough name */}
                <td
                  className="py-1 px-2"
                  style={{
                    color: "#e2e8f0",
                    fontSize: "11px",
                    letterSpacing: "0.05em",
                    textTransform: "uppercase",
                    whiteSpace: "nowrap",
                  }}
                >
                  {row.borough_name}
                </td>

                {/* Worst organ label */}
                <td
                  className="py-1 px-2"
                  style={{
                    color: "#94a3b8",
                    fontSize: "10px",
                    fontFamily: "var(--font-jetbrains, monospace)",
                    letterSpacing: "0.05em",
                  }}
                >
                  {row.worst.label}
                </td>

                {/* Worst score + quality dot */}
                <td
                  className="py-1 px-2"
                  style={{
                    color: scoreToColour(row.worst.score),
                    fontSize: "11px",
                    fontFamily: "var(--font-jetbrains, monospace)",
                    fontWeight: 600,
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {Math.round(row.worst.score * 10) / 10}
                    <QualityDot
                      quality={scoreQuality?.[row.borough_code]?.organs[row.worst.key]}
                    />
                  </span>
                </td>

                {/* 2nd worst organ label */}
                <td
                  className="py-1 px-2"
                  style={{
                    color: "#94a3b8",
                    fontSize: "10px",
                    fontFamily: "var(--font-jetbrains, monospace)",
                    letterSpacing: "0.05em",
                  }}
                >
                  {row.secondWorst ? row.secondWorst.label : "\u2014"}
                </td>

                {/* 2nd worst score + quality dot */}
                <td
                  className="py-1 px-2"
                  style={{
                    color: row.secondWorst
                      ? scoreToColour(row.secondWorst.score)
                      : "#64748b",
                    fontSize: "11px",
                    fontFamily: "var(--font-jetbrains, monospace)",
                    fontWeight: 600,
                  }}
                >
                  {row.secondWorst ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      {Math.round(row.secondWorst.score * 10) / 10}
                      <QualityDot
                        quality={scoreQuality?.[row.borough_code]?.organs[row.secondWorst.key]}
                      />
                    </span>
                  ) : (
                    "\u2014"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
