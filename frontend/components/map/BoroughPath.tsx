"use client";

/**
 * Individual borough SVG path with thermal colouring.
 *
 * Single <path> element — xrayMode changes fill/opacity via CSS transition.
 * Glow and pulse only enabled after effectsReady=true (delayed after transition).
 */

import { useMemo } from "react";
import type { BoroughScore, MetricFilter, TrendInfo } from "@/lib/types";
import { scoreToColour, glowIntensity, pulseDuration, XRAY_BLUE } from "@/lib/colours";

interface BoroughPathProps {
  borough: BoroughScore;
  pathData: string;
  isHovered: boolean;
  isSelected: boolean;
  isAnyHovered: boolean;
  metricFilter: MetricFilter;
  xrayMode?: boolean;
  effectsReady?: boolean;
  trend?: TrendInfo | null;
  centroidX?: number;
  centroidY?: number;
  onHover: () => void;
  onLeave: () => void;
}

function getActiveScore(
  borough: BoroughScore,
  filter: MetricFilter
): number | null {
  if (filter === null) return borough.composite_score;
  // When filtering by green space, colour by the ward-pop-weighted access metric
  // (falling back to raw coverage if access is missing). This surfaces the
  // methodology improvement on the thermal map itself.
  if (filter === "green_space_score") {
    return borough.green_space_access_score ?? borough.green_space_score;
  }
  return borough[filter];
}

export default function BoroughPath({
  borough,
  pathData,
  isHovered,
  isSelected,
  isAnyHovered,
  metricFilter,
  xrayMode,
  effectsReady,
  trend,
  centroidX,
  centroidY,
  onHover,
  onLeave,
}: BoroughPathProps) {
  const score = getActiveScore(borough, metricFilter);
  const thermalColour = useMemo(() => scoreToColour(score), [score]);
  const glow = useMemo(() => glowIntensity(score), [score]);
  const pulse = useMemo(() => `${pulseDuration(score)}s`, [score]);
  const glowPx = glow * 25;

  const fill = xrayMode ? XRAY_BLUE : thermalColour;
  const isElevated = !xrayMode && (isHovered || isSelected);
  const isDimmed = !xrayMode && isAnyHovered && !isElevated;

  const opacity = xrayMode ? 0.3 : isDimmed ? 0.3 : 1;

  // Glow + brightness: ONLY when effectsReady (well after transition completes).
  // This prevents any filter computation during the fill/opacity transition.
  let filter = "none";
  if (effectsReady) {
    if (isDimmed) {
      filter = "brightness(0.5)";
    } else if (isElevated) {
      filter = `brightness(1.2) drop-shadow(0 0 ${glowPx * 1.5}px ${thermalColour})`;
    } else {
      filter = `drop-shadow(0 0 ${glowPx}px ${thermalColour})`;
    }
  }

  // Pulse: only when effects are ready and not dimmed
  const showPulse = effectsReady && !isDimmed && !xrayMode;

  return (
    <>
      <path
        d={pathData}
        fill={fill}
        stroke="#020617"
        strokeWidth={1.2}
        className={showPulse ? "borough-pulse" : ""}
        style={{
          "--pulse-duration": pulse,
          opacity,
          filter,
          transform: isElevated ? "scale(1.05)" : "scale(1)",
          transformOrigin: "center",
          transformBox: "fill-box",
          willChange: effectsReady ? "auto" : "fill, opacity, filter, transform",
          transition: "fill 1.5s ease-out, opacity 1s ease-out, transform 300ms ease-out, filter 1s ease-out",
        } as React.CSSProperties}
        onMouseEnter={xrayMode ? undefined : onHover}
        onMouseLeave={xrayMode ? undefined : onLeave}
        data-borough-code={borough.borough_code}
        aria-label={`${borough.borough_name}: ${score !== null ? Math.round(score) + "/100" : "N/A"}`}
      />
    </>
  );
}
