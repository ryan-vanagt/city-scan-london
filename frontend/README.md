# CityScan London — Frontend

Next.js single-page app that visualises London's health as a thermal medical scan.

## Stack

Next.js 16 (App Router) | TypeScript | Tailwind CSS v4 | React 19 | Lucide React | react-markdown

## Setup

```bash
cd frontend
npm ci
npm run dev     # http://localhost:3000
```

Requires the backend running on `http://localhost:8000` (or set `NEXT_PUBLIC_API_URL`).

## Structure

```
app/page.tsx              — single page orchestrator (all state + transitions)
components/landing/       — bulletin report + X-ray map (landing overlay)
components/map/           — interactive thermal map (LondonMap, BoroughPath, tooltip)
components/header/        — vital signs bar + EKG animations
components/panels/        — Doctor chat (SSE) + Bulletin panel
components/ui/            — floating action buttons
lib/api.ts                — API client + SSE async generator
lib/colours.ts            — thermal gradient + glow/pulse calculations
lib/geo.ts                — GeoJSON → SVG path converter (Mercator projection)
lib/types.ts              — TypeScript interfaces
```

## Design

Medical thermal scan aesthetic. Dark background (`#020617`), 6-stop thermal gradient (blue=healthy, red=critical), X-ray blue (`#0ea5e9`) accents, EKG-animated header, clinical typography (JetBrains Mono for data, Inter for body, IBM Plex Sans for bulletins).

Full spec: `docs/frontend-spec.md`
