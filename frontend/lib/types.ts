/** TypeScript interfaces matching the FastAPI backend responses. */

export interface LondonScore {
  composite_score: number | null;
  air_score: number | null;
  transit_score: number | null;
  sentiment_score: number | null;
  immune_score: number | null;
  green_space_score: number | null;
  borough_count: number;
  timestamp: string | null;
}

export interface BoroughScore {
  borough_code: string;
  borough_name: string;
  timestamp: string | null;
  air_score: number | null;
  transit_score: number | null;
  sentiment_score: number | null;
  immune_score: number | null;
  green_space_score: number | null;
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

export type SSEEvent = SSETokenEvent | SSESourcesEvent;

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: SSESourcesEvent["sources"];
  isStreaming?: boolean;
}

/** Which metric is currently filtering the map (null = composite/overall) */
export type MetricFilter =
  | "air_score"
  | "transit_score"
  | "sentiment_score"
  | "immune_score"
  | "green_space_score"
  | null;

/** Which panel is open on the right side */
export type PanelState =
  | { type: "closed" }
  | { type: "borough"; boroughCode: string }
  | { type: "doctor"; prefill?: string }
  | { type: "bulletin" };
