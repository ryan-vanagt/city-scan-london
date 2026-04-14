"use client";

/**
 * Interactive SVG thermal map of London's 33 boroughs.
 *
 * Each borough is a BoroughPath coloured by its health score.
 * Manages hover/selection state and renders a tooltip on hover.
 */

import { useState, useCallback, useRef, useMemo } from "react";
import type { BoroughScore, MetricFilter } from "@/lib/types";
import { BOROUGH_PATHS, BOROUGH_PATH_MAP, VIEW_BOX_WIDTH, VIEW_BOX_HEIGHT } from "@/lib/geo";
import BoroughPath from "./BoroughPath";
import BoroughTooltip from "./BoroughTooltip";

interface LondonMapProps {
  boroughs: BoroughScore[];
  metricFilter: MetricFilter;
  selectedBorough: string | null;
  xrayMode?: boolean;
  effectsReady?: boolean;
  onBoroughHover: (code: string | null) => void;
}

export default function LondonMap({
  boroughs,
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
                onHover={() => handleHover(geo.code)}
                onLeave={handleLeave}
              />
            );
          })}
        </g>
      </svg>

      {/* Subtle vignette — slightly darker edges */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse at center, transparent 55%, rgba(2,6,23,0.4) 100%)",
        }}
      />

      {hoveredBorough && (
        <BoroughTooltip
          borough={hoveredBorough}
          position={tooltipPos}
          metricFilter={metricFilter}
        />
      )}
    </div>
  );
}
