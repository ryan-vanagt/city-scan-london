/**
 * Shared statistical helpers for analytics computations.
 *
 * Kept minimal — no external stats library. Pure-math helpers used by the
 * analytics panel's correlation-insight block and the equity-patterns chart.
 */

import type { BoroughScore } from "./types";

/**
 * Pearson correlation coefficient between two paired arrays.
 *
 * Returns null if fewer than 5 paired non-null values exist or if either
 * array has zero variance.
 */
export function pearson(
  xs: (number | null)[],
  ys: (number | null)[],
): number | null {
  const pairs: [number, number][] = [];
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] !== null && ys[i] !== null) {
      pairs.push([xs[i]!, ys[i]!]);
    }
  }
  if (pairs.length < 5) return null;
  const n = pairs.length;
  let sx = 0, sy = 0, sxy = 0, sx2 = 0, sy2 = 0;
  for (const [x, y] of pairs) {
    sx += x; sy += y; sxy += x * y; sx2 += x * x; sy2 += y * y;
  }
  const num = n * sxy - sx * sy;
  const den = Math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy));
  if (den === 0) return null;
  return num / den;
}

export type OrganKey =
  | "air_score"
  | "air_quality_modelled_score"
  | "transit_score"
  | "sentiment_score"
  | "immune_score"
  | "green_space_score"
  | "green_space_access_score"
  | "composite_score";

export interface OrganCorrelation {
  organ: OrganKey;
  r: number | null;   // null if fewer than 5 pairs or zero variance (e.g. sentiment)
  n: number;          // number of matched (borough, imd) pairs with non-null score
}

/**
 * For a given organ, compute Pearson r vs IMD rank across all boroughs that
 * have both an IMD rank and a non-null score. Zero-variance signals (sentiment)
 * return r=null explicitly rather than NaN.
 */
export function organImdCorrelation(
  boroughs: BoroughScore[],
  deprivation: Record<string, { imd_rank: number }>,
  organ: OrganKey,
): OrganCorrelation {
  const pairs = boroughs
    .filter((b) => deprivation[b.borough_code] && b[organ] !== null)
    .map((b) => ({ imd: deprivation[b.borough_code].imd_rank, score: b[organ] as number }));
  if (pairs.length < 5) {
    return { organ, r: null, n: pairs.length };
  }
  const r = pearson(pairs.map((p) => p.imd), pairs.map((p) => p.score));
  return { organ, r, n: pairs.length };
}
