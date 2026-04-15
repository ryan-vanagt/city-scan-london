/**
 * API client for the CityScan London FastAPI backend.
 *
 * All endpoints hit NEXT_PUBLIC_API_URL (default http://localhost:8000).
 */

import type { BoroughScore, BulletinResponse, LondonScore } from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Fetch London-wide health scores. */
export async function fetchLondonScore(): Promise<LondonScore> {
  const res = await fetch(`${BASE_URL}/london/score`);
  if (!res.ok) throw new Error(`London score fetch failed: ${res.status}`);
  const data = await res.json();
  if (!data || typeof data.composite_score === "undefined") {
    throw new Error("Invalid london score response shape");
  }
  return data;
}

/** Fetch all 33 boroughs with scores. */
export async function fetchBoroughs(): Promise<BoroughScore[]> {
  const res = await fetch(`${BASE_URL}/boroughs`);
  if (!res.ok) throw new Error(`Boroughs fetch failed: ${res.status}`);
  const data = await res.json();
  if (!Array.isArray(data)) {
    throw new Error("Invalid boroughs response shape");
  }
  return data;
}

/** Fetch the latest bulletin. Returns null if no bulletin exists. */
export async function fetchBulletin(): Promise<BulletinResponse | null> {
  const res = await fetch(`${BASE_URL}/bulletin/latest`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Bulletin fetch failed: ${res.status}`);
  return res.json();
}

/**
 * Stream a Doctor Agent query via SSE.
 *
 * Calls POST /agent/query and yields parsed SSE events as they arrive.
 * The caller is responsible for handling token and sources events.
 */
export async function* streamDoctorQuery(
  question: string,
  role?: string | null
): AsyncGenerator<
  | { type: "token"; content: string }
  | { type: "sources"; sources: Array<{ type: string; tool: string; data: Record<string, unknown> }> }
  | { type: "done" }
> {
  const body: Record<string, string> = { question };
  if (role) body.role = role;

  const res = await fetch(`${BASE_URL}/agent/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`Agent query failed: ${res.status}`);
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;

      const data = trimmed.slice(6);
      if (data === "[DONE]") {
        yield { type: "done" };
        return;
      }

      try {
        const parsed = JSON.parse(data);
        if (parsed && typeof parsed.type === "string") {
          yield parsed;
        }
      } catch {
        // Skip malformed events
      }
    }
  }
}
