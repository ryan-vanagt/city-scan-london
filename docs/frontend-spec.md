# Frontend Specification — CityScan London

## Identity

CityScan London visualises London's health as a **thermal medical scan**. The UI feels like a radiologist's monitor: dark background, clinical typography, thermal-gradient borough map, vital signs header with EKG animations. The landing is a scan report (bulletin), which transitions into a live interactive thermal map.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 14+ (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Components | shadcn/ui (dark theme) |
| Icons | Lucide React |
| Fonts | JetBrains Mono (numbers/scores), Inter (body text), IBM Plex Sans (bulletin text) |
| Map | London borough SVG from ONS GeoJSON (static file, no map library needed) |
| API client | Native `fetch` with SSE via `EventSource` or manual stream parsing |

---

## Design System

### Colour Palette

**Background & surfaces:**

| Element | Hex | Usage |
|---|---|---|
| Page background | `#020617` (slate-950) | Darkest — radiologist monitor |
| Card/panel background | `#0f172a` (slate-900) | Panels, detail views |
| Border/dividers | `#1e293b` (slate-800) | Subtle structure |
| Text primary | `#e2e8f0` (slate-200) | Main readable text |
| Text secondary | `#64748b` (slate-500) | Labels, timestamps |

**Thermal gradient (borough fill, continuous based on score 0-100):**

| Score Range | Colour | Hex | Thermal feel |
|---|---|---|---|
| 90-100 | Deep blue | `#1e3a8a` | Cold — perfectly healthy |
| 75-89 | Blue | `#2563eb` | Cool — healthy |
| 60-74 | Cyan/teal | `#06b6d4` | Moderate — stable |
| 45-59 | Green-yellow | `#84cc16` | Warming — watch |
| 30-44 | Orange | `#f97316` | Hot — struggling |
| 0-29 | Red | `#ef4444` | Hotspot — critical |

Implement as a continuous interpolation function: `scoreToColour(score: number): string` — interpolate between these stops so every score gets a unique shade.

**X-ray mode (bulletin landing):** All boroughs rendered in monochrome scan blue `#0ea5e9` on `#020617` background.

### Glow Effect

Boroughs have a CSS `box-shadow` / SVG `filter: drop-shadow(...)` glow in their thermal colour. Intensity proportional to how far from "moderate" the score is — very healthy (deep blue glow) and very unhealthy (red glow) both glow more than mid-range boroughs.

### Pulse Animation

Every borough pulses (subtle opacity oscillation 0.7 → 1.0 → 0.7). Pulse speed mapped to health:
- Score 90+: slow, steady pulse (~2s cycle) — healthy resting heartbeat
- Score 50-89: medium pulse (~1.5s cycle)
- Score <50: faster pulse (~0.8s cycle) — elevated, stressed

### Typography

- **Scores and numbers:** JetBrains Mono, monospace. Clinical readout feel.
- **Body text, labels:** Inter. Clean, neutral.
- **Bulletin report text:** IBM Plex Sans. Editorial, medical report.
- **Borough names on hover:** ALL CAPS, letter-spacing: 0.15em, small font (12px). Like a medical chart label.

All fonts loaded via `next/font` (Google Fonts for Inter and IBM Plex Sans, self-hosted or Google for JetBrains Mono).

### Transitions

All interactive transitions: `300ms ease-out`. Never instant, never slow.

---

## Page Structure — Single Page

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LANDING: BULLETIN SCAN REPORT                    │
│          (full viewport, X-ray blue London map + report text)        │
│                                                                      │
│                    scroll or click to enter live map                  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ smooth transition
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER: Vital Signs Bar                                              │
│  🫁 ~~42~~  │  🩸 ~~78~~  │  🧠 ~~61~~  │  🛡️ ~~55~~  │  ❤️ 59   │
│  (EKG line)    (EKG line)    (EKG line)    (EKG line)     overall    │
├────────────────────────────────────────┬─────────────────────────────┤
│                                        │                             │
│         LONDON THERMAL MAP             │    CONTEXTUAL PANEL         │
│         (SVG, ~65% width)              │    (slides in/out)          │
│                                        │                             │
│         boroughs filled with           │    - Borough detail         │
│         thermal gradient               │      (on borough click)     │
│         pulsing, interactive           │    - Doctor chat             │
│                                        │      (on 🩺 click)          │
│                                        │    - Bulletin                │
│                                        │      (on 📋 click)          │
│                                        │                             │
├────────────────────────────────────────┴─────────────────────────────┤
│ FOOTER: Ryan Van Agt • UCL MSc Business Analytics                    │
│         Powered by Claude Haiku 4.5, LangGraph, DuckDB, ChromaDB    │
│         [LinkedIn icon] [GitHub icon]                        🔊 📋 🩺│
└──────────────────────────────────────────────────────────────────────┘
```

---

## Section 1: Landing — Bulletin Scan Report

**Trigger:** page load (default view).

**Layout:** Full viewport, centred.

**Left/centre:** London borough map in X-ray blue (monochrome `#0ea5e9`, all boroughs same colour). Static, no interaction. Like a medical scan image on a dark background.

**Right or below map:** Today's bulletin text, styled as a medical scan report:

```
CITYSCAN LONDON
Daily Health Scan — 12 April 2026
──────────────────────────────────────

PATIENT:    Greater London (33 boroughs)
OVERALL:    62 / 100

FINDINGS:
• Respiratory (Air): Moderate impairment...
• Circulatory (Transit): Strong...
• Neurological (Sentiment): Stable...
• Immune (Crime/A&E): Within normal parameters...

AREAS OF CONCERN:
• Tower Hamlets — composite 41/100
• Newham — air quality 28/100

ATTENDING: Dr. CityScan AI
MODEL:     Claude Haiku 4.5
```

Font: JetBrains Mono for the whole report block. Bordered with `border: 1px solid #1e293b`. Subtle scan-line CSS animation (horizontal line sweeping down slowly, like a scanner).

**Transition trigger:** scroll down, or click a "View Live Vitals" button/arrow at the bottom. The bulletin slides up, the X-ray map smoothly transitions to thermal colours — boroughs fill with their health colours one by one (staggered animation, ~50ms delay per borough).

**API:** `GET /bulletin/latest` for bulletin content. `GET /london/score` for overall score in header.

---

## Section 2: Vital Signs Header

**Always visible** once the live map is active (sticky top bar).

**Content:** Four vital signs + overall score, each with:
1. Medical icon (Lucide React)
2. EKG-style animated SVG line (~120px wide, continuously animating left-to-right)
3. Numerical score in JetBrains Mono, bold

**EKG line shapes per metric:**
- Lungs (Air): smooth sine wave — breathing rhythm
- Arteries (Transit): sharp spikes with flat sections — heartbeat
- Brain (Sentiment): gentle undulation — brain waves
- Immune: steady small pulses — immune ticks

Each EKG line is an SVG `<path>` with `stroke-dashoffset` animation. The line colour matches the thermal colour of that metric's score.

**Interactivity:**
- **Hover a borough on the map** → header scores smoothly transition to that borough's scores (not London-wide). On mouse leave, transition back to London averages.
- **Click a metric in the header** → map recolours to show only that metric. Clicking again (or clicking "Overall") resets to composite score. Active metric is underlined or highlighted.

**API:** `GET /london/score` for city-wide scores. Borough-specific scores come from the map data already loaded.

---

## Section 3: London Thermal Map

**Source:** London borough boundaries GeoJSON from ONS, converted to an inline SVG or rendered via a lightweight SVG component. Each borough is a `<path>` element with a unique `data-borough-code` attribute.

**Fill:** Each borough filled with its thermal colour via `scoreToColour(compositeScore)`. When a metric filter is active, use that metric's score instead.

**Default state (no hover):** All boroughs visible at full opacity, pulsing at their health-rate.

**Hover behaviour (focus mode):**
1. Hovered borough: `opacity: 1`, `transform: scale(1.05)`, `filter: brightness(1.2)`, glow intensifies
2. All other boroughs: `opacity: 0.3`, `filter: brightness(0.5)`, pulse pauses
3. Tooltip appears adjacent to the borough:
   ```
   C A M D E N
   🫁 34  🩸 82  🧠 62  🛡️ 55
   ━━━━━━━━━━━━━━━━
   Overall: 58
   ```
   Background: `#0f172a` with 90% opacity. Border: `1px solid` in the borough's thermal colour.
4. Header scores transition to this borough's scores.

**Click behaviour:**
- Right panel slides in with borough detail.
- Clicked borough stays elevated + highlighted.
- Other boroughs stay dimmed.
- Click elsewhere or panel X → panel closes, map returns to normal.

**CSS approach for focus:**
```css
.map-container:hover .borough { opacity: 0.3; filter: brightness(0.5); transition: all 0.3s ease-out; }
.map-container:hover .borough:hover { opacity: 1; filter: brightness(1.2); transform: scale(1.05); }
```

**API:** `GET /boroughs` — returns all 33 boroughs with all scores. Single request, cached. This data drives the entire map + tooltips + header updates.

---

## Section 4: Contextual Right Panel

A slide-in panel (~35% width) that appears from the right edge. Three possible states:

### State A: Borough Detail (on borough click)

Minimal. Clean. Scores only — the Doctor handles deep questions.

```
┌─────────────────────────────┐
│  ✕                    E09000007 │
│                                 │
│  C A M D E N                    │
│                                 │
│  🫁 Air Quality         34     │
│  ████████░░░░░░░░░░░░  34/100  │
│                                 │
│  🩸 Transit             82     │
│  ████████████████░░░░  82/100  │
│                                 │
│  🧠 Sentiment           62     │
│  ████████████░░░░░░░░  62/100  │
│                                 │
│  🛡️ Immune              55     │
│  ███████████░░░░░░░░░  55/100  │
│                                 │
│  ──────────────────────         │
│  Overall: 58                    │
│                                 │
│  Last updated: 12 Apr 09:00     │
│                                 │
│  [🩺 Ask the Doctor about       │
│      Camden]                    │
│                                 │
└─────────────────────────────────┘
```

Score bars filled with the thermal gradient colour of each score. The "Ask the Doctor" button pre-fills the chat with "How is Camden doing?" and opens the chat panel.

**API:** No extra call needed — data already loaded from `GET /boroughs`.

### State B: Doctor Chat (on 🩺 click)

Chat interface styled as a medical consultation.

**Header:** "Dr. CityScan" with stethoscope icon.

**Initial message (pre-populated, not from API):**
"Good morning. London's overall health is 62/100 today. What would you like to know?"

**User input:** text field at the bottom. On submit → `POST /agent/query` with SSE streaming.

**Token streaming:** tokens appear one by one (typewriter effect) in a chat bubble. Use JetBrains Mono for the response text (medical readout feel).

**Sources:** after the response completes (after `[DONE]`), sources appear as small collapsible cards below the message: "Source: get_borough_health(Camden) → DuckDB" with a toggle to expand raw data.

**Chat history:** maintained in React state for the session. Not persisted.

**SSE parsing:** Connect to `POST /agent/query` endpoint. Parse SSE events:
- `{"type": "token", "content": "..."}` → append to current response
- `{"type": "sources", "sources": [...]}` → store for display after response
- `[DONE]` → mark response complete

### State C: Bulletin (on 📋 click)

Renders the latest bulletin markdown in IBM Plex Sans. Same content as the landing page report but in the side panel. Useful for reference while exploring the map.

**API:** `GET /bulletin/latest` (can cache from landing page load).

---

## Section 5: Floating Action Buttons

Bottom-right corner, vertical stack:

1. **📋 Bulletin** — opens/closes bulletin panel
2. **🩺 Doctor** — opens/closes chat panel
3. **🔊 Sound** (polish) — toggles heartbeat audio

Each button: circular, `48px`, background `#0f172a`, border `1px solid #1e293b`. Hover: glow effect in `#0ea5e9`. The stethoscope icon does a subtle pulse animation when idle (inviting interaction).

Only one panel can be open at a time — opening one closes the other.

---

## Section 6: Footer

Thin bar, always visible at bottom of map section.

```
Ryan Van Agt  •  UCL MSc Business Analytics  •  Powered by Claude Haiku 4.5, LangGraph, DuckDB, ChromaDB   [LinkedIn] [GitHub]
```

Font: Inter, 12px, `text-secondary` colour. LinkedIn and GitHub are small Lucide icons linked to:
- LinkedIn: Ryan's profile URL
- GitHub: `https://github.com/ryan-vanagt/city-scan-london` (404 while private, works when public)

---

## Section 7: Loading State

On initial page load, before API data arrives:

1. London borough map outline in X-ray blue (`#0ea5e9`), no fill
2. Pulsing text: "Scanning London..." in JetBrains Mono, centre of map
3. Subtle horizontal scan-line animation sweeping top to bottom
4. Once data loads, boroughs fill with thermal colours in a staggered wave (50ms per borough, sorted by borough code)

---

## API Endpoints Consumed

| Endpoint | Method | Used by | Caching |
|---|---|---|---|
| `/london/score` | GET | Header vital signs, landing overall score | Cache 60s |
| `/boroughs` | GET | Map fills, tooltips, borough detail panel, header on hover | Cache 60s |
| `/bulletin/latest` | GET | Landing bulletin, bulletin panel | Cache 5min |
| `/agent/query` | POST (SSE) | Doctor chat | No cache |

**Base URL:** `http://localhost:8000` in dev. Configurable via `NEXT_PUBLIC_API_URL` env var.

**CORS:** API already allows `http://localhost:3000`.

---

## File Structure

```
frontend/
├── app/
│   ├── layout.tsx          ← root layout, fonts, metadata
│   ├── page.tsx            ← single page entry point
│   └── globals.css         ← Tailwind base + custom animations
├── components/
│   ├── landing/
│   │   ├── BulletinReport.tsx   ← scan report styled bulletin
│   │   └── XRayMap.tsx          ← static X-ray blue London map
│   ├── map/
│   │   ├── LondonMap.tsx        ← interactive SVG thermal map
│   │   ├── BoroughPath.tsx      ← individual borough SVG path
│   │   └── BoroughTooltip.tsx   ← hover tooltip
│   ├── header/
│   │   ├── VitalSigns.tsx       ← header bar with 4 metrics
│   │   └── EkgLine.tsx          ← animated SVG EKG line
│   ├── panels/
│   │   ├── BoroughDetail.tsx    ← borough scores panel
│   │   ├── DoctorChat.tsx       ← SSE chat interface
│   │   └── BulletinPanel.tsx    ← bulletin in side panel
│   ├── ui/
│   │   ├── FloatingActions.tsx  ← FAB buttons (doctor, bulletin, sound)
│   │   └── ScoreBar.tsx         ← horizontal score bar with thermal fill
│   └── Footer.tsx
├── lib/
│   ├── api.ts              ← fetch wrappers for all endpoints
│   ├── colours.ts          ← scoreToColour() thermal gradient function
│   ├── types.ts            ← TypeScript interfaces for API responses
│   └── london-boroughs.json ← GeoJSON borough boundaries
├── public/
│   └── heartbeat.wav       ← optional audio file (CC0 licensed)
├── package.json
├── tailwind.config.ts
├── tsconfig.json
└── next.config.ts
```

---

## Polish Features (if time allows)

Ordered by impact-to-effort ratio:

1. **EKG line animations** in header — high impact, ~50 lines SVG per shape
2. **Staggered borough reveal** on transition from bulletin → map — high impact, CSS only
3. **Map zoom on Doctor mention** — when Doctor response contains a borough name, that borough auto-highlights for 2 seconds
4. **Heartbeat audio** — toggle on/off, speed tied to hovered borough score
5. **Scan-line animation** on landing bulletin — horizontal line sweeping down
6. **Borough entrance animation** — boroughs fly in or fade in when page loads

---

## Responsive Behaviour (Desktop-First)

**Desktop (>1024px):** Full layout as described. Map ~65%, panel ~35%.

**Tablet (768-1024px):** Map full width. Panel overlays from bottom (half height) instead of right side.

**Mobile (<768px):** Map full width (simplified, no hover — tap to select). Panel is full-screen overlay. FABs remain in bottom-right.

---

## Environment Variables

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

In Docker, this is set to the API service's internal URL.
