/**
 * GeoJSON to SVG path converter for London borough boundaries.
 *
 * Reads london-boroughs.json (ONS GeoJSON with 33 boroughs) and converts
 * each Polygon's coordinates into an SVG path `d` string using a simple
 * Mercator projection scaled to fit a 600x500 viewBox.
 */

import boroughsGeoJson from "./london-boroughs.json";

/** A single borough's SVG representation. */
export interface BoroughGeo {
  code: string;
  name: string;
  path: string;
  /** Centroid in SVG coordinates (for tooltip positioning). */
  centroidX: number;
  centroidY: number;
}

/** SVG viewBox dimensions. */
export const VIEW_BOX_WIDTH = 800;
export const VIEW_BOX_HEIGHT = 600;

/** Padding inside the viewBox so boroughs don't clip edges. */
const PADDING = 20;

interface GeoJsonFeature {
  type: string;
  properties: { name: string; code: string; color?: string };
  geometry: {
    type: "Polygon";
    coordinates: number[][][];
  };
}

interface GeoJsonCollection {
  type: string;
  features: GeoJsonFeature[];
}

/**
 * Convert latitude to Mercator Y (web mercator).
 * This stretches higher latitudes so the map looks correct.
 */
function latToMercatorY(lat: number): number {
  const rad = (lat * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + rad / 2));
}

/** Compute bounding box of all features in Mercator-projected space. */
function computeBounds(features: GeoJsonFeature[]): {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
} {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const feature of features) {
    for (const ring of feature.geometry.coordinates) {
      for (const [lon, lat] of ring) {
        const mx = lon;
        const my = latToMercatorY(lat);
        if (mx < minX) minX = mx;
        if (mx > maxX) maxX = mx;
        if (my < minY) minY = my;
        if (my > maxY) maxY = my;
      }
    }
  }

  return { minX, maxX, minY, maxY };
}

function buildBoroughPaths(): BoroughGeo[] {
  const geojson = boroughsGeoJson as unknown as GeoJsonCollection;
  const features = geojson.features;
  const bounds = computeBounds(features);

  const geoWidth = bounds.maxX - bounds.minX;
  const geoHeight = bounds.maxY - bounds.minY;

  const drawWidth = VIEW_BOX_WIDTH - PADDING * 2;
  const drawHeight = VIEW_BOX_HEIGHT - PADDING * 2;

  // Scale independently on each axis to fill the viewBox.
  const scaleX = drawWidth / geoWidth;
  const scaleY = drawHeight / geoHeight;

  const offsetX = PADDING;
  const offsetY = PADDING;

  /** Project a [lon, lat] pair to SVG [x, y]. */
  function project(lon: number, lat: number): [number, number] {
    const x = (lon - bounds.minX) * scaleX + offsetX;
    // SVG Y is top-down, Mercator Y is bottom-up — flip.
    const my = latToMercatorY(lat);
    const y = (bounds.maxY - my) * scaleY + offsetY;
    return [x, y];
  }

  const result: BoroughGeo[] = [];

  for (const feature of features) {
    const { code, name } = feature.properties;
    const rings = feature.geometry.coordinates;

    let pathD = "";
    let sumX = 0;
    let sumY = 0;
    let pointCount = 0;

    for (const ring of rings) {
      for (let i = 0; i < ring.length; i++) {
        const [x, y] = project(ring[i][0], ring[i][1]);
        pathD += i === 0 ? `M${x.toFixed(2)},${y.toFixed(2)}` : `L${x.toFixed(2)},${y.toFixed(2)}`;
        sumX += x;
        sumY += y;
        pointCount++;
      }
      pathD += "Z";
    }

    result.push({
      code,
      name,
      path: pathD,
      centroidX: pointCount > 0 ? sumX / pointCount : 0,
      centroidY: pointCount > 0 ? sumY / pointCount : 0,
    });
  }

  return result;
}

/** Pre-computed borough SVG paths. Computed once at module load. */
export const BOROUGH_PATHS: BoroughGeo[] = buildBoroughPaths();

/** Lookup map by borough code for O(1) access. */
export const BOROUGH_PATH_MAP: Map<string, BoroughGeo> = new Map(
  BOROUGH_PATHS.map((b) => [b.code, b])
);
