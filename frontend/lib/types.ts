/** TypeScript interfaces matching the FastAPI backend responses. */

export interface LondonScore {
  composite_score: number | null;
  air_score: number | null;
  air_quality_modelled_score: number | null;
  transit_score: number | null;
  sentiment_score: number | null;
  immune_score: number | null;
  green_space_score: number | null;
  green_space_access_score: number | null;
  borough_count: number;
  timestamp: string | null;
}

export interface BoroughScore {
  borough_code: string;
  borough_name: string;
  timestamp: string | null;
  air_score: number | null;
  air_quality_modelled_score: number | null;
  transit_score: number | null;
  sentiment_score: number | null;
  immune_score: number | null;
  green_space_score: number | null;
  green_space_access_score: number | null;
  composite_score: number | null;
}

export interface BulletinResponse {
  date: string;
  content: string;
  scores?: {
    london_score?: LondonScore;
    [key: string]: unknown;
  };
}

export interface SSETokenEvent {
  type: "token";
  content: string;
}

export interface SSESourcesEvent {
  type: "sources";
  sources: Array<{
    type: string;
    tool: string;
    data: Record<string, unknown>;
  }>;
}

export interface SSEDoneEvent {
  type: "done";
}

export type SSEEvent = SSETokenEvent | SSESourcesEvent | SSEDoneEvent;

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: SSESourcesEvent["sources"];
  isStreaming?: boolean;
}

export interface TrendInfo {
  direction: "improving" | "declining" | "stable" | null;
  delta: number | null;
}

export interface HousingAffordability {
  borough_code: string;
  borough_name: string;
  ratio: number | null;            // current-year median ratio (house price / earnings)
  ratio_5yr_avg: number | null;    // 5-year average for context
  year: number | null;             // year ending September (e.g. 2025)
}

export interface HealthIndexEntry {
  borough_code: string;
  borough_name: string;
  score: number | null;            // ONS Health Index latest year (England 2015 = 100 baseline)
  score_2020: number | null;       // for context
  score_2015: number | null;       // baseline year
  year: number | null;             // most recent year covered (likely 2021)
}

/** Which metric is currently filtering the map (null = composite/overall) */
export type MetricFilterKey =
  | "air_score"
  | "transit_score"
  | "sentiment_score"
  | "immune_score"
  | "green_space_score";

export type MetricFilter = MetricFilterKey | null;

/** Which panel is open on the right side */
export type PanelState =
  | { type: "closed" }
  | { type: "borough"; boroughCode: string }
  | { type: "doctor"; prefill?: string }
  | { type: "bulletin" }
  | { type: "analytics" };
