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

import { useMemo, useState } from "react";
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
  strengthWord,
  type OrganKey,
  type ImdDomainKey,
} from "@/lib/stats";

interface EquityPatternsProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, {
    imd_rank: number;
    name: string;
    domains?: Record<string, { rank: number; score?: number }>;
  }>;
}

interface DomainOption {
  key: ImdDomainKey;
  label: string;     // dropdown text
  short: string;     // chart-title snippet
}

/**
 * Curated domain options. "Income" is highlighted as the leakage-free
 * baseline (no input overlap with CityScan); "Barriers" is the housing &
 * service-access lens (London-specific stressor); the others are honest
 * comparisons we don't want to hide.
 */
const DOMAIN_OPTIONS: DomainOption[] = [
  { key: "overall",    label: "Overall IMD",                          short: "IMD deprivation rank" },
  { key: "income",     label: "Income (leakage-free)",                short: "IMD income rank" },
  { key: "barriers",   label: "Housing & service barriers",           short: "IMD barriers rank" },
  { key: "living",     label: "Living environment",                   short: "IMD living rank" },
  { key: "health",     label: "Health & disability",                  short: "IMD health rank" },
  { key: "crime",      label: "Crime",                                short: "IMD crime rank" },
  { key: "employment", label: "Employment",                           short: "IMD employment rank" },
  { key: "education",  label: "Education",                            short: "IMD education rank" },
];

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
  const [domain, setDomain] = useState<ImdDomainKey>("overall");
  const domainOption =
    DOMAIN_OPTIONS.find((o) => o.key === domain) ?? DOMAIN_OPTIONS[0];

  const data: BarDatum[] = useMemo(() => {
    return ORGANS.map((o) => {
      const corr = organImdCorrelation(boroughs, deprivation, o.key, domain);
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
  }, [boroughs, deprivation, domain]);

  // Flip order so the strongest signal is visually at the top
  const chartData = useMemo(() => [...data].reverse(), [data]);

  // Caption is fully derived from computed values — strongest and weakest
  // organs are picked live, descriptors come from strengthWord(|r|), so
  // prose can never contradict the data even if signals shift.
  // Filter excludes both null AND NaN/Infinity to avoid sentiment-style
  // zero-variance artifacts leaking into the caption.
  const captionParts = useMemo(() => {
    const ranked = data
      .filter((d) => d.rRaw !== null && Number.isFinite(d.rRaw))
      .map((d) => ({
        label: d.label,
        r: d.rRaw as number,
      }))
      .sort((a, b) => Math.abs(b.r) - Math.abs(a.r));
    if (ranked.length < 2) return null;
    const strongest = ranked[0];
    const weakest = ranked[ranked.length - 1];
    return { strongest, weakest };
  }, [data]);

  // Per-borough divergence vs the chosen-domain-predicted composite.
  // Driving organ also recomputes against the same domain.
  const divergence = useMemo(
    () => boroughDivergence(boroughs, deprivation, 5, domain),
    [boroughs, deprivation, domain],
  );

  return (
    <div>
      {/* Title row — title left, domain dropdown right */}
      <div className="flex items-center justify-between mb-3 gap-3">
        <div
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: "#0ea5e9" }}
        >
          EQUITY PATTERNS · |r| vs {domainOption.short}
        </div>
        <select
          value={domain}
          onChange={(e) => setDomain(e.target.value as ImdDomainKey)}
          className="text-[10px] font-mono px-2 py-1 rounded border bg-transparent"
          style={{
            color: "#94a3b8",
            borderColor: "#1e293b",
            backgroundColor: "rgba(15, 23, 42, 0.6)",
          }}
          aria-label="IMD domain"
        >
          {DOMAIN_OPTIONS.map((opt) => (
            <option
              key={opt.key}
              value={opt.key}
              style={{ backgroundColor: "#0f172a", color: "#cbd5e1" }}
            >
              {opt.label}
            </option>
          ))}
        </select>
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

      {/* Caption — strongest/weakest organs computed live; descriptors derive
          from strengthWord(|r|) so the prose tracks the data automatically. */}
      {captionParts && (
        <div
          className="mt-2 text-[11px] font-mono px-3 py-2 rounded"
          style={{
            backgroundColor: "rgba(14, 165, 233, 0.05)",
            border: "1px solid rgba(14, 165, 233, 0.15)",
            color: "#94a3b8",
            lineHeight: 1.55,
          }}
        >
          Strongest gradient: {captionParts.strongest.label} (r=
          {formatR(captionParts.strongest.r)},{" "}
          {strengthWord(captionParts.strongest.r)}). Weakest:{" "}
          {captionParts.weakest.label} (r={formatR(captionParts.weakest.r)},{" "}
          {strengthWord(captionParts.weakest.r)}).
        </div>
      )}

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
