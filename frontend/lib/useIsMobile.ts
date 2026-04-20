"use client";

import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT_PX = 768;

/**
 * Returns true when the viewport is narrower than MOBILE_BREAKPOINT_PX.
 *
 * Designed for hard-gating the main dashboard on phones — CityScan is a
 * desktop tool (thermal SVG map, slide-out Recharts panels, Doctor chat)
 * and the mobile experience is intentionally not supported. Returns
 * `null` on the first render (pre-hydration) so callers can skip the
 * flash-of-wrong-content.
 */
export function useIsMobile(): boolean | null {
  const [isMobile, setIsMobile] = useState<boolean | null>(null);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`);
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);

  return isMobile;
}
