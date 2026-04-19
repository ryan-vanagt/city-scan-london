"use client";

/**
 * Interactive SVG thermal map of London's 33 boroughs.
 *
 * Each borough is a BoroughPath coloured by its health score.
 * Manages hover/selection state and renders a tooltip on hover.
 */

import { useState, useCallback, useRef, useMemo } from "react";
import type { BoroughScore, MetricFilter, TrendInfo } from "@/lib/types";
import { BOROUGH_PATHS, BOROUGH_PATH_MAP, VIEW_BOX_WIDTH, VIEW_BOX_HEIGHT } from "@/lib/geo";
import BoroughPath from "./BoroughPath";
import BoroughTooltip from "./BoroughTooltip";

interface LondonMapProps {
  boroughs: BoroughScore[];
  deprivation?: Record<string, any>;
  trends?: Record<string, TrendInfo>;
  metricFilter: MetricFilter;
  selectedBorough: string | null;
  xrayMode?: boolean;
  effectsReady?: boolean;
  onBoroughHover: (code: string | null) => void;
}

export default function LondonMap({
  boroughs,
  deprivation,
  trends,
  metricFilter,
  selectedBorough,
  xrayMode,
  effectsReady,
  onBoroughHover,
}: LondonMapProps) {
  const [hoveredCode, setHoveredCode] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({
    x: 0,
    y: 0,
  });
  const svgRef = useRef<SVGSVGElement>(null);

  /** Build a lookup from borough code to BoroughScore. */
  const scoreMap = useMemo(() => new Map(boroughs.map((b) => [b.borough_code, b])), [boroughs]);

  const hoveredBorough = hoveredCode ? scoreMap.get(hoveredCode) : null;
  const isAnyHovered = hoveredCode !== null || selectedBorough !== null;

  const handleHover = useCallback(
    (code: string) => {
      setHoveredCode(code);
      onBoroughHover(code);

      // Position tooltip at borough centroid (in SVG coordinates mapped to DOM).
      const geo = BOROUGH_PATH_MAP.get(code);
      if (geo && svgRef.current) {
        const svg = svgRef.current;
        const rect = svg.getBoundingClientRect();
        const scaleX = rect.width / VIEW_BOX_WIDTH;
        const scaleY = rect.height / VIEW_BOX_HEIGHT;
        setTooltipPos({
          x: geo.centroidX * scaleX,
          y: geo.centroidY * scaleY,
        });
      }
    },
    [onBoroughHover]
  );

  const handleLeave = useCallback(() => {
    setHoveredCode(null);
    onBoroughHover(null);
  }, [onBoroughHover]);

  return (
    <div className="relative w-full" style={{ aspectRatio: `${VIEW_BOX_WIDTH}/${VIEW_BOX_HEIGHT}` }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
        className="w-full h-full"
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="Interactive London borough health map"
      >
        <g>
          {BOROUGH_PATHS.map((geo) => {
            const borough = scoreMap.get(geo.code) ?? {
              borough_code: geo.code,
              borough_name: geo.name,
              timestamp: null,
              air_score: null,
              transit_score: null,
              sentiment_score: null,
              immune_score: null,
              green_space_score: null,
              green_space_access_score: null,
              composite_score: null,
            };
            return (
              <BoroughPath
                key={geo.code}
                borough={borough}
                pathData={geo.path}
                isHovered={hoveredCode === geo.code}
                isSelected={selectedBorough === geo.code}
                isAnyHovered={isAnyHovered}
                metricFilter={metricFilter}
                xrayMode={xrayMode}
                effectsReady={effectsReady}
                trend={trends?.[geo.code] ?? null}
                centroidX={geo.centroidX}
                centroidY={geo.centroidY}
                onHover={() => handleHover(geo.code)}
                onLeave={handleLeave}
              />
            );
          })}
        </g>

        {/* Trend arrows — composite only, hidden when metric filter active */}
        {effectsReady && !xrayMode && !metricFilter && trends && BOROUGH_PATHS.map((geo) => {
          const trend = trends[geo.code];
          if (!trend?.direction || trend.direction === "stable") return null;
          return (
            <g
              key={`trend-${geo.code}`}
              transform={`translate(${geo.centroidX}, ${geo.centroidY})`}
              className="pointer-events-none"
              opacity={0.9}
            >
              {trend.direction === "declining" ? (
                <>
                  <line x1={0} y1={-5} x2={0} y2={4} stroke="white" strokeWidth={1.5} strokeLinecap="round" />
                  <polyline points="-3,1 0,5 3,1" fill="none" stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
                  <animateTransform attributeName="transform" type="translate" values={`${geo.centroidX},${geo.centroidY}; ${geo.centroidX},${geo.centroidY + 3}; ${geo.centroidX},${geo.centroidY}`} dur="1s" repeatCount="indefinite" />
                </>
              ) : (
                <>
                  <line x1={0} y1={5} x2={0} y2={-4} stroke="white" strokeWidth={1.5} strokeLinecap="round" />
                  <polyline points="-3,-1 0,-5 3,-1" fill="none" stroke="white" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
                  <animateTransform attributeName="transform" type="translate" values={`${geo.centroidX},${geo.centroidY}; ${geo.centroidX},${geo.centroidY - 3}; ${geo.centroidX},${geo.centroidY}`} dur="1s" repeatCount="indefinite" />
                </>
              )}
            </g>
          );
        })}
      </svg>

      {/* Subtle vignette — slightly darker edges */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse at center, transparent 55%, rgba(2,6,23,0.4) 100%)",
        }}
      />

      {effectsReady && !xrayMode && (
        <div
          className="absolute bottom-2 left-2 flex items-center gap-3 text-[9px] font-mono"
          style={{ color: "#64748b" }}
        >
          <span className="text-white">↑ Improving (7d)</span>
          <span className="text-white">↓ Declining (7d)</span>
        </div>
      )}

      {hoveredBorough && (
        <BoroughTooltip
          borough={hoveredBorough}
          position={tooltipPos}
          metricFilter={metricFilter}
          imdRank={deprivation?.[hoveredBorough.borough_code]?.imd_rank ?? null}
        />
      )}
    </div>
  );
}
