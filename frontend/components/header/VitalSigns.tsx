"use client";

/**
 * Vital signs header bar showing 4 metrics + overall composite score.
 *
 * Each metric shows a label, an animated EKG line, and a numerical score.
 * All labels and EKG lines are X-ray blue; only scores use thermal colours.
 * Clicking a metric toggles the map's colour filter.
 */

import { useMemo } from "react";
import { HeartPulse } from "lucide-react";
import type { BoroughScore, LondonScore, MetricFilter } from "@/lib/types";
import { scoreToColour, XRAY_BLUE } from "@/lib/colours";
import EkgLine from "./EkgLine";

interface VitalSignsProps {
  londonScore: LondonScore;
  hoveredBorough: BoroughScore | null;
  metricFilter: MetricFilter;
  onMetricClick: (metric: MetricFilter) => void;
}

interface MetricConfig {
  key: "air_score" | "transit_score" | "sentiment_score" | "immune_score";
  label: string;
  ekgVariant: "air" | "transit" | "sentiment" | "immune";
}

const METRICS: MetricConfig[] = [
  { key: "air_score", label: "AIR QUALITY", ekgVariant: "air" },
  { key: "transit_score", label: "TRANSIT", ekgVariant: "transit" },
  { key: "sentiment_score", label: "SENTIMENT", ekgVariant: "sentiment" },
  { key: "immune_score", label: "IMMUNE", ekgVariant: "immune" },
];

function formatScore(value: number | null): string {
  if (value === null) return "--";
  return Math.round(value).toString();
}

/** Abbreviate long borough names to fit the header. */
function abbreviateName(name: string): string {
  if (name.length <= 12) return name.toUpperCase();
  const abbrevs: Record<string, string> = {
    "Barking and Dagenham": "B & D",
    "Hammersmith and Fulham": "H & F",
    "Kensington and Chelsea": "K & C",
    "Kingston upon Thames": "KINGSTON",
    "Richmond upon Thames": "RICHMOND",
    "Tower Hamlets": "TWR HAMLETS",
    "Waltham Forest": "WALTHAM F.",
  };
  return (abbrevs[name] ?? name.slice(0, 12)).toUpperCase();
}

export default function VitalSigns({
  londonScore,
  hoveredBorough,
  metricFilter,
  onMetricClick,
}: VitalSignsProps) {
  const activeScores = useMemo(() => {
    if (hoveredBorough) {
      return {
        air_score: hoveredBorough.air_score,
        transit_score: hoveredBorough.transit_score,
        sentiment_score: hoveredBorough.sentiment_score,
        immune_score: hoveredBorough.immune_score,
        composite_score: hoveredBorough.composite_score,
      };
    }
    return {
      air_score: londonScore.air_score,
      transit_score: londonScore.transit_score,
      sentiment_score: londonScore.sentiment_score,
      immune_score: londonScore.immune_score,
      composite_score: londonScore.composite_score,
    };
  }, [londonScore, hoveredBorough]);

  // Heart shows filtered metric score when isolating, composite when showing all
  const heartScore = metricFilter ? activeScores[metricFilter] : activeScores.composite_score;
  const heartColour = scoreToColour(heartScore);

  return (
    <header
      className="sticky top-0 z-40 flex items-center justify-between px-4 py-2 border-b"
      style={{ backgroundColor: "#020617", borderColor: "#1e293b" }}
    >
      {/* Context label */}
      <div className="hidden md:flex items-center gap-2 mr-4 min-w-[100px]">
        {hoveredBorough ? (
          <span
            className="text-[11px] text-slate-400 font-medium whitespace-nowrap"
            style={{ letterSpacing: "0.1em" }}
            title={hoveredBorough.borough_name}
          >
            {abbreviateName(hoveredBorough.borough_name)}
          </span>
        ) : (
          <span className="text-[11px] text-slate-500" style={{ letterSpacing: "0.1em" }}>
            LONDON
          </span>
        )}
      </div>

      {/* Metrics row with "ALL" reset */}
      <div className="flex items-center gap-2 md:gap-4 flex-1 justify-center">
        {/* ALL button — always visible, resets filter */}
        <button
          onClick={() => onMetricClick(null)}
          aria-pressed={metricFilter === null}
          className="text-[10px] font-medium px-2 py-1 rounded-md transition-all duration-300 ease-out hover:bg-slate-800/50"
          style={{
            color: metricFilter === null ? XRAY_BLUE : "#64748b",
            letterSpacing: "0.1em",
            background: metricFilter === null ? "rgba(14, 165, 233, 0.1)" : "transparent",
          }}
        >
          ALL
        </button>

        {METRICS.map(({ key, label, ekgVariant }) => {
          const score = activeScores[key];
          const scoreColour = scoreToColour(score);
          const isActive = metricFilter === key;

          return (
            <button
              key={key}
              onClick={() => onMetricClick(isActive ? null : key)}
              aria-pressed={isActive}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md transition-all duration-300 ease-out hover:bg-[rgba(14,165,233,0.15)] cursor-pointer"
              style={isActive ? { background: "rgba(14, 165, 233, 0.15)" } : undefined}
              aria-label={`Filter map by ${label}`}
            >
              <span
                className="text-[10px] font-medium hidden sm:inline"
                style={{ color: XRAY_BLUE, letterSpacing: "0.1em" }}
              >
                {label}
              </span>
              <EkgLine variant={ekgVariant} colour={XRAY_BLUE} />
              <span
                className="font-mono text-sm font-bold w-[3ch] text-right transition-all duration-300"
                style={{ color: scoreColour }}
              >
                {formatScore(score)}
              </span>
            </button>
          );
        })}
      </div>

      {/* Overall composite — HeartPulse icon, pulsing, thermal-coloured */}
      <div className="flex items-center gap-2 ml-4">
        <HeartPulse
          size={20}
          fill="currentColor"
          className="stethoscope-pulse"
          style={{
            color: heartColour,
            filter: `drop-shadow(0 0 8px ${heartColour}80)`,
            transition: "color 0.3s ease-out, filter 0.3s ease-out",
          }}
        />
        <span
          className="font-mono text-lg font-bold w-[3ch] text-right transition-all duration-300"
          style={{ color: heartColour }}
        >
          {formatScore(heartScore)}
        </span>
      </div>
    </header>
  );
}
