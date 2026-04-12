/**
 * Thermal gradient colour system for borough health scores.
 *
 * Maps 0-100 health scores to a thermal imaging palette:
 *   Blue (healthy/cold) → Cyan → Green → Yellow → Orange → Red (critical/hot)
 */

interface ColourStop {
  score: number;
  r: number;
  g: number;
  b: number;
}

const THERMAL_STOPS: ColourStop[] = [
  { score: 0, r: 239, g: 68, b: 68 },    // #ef4444 — red (critical)
  { score: 30, r: 249, g: 115, b: 22 },   // #f97316 — orange (hot)
  { score: 45, r: 132, g: 204, b: 22 },   // #84cc16 — green-yellow (warming)
  { score: 60, r: 6, g: 182, b: 212 },    // #06b6d4 — cyan (moderate)
  { score: 75, r: 37, g: 99, b: 235 },    // #2563eb — blue (cool)
  { score: 100, r: 30, g: 58, b: 138 },   // #1e3a8a — deep blue (cold)
];

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

/**
 * Convert a health score (0-100) to a thermal gradient colour.
 * 100 = healthiest (deep blue/cold), 0 = critical (red/hot).
 */
export function scoreToColour(score: number | null): string {
  if (score === null) return "rgb(100, 116, 139)"; // slate-500 for unknown (rgb to match thermal format)

  const clamped = Math.max(0, Math.min(100, score));

  // Find the two stops we're between
  for (let i = 0; i < THERMAL_STOPS.length - 1; i++) {
    const lo = THERMAL_STOPS[i];
    const hi = THERMAL_STOPS[i + 1];
    if (clamped >= lo.score && clamped <= hi.score) {
      const t = (clamped - lo.score) / (hi.score - lo.score);
      const r = lerp(lo.r, hi.r, t);
      const g = lerp(lo.g, hi.g, t);
      const b = lerp(lo.b, hi.b, t);
      return `rgb(${r}, ${g}, ${b})`;
    }
  }

  // Fallback (shouldn't reach here)
  return "#1e3a8a";
}

/**
 * Get the glow intensity based on how extreme the score is.
 * Scores far from 50 (very healthy or very unhealthy) glow more.
 */
export function glowIntensity(score: number | null): number {
  if (score === null) return 0;
  const distance = Math.abs(score - 50) / 50; // 0 at 50, 1 at 0 or 100
  return 0.1 + distance * 0.8; // 0.1 at 50, 0.9 at 0 or 100
}

/**
 * Get the pulse duration based on health score.
 * Healthy = slow pulse (resting heartbeat), unhealthy = fast pulse (stressed).
 */
export function pulseDuration(score: number | null): number {
  if (score === null) return 2.0;
  if (score >= 80) return 1.5;  // Healthy — normal steady heartbeat
  if (score >= 50) return 2.0;  // OK — slightly slower
  if (score >= 30) return 3.0;  // Unhealthy — slow, laboured
  return 4.0;                   // Critical — barely alive, fading
}

/** X-ray scan blue for the bulletin landing mode. */
export const XRAY_BLUE = "#0ea5e9";

/** X-ray blue as rgb() — matches scoreToColour() output format so CSS
 *  fill transitions interpolate smoothly between X-ray and thermal. */
export const XRAY_BLUE_RGB = "rgb(14, 165, 233)";

/** Background colours */
export const BG_PAGE = "#020617";
export const BG_CARD = "#0f172a";
export const BG_BORDER = "#1e293b";
