"use client";

/**
 * Static X-ray blue London map for the landing / bulletin page.
 *
 * All 33 boroughs filled in uniform X-ray blue (#0ea5e9) with no
 * interactivity. A scan-line animation sweeps across the map.
 */

import { BOROUGH_PATHS, VIEW_BOX_WIDTH, VIEW_BOX_HEIGHT } from "@/lib/geo";
import { XRAY_BLUE } from "@/lib/colours";

export default function XRayMap() {
  return (
    <div
      className="relative w-full max-w-[500px] mx-auto"
      style={{ aspectRatio: `${VIEW_BOX_WIDTH}/${VIEW_BOX_HEIGHT}` }}
    >
      {/* SVG map */}
      <svg
        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
        className="w-full h-full"
        preserveAspectRatio="xMidYMid meet"
        aria-label="London boroughs X-ray map"
      >
        {BOROUGH_PATHS.map((geo) => (
          <path
            key={geo.code}
            d={geo.path}
            fill={XRAY_BLUE}
            fillOpacity={0.3}
            stroke={XRAY_BLUE}
            strokeWidth={0.5}
            strokeOpacity={0.6}
          />
        ))}
      </svg>

      {/* Scan line overlay */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute left-0 w-full h-[2px] scan-line"
          style={{
            background: `linear-gradient(90deg, transparent, ${XRAY_BLUE}80, transparent)`,
            boxShadow: `0 0 20px ${XRAY_BLUE}60`,
          }}
        />
      </div>
    </div>
  );
}
