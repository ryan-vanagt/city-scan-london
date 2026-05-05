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
  // Variance terms — guard against zero AND near-zero (floating-point error
  // when one variable is constant, e.g. sentiment is identical across all
  // 33 boroughs; sums of identical floats don't cancel exactly to 0).
  const xVar = n * sx2 - sx * sx;
  const yVar = n * sy2 - sy * sy;
  const VAR_EPSILON = 1e-9;
  if (xVar < VAR_EPSILON || yVar < VAR_EPSILON) return null;
  const den = Math.sqrt(xVar * yVar);
  const r = (n * sxy - sx * sy) / den;
  return Number.isFinite(r) ? r : null;
}

/**
 * Map |r| to a verbal magnitude word using conventional behavioural-science
 * effect-size thresholds (Cohen-style: ~0.1 small, ~0.3 medium, ~0.5 large).
 * "barely" / "weakly" / "moderately" / "strongly" / "very strongly" are
 * descriptive labels for the on-screen caption — they describe the
 * magnitude of association, not statistical significance, and they make
 * no claim about causation. Used to keep prose in lockstep with the
 * computed value so a caption can never contradict its data.
 *
 * Thresholds: |r|<0.1 → "barely"; 0.1–0.3 → "weakly"; 0.3–0.5 →
 * "moderately"; 0.5–0.7 → "strongly"; ≥0.7 → "very strongly". These are
 * conventional cut-offs for descriptive labelling; the underlying r is
 * also displayed in the bar label so the reader can override the verbal
 * descriptor with the numeric value.
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
 * IMD domain selector. "overall" uses the headline `imd_rank`; the other
 * keys point at sub-domain ranks under `domains.{key}.rank` in the API
 * payload from /boroughs/deprivation.
 *
 * Four sub-domains — income, employment, education, barriers — share no
 * inputs with any CityScan organ. They are INPUT-leakage-free, so any
 * correlation we measure against them is not a tautology of shared
 * measurement. Causal-pathway confounding still applies (e.g. income
 * affects health via mechanisms the score doesn't directly observe), but
 * that is interpretive, not arithmetic. The other three domains (health,
 * crime, living) overlap with CityScan organs at the input level and are
 * disclosed accordingly.
 */
export type ImdDomainKey =
  | "overall"
  | "income"
  | "employment"
  | "education"
  | "health"
  | "crime"
  | "barriers"
  | "living";

interface DeprivationLike {
  imd_rank: number;
  domains?: Record<string, { rank: number; score?: number }>;
}

function getDomainRank(dep: DeprivationLike | undefined, domain: ImdDomainKey): number | null {
  if (!dep) return null;
  if (domain === "overall") return dep.imd_rank;
  const d = dep.domains?.[domain];
  return typeof d?.rank === "number" ? d.rank : null;
}

/**
 * For a given organ, compute Pearson r vs the chosen IMD domain rank across
 * all boroughs that have both a rank and a non-null score. Zero-variance
 * signals (sentiment) return r=null explicitly rather than NaN.
 *
 * `domain` defaults to "overall" so existing callers stay backward-compatible.
 */
export function organImdCorrelation(
  boroughs: BoroughScore[],
  deprivation: Record<string, DeprivationLike>,
  organ: OrganKey,
  domain: ImdDomainKey = "overall",
): OrganCorrelation {
  const pairs: { imd: number; score: number }[] = [];
  for (const b of boroughs) {
    const dep = deprivation[b.borough_code];
    if (!dep || b[organ] === null) continue;
    const rank = getDomainRank(dep, domain);
    if (rank === null) continue;
    pairs.push({ imd: rank, score: b[organ] as number });
  }
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

// Sentiment_score is intentionally excluded: it has zero between-borough
// variance (London-wide signal applied uniformly), so its residual would
// be derived from a degenerate per-organ regression and could spuriously
// dominate the driver-attribution magnitude comparison.
const DIVERGENCE_ORGANS: { key: OrganKey; label: string }[] = [
  { key: "air_score", label: "Lungs" },
  { key: "transit_score", label: "Arteries" },
  { key: "immune_score", label: "Immune" },
  { key: "green_space_score", label: "Skin" },
];

/**
 * Per-borough divergence between actual composite score and what the chosen
 * IMD domain rank alone would predict, using **leave-one-out (LOO) residuals**:
 * for each borough, the regression line is refit on the other 32 boroughs, so
 * the borough being scored never contributed to its own predicted value.
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
 * `domain` defaults to "overall" (uses `imd_rank`). Pass any of the four
 * input-leakage-free sub-domains — income, employment, education,
 * barriers — for a deprivation baseline that does not share inputs with
 * any CityScan organ; or any other sub-domain to reframe the divergence
 * against that lens (with the input-overlap caveat surfaced in the
 * caption).
 *
 * Sentiment is intentionally excluded from the per-organ driver
 * regression: it is a London-wide signal applied uniformly to every
 * borough (zero between-borough variance), which makes its per-organ
 * residual degenerate and would let it spuriously dominate the driver
 * attribution. See DIVERGENCE_ORGANS for the four organs that ARE
 * included.
 *
 * Returns up to topN entries sorted by |residual| descending. Returns []
 * if fewer than 6 boroughs have both a rank and a composite score (LOO
 * requires ≥6 so each fit has ≥5 pairs).
 */
export function boroughDivergence(
  boroughs: BoroughScore[],
  deprivation: Record<string, DeprivationLike & { name?: string }>,
  topN: number = 5,
  domain: ImdDomainKey = "overall",
): BoroughDivergence[] {
  const compositePairs: { code: string; name: string; imd: number; actual: number }[] = [];
  for (const b of boroughs) {
    const dep = deprivation[b.borough_code];
    if (!dep || b.composite_score === null) continue;
    const rank = getDomainRank(dep, domain);
    if (rank === null) continue;
    compositePairs.push({
      code: b.borough_code,
      name: b.borough_name,
      imd: rank,
      actual: b.composite_score as number,
    });
  }
  if (compositePairs.length < 6) return [];

  // Per-organ pair arrays — built once, sliced per-borough during LOO loop.
  const organPairs: Partial<Record<OrganKey, { code: string; imd: number; actual: number }[]>> = {};
  for (const org of DIVERGENCE_ORGANS) {
    const arr: { code: string; imd: number; actual: number }[] = [];
    for (const b of boroughs) {
      const dep = deprivation[b.borough_code];
      if (!dep || b[org.key] === null) continue;
      const rank = getDomainRank(dep, domain);
      if (rank === null) continue;
      arr.push({
        code: b.borough_code,
        imd: rank,
        actual: b[org.key] as number,
      });
    }
    organPairs[org.key] = arr;
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
      : "mixed signal";

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
