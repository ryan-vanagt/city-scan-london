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

/**
 * Map |r| to a verbal magnitude word using conventional stats thresholds.
 * Used to keep on-screen captions in lockstep with computed correlation
 * strength — every adjective in our captions derives from this function so
 * prose can never contradict the data.
 *
 * Thresholds match the standard: |r|<0.1 negligible, 0.1–0.3 weak, 0.3–0.5
 * moderate, 0.5–0.7 strong, ≥0.7 very strong.
 */
export function strengthWord(r: number): "barely" | "weakly" | "moderately" | "strongly" | "very strongly" {
  const a = Math.abs(r);
  if (a < 0.1) return "barely";
  if (a < 0.3) return "weakly";
  if (a < 0.5) return "moderately";
  if (a < 0.7) return "strongly";
  return "very strongly";
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

export interface BoroughDivergence {
  borough_code: string;
  borough_name: string;
  residual: number;            // composite − IMD-predicted composite (in score points)
  predicted: number;
  actual: number;
  driving_organ: OrganKey | null;
  driving_organ_label: string; // e.g. "Lungs", "Immune", "Skin"
}

interface SimpleRegression {
  slope: number;
  intercept: number;
  predict: (x: number) => number;
}

function leastSquares(xs: number[], ys: number[]): SimpleRegression | null {
  const n = xs.length;
  if (n < 5) return null;
  let sx = 0, sy = 0, sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) {
    sx += xs[i]; sy += ys[i]; sxy += xs[i] * ys[i]; sxx += xs[i] * xs[i];
  }
  const mx = sx / n;
  const my = sy / n;
  const denom = sxx - n * mx * mx;
  if (denom === 0) return null;
  const slope = (sxy - n * mx * my) / denom;
  const intercept = my - slope * mx;
  return { slope, intercept, predict: (x) => slope * x + intercept };
}

const DIVERGENCE_ORGANS: { key: OrganKey; label: string }[] = [
  { key: "air_score", label: "Lungs" },
  { key: "transit_score", label: "Arteries" },
  { key: "sentiment_score", label: "Brain" },
  { key: "immune_score", label: "Immune" },
  { key: "green_space_score", label: "Skin" },
];

/**
 * Per-borough divergence between actual composite score and what IMD rank
 * alone would predict, using **leave-one-out (LOO) residuals**: for each
 * borough, the regression line is refit on the other 32 boroughs, so the
 * borough being scored never contributed to its own predicted value.
 *
 * Removes the in-sample-fitting bias where a borough at extreme IMD rank
 * (high leverage) pulls the line toward itself, understating its true
 * deviation. Compared to in-sample fitting, top-5 ranking is stable but
 * magnitudes for high-leverage boroughs (extreme ranks) become more honest.
 *
 * The "driving organ" is the organ whose own LOO residual is largest in
 * magnitude AND has the same sign as the composite LOO residual — i.e. the
 * organ pulling the borough away from its IMD-predicted health in the
 * direction of the divergence.
 *
 * Returns up to topN entries sorted by |residual| descending. Returns []
 * if fewer than 6 boroughs have both an IMD rank and a composite score
 * (LOO requires ≥6 so each fit has ≥5 pairs).
 */
export function boroughDivergence(
  boroughs: BoroughScore[],
  deprivation: Record<string, { imd_rank: number; name: string }>,
  topN: number = 5,
): BoroughDivergence[] {
  const compositePairs = boroughs
    .filter((b) => deprivation[b.borough_code] && b.composite_score !== null)
    .map((b) => ({
      code: b.borough_code,
      name: b.borough_name,
      imd: deprivation[b.borough_code].imd_rank,
      actual: b.composite_score as number,
    }));
  if (compositePairs.length < 6) return [];

  // Per-organ pair arrays — built once, sliced per-borough during LOO loop.
  const organPairs: Partial<Record<OrganKey, { code: string; imd: number; actual: number }[]>> = {};
  for (const org of DIVERGENCE_ORGANS) {
    organPairs[org.key] = boroughs
      .filter((b) => deprivation[b.borough_code] && b[org.key] !== null)
      .map((b) => ({
        code: b.borough_code,
        imd: deprivation[b.borough_code].imd_rank,
        actual: b[org.key] as number,
      }));
  }

  const all: BoroughDivergence[] = [];
  for (let i = 0; i < compositePairs.length; i++) {
    const p = compositePairs[i];

    // LOO composite prediction: fit on all-but-i, predict i.
    const otherComp = compositePairs.filter((_, j) => j !== i);
    const compReg = leastSquares(
      otherComp.map((o) => o.imd),
      otherComp.map((o) => o.actual),
    );
    if (!compReg) continue;
    const predicted = compReg.predict(p.imd);
    const residual = p.actual - predicted;

    // LOO organ residuals — refit each organ's line excluding this borough,
    // pick the largest-magnitude organ residual matching the composite sign.
    let drivingKey: OrganKey | null = null;
    let drivingMag = 0;
    for (const org of DIVERGENCE_ORGANS) {
      const arr = organPairs[org.key];
      if (!arr) continue;
      const idx = arr.findIndex((a) => a.code === p.code);
      if (idx === -1) continue;
      const others = arr.filter((_, j) => j !== idx);
      const reg = leastSquares(
        others.map((o) => o.imd),
        others.map((o) => o.actual),
      );
      if (!reg) continue;
      const orgResid = arr[idx].actual - reg.predict(arr[idx].imd);
      if (Math.sign(orgResid) !== Math.sign(residual)) continue;
      const mag = Math.abs(orgResid);
      if (mag > drivingMag) {
        drivingMag = mag;
        drivingKey = org.key;
      }
    }
    const drivingLabel = drivingKey
      ? DIVERGENCE_ORGANS.find((o) => o.key === drivingKey)!.label
      : "—";

    all.push({
      borough_code: p.code,
      borough_name: p.name,
      residual,
      predicted,
      actual: p.actual,
      driving_organ: drivingKey,
      driving_organ_label: drivingLabel,
    });
  }

  return all
    .sort((a, b) => Math.abs(b.residual) - Math.abs(a.residual))
    .slice(0, topN);
}
