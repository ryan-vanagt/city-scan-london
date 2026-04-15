# Frontend Specification — CityScan London

## Identity

CityScan London visualises London's health as a **thermal medical scan**. The UI feels like a radiologist's monitor: dark background, clinical typography, thermal-gradient borough map, vital signs header with EKG animations. The landing is a scan report (bulletin), which transitions into a live interactive thermal map.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 16+ (App Router) |
| Language | TypeScript (strict mode) |
| Styling | Tailwind CSS v4 (inline theme via PostCSS) |
| Icons | Lucide React |
| Markdown | react-markdown + remark-gfm |
| Fonts | JetBrains Mono (numbers/scores), Inter (body text), IBM Plex Sans (bulletin text) |
| Map | London borough SVG from ONS GeoJSON (`lib/london-boroughs.json`), Mercator-projected in `lib/geo.ts` |
| API client | Native `fetch` with manual SSE stream parsing via `ReadableStream` |

All fonts loaded via `next/font` (Google Fonts).

---

## Design System

### Colour Palette

**Background & surfaces:**

| Element | Hex | Tailwind | Usage |
|---|---|---|---|
| Page background | `#020617` | slate-950 | Darkest — radiologist monitor |
| Card/panel background | `#0f172a` | slate-900 | Panels, tooltips, detail views |
| Border/dividers | `#1e293b` | slate-800 | Subtle structure |
| Text primary | `#e2e8f0` | slate-200 | Main readable text |
| Text secondary | `#64748b` | slate-500 | Labels, timestamps, muted |
| X-ray blue | `#0ea5e9` | sky-500 | Accent, links, active states |

**Thermal gradient** (borough fill, continuous interpolation in `lib/colours.ts`):

| Score | Colour | Hex | Thermal feel |
|---|---|---|---|
| 100 | Deep blue | `#1e3a8a` | Cold — perfectly healthy |
| 75 | Blue | `#2563eb` | Cool — healthy |
| 60 | Cyan/teal | `#06b6d4` | Moderate — stable |
| 45 | Green-yellow | `#84cc16` | Warming — watch |
| 30 | Orange | `#f97316` | Hot — struggling |
| 0 | Red | `#ef4444` | Hotspot — critical |

Implemented as `scoreToColour(score)` — linearly interpolates RGB between stops. Null scores render as `#64748b` (slate-500).

**X-ray mode (landing):** All boroughs rendered in monochrome `#0ea5e9` at 30% opacity.

### Glow Effect

Boroughs have SVG `filter: drop-shadow(...)` glow in their thermal colour. Intensity calculated by `glowIntensity(score)` — returns 0.1-0.9 based on distance from score 50. Extreme scores (very healthy or very unhealthy) glow brighter than mid-range.

### Pulse Animation

Every borough has a `borough-pulse` CSS animation — subtle scale oscillation (1.0 → 1.03 → 1.0). Pulse speed mapped to health via `pulseDuration(score)`:
- Score 80+: 1.5s cycle — healthy resting heartbeat
- Score 50-79: 2.0s cycle — slightly slower
- Score 30-49: 3.0s cycle — laboured
- Score <30: 4.0s cycle — barely alive

Pulse only activates after the landing-to-map transition completes (`effectsReady` state).

### Typography

- **Scores and numbers:** JetBrains Mono (`--font-jetbrains`). Clinical readout.
- **Body text, labels:** Inter (`--font-inter`). Clean, neutral.
- **Bulletin text:** IBM Plex Sans (`--font-ibm-plex`). Editorial, medical report.
- **Borough names:** ALL CAPS, letter-spacing: 0.15em, 11px. Medical chart label.

### Transitions & Animations

| Animation | Duration | Easing | Used by |
|---|---|---|---|
| Borough hover (scale, filter) | 300ms | ease-out | BoroughPath |
| Borough fill (thermal colour) | 1.5s | ease-out | BoroughPath |
| Borough opacity (dim/restore) | 1s | ease-out | BoroughPath |
| Panel slide-in | 0.4s | ease-out | page.tsx panel container |
| Landing dissolve | 1.2s | ease-out | page.tsx landing overlay |
| Map dezoom | 2s | cubic-bezier(0.16,1,0.3,1) | page.tsx map container |
| Header/footer appear | 0.5s | ease-out | page.tsx |
| EKG scroll | 2s | linear infinite | EkgLine (translateX loop) |
| Scan line | 3s | ease-in-out infinite | XRayMap (vertical sweep) |
| Borough pulse | variable | ease-in-out infinite | BoroughPath (scale) |
| Scanning pulse | 1.5s | ease-in-out infinite | Loading text, cursor |

---

## Page Structure — Single Page

All state lives in `app/page.tsx`. No routing — everything is panel-based.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LANDING: BULLETIN SCAN REPORT                    │
│          (full viewport, X-ray blue London map + report text)        │
│                                                                      │
│              "SCANNING LONDON..." pulsing text while loading         │
│              bulletin card centred, "VIEW LIVE SIGNALS" button       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ 5-act transition (3.5s total)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER: Vital Signs Bar (sticky)                                     │
│  [ALL] AIR ~~42~~ │ TRANSIT ~~78~~ │ SENTIMENT ~~61~~ │ IMMUNE ~~55~~ │ GREEN SPACE ~~70~~ │ ❤ 59│
│        (EKG line)   (EKG line)       (EKG line)         (EKG line)     (EKG line)          │
├────────────────────────────────────────┬─────────────────────────────┤
│                                        │                             │
│         LONDON THERMAL MAP             │    CONTEXTUAL PANEL         │
│         (SVG, responsive width)        │    (35% desktop, 90% mobile)│
│                                        │                             │
│         boroughs filled with           │    - Doctor chat             │
│         thermal gradient               │      (on ASK THE DOCTOR)    │
│         pulsing, hover-interactive     │    - Analytics scatter       │
│                                        │      (on ANALYTICS)         │
│                                        │                             │
├────────────────────────────────────────┴─────────────────────────────┤
│ FOOTER: Ryan Van Agt • Sources • Powered by...    [LinkedIn][GitHub] │
│                                                   ANALYTICS          │
│                                                   ASK THE DOCTOR     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Section 1: Landing — Bulletin Scan Report

**Trigger:** Page load (default view). Shown while `showLanding` is true.

**Layout:** Full viewport overlay (fixed inset-0, z-30). Semi-transparent background `rgba(2,6,23,0.65)`.

**Loading state:** While API data is loading (`isLoading && boroughs.length === 0`), displays pulsing "SCANNING LONDON..." text (cyan, JetBrains Mono, tracking-widest, `animate-pulse`).

**Content (after data loads):**
- `BulletinReport` component — medical scan report card:
  - Header: "CITYSCAN LONDON", date, overall score (thermal-coloured, 4xl)
  - Decorative dash divider
  - Bulletin markdown (truncated to 500 chars on landing, full in panel)
  - Footer: "ATTENDING: Dr. CityScan AI" / "MODEL: Claude Sonnet 4.5"
  - Font: IBM Plex Sans for markdown, JetBrains Mono for scores
- "VIEW LIVE SIGNALS" button with bouncing ChevronDown icon

**X-ray map:** `XRayMap` component renders static monochrome borough outlines behind the bulletin card. Scan-line animation sweeps vertically.

**Transition to live map (5-act sequence):**
1. (0ms) Landing overlay dissolves (opacity → 0, blur → 6px, 1.2s)
2. (600ms) Map dezooms from scale(4) → scale(1) (2s cubic-bezier)
3. (1800ms) Borough colours change from X-ray blue → thermal gradient (1.5s fill transition)
4. (2200ms) Header, footer, FABs fade in (0.5s)
5. (3500ms) Glow and pulse effects enabled

**Error state:** If all API fetches fail and no boroughs load, a toast appears: "Unable to connect to API — make sure backend is running on port 8000"

---

## Section 2: Vital Signs Header

**Component:** `VitalSigns` — sticky top bar, z-40.

**Layout:** Three sections:
1. **Left:** Context label — shows abbreviated hovered borough name or "LONDON" (hidden on mobile)
2. **Centre:** "ALL" button + 5 metric buttons (air, transit, sentiment, immune, green space)
3. **Right:** HeartPulse icon (pulsing) + overall composite score

**Each metric button shows:**
- Label text (hidden on xs screens, visible on sm+)
- EKG animated SVG line (120px wide, `ekg-scroll` animation, always X-ray blue colour)
- Score value in thermal colour (JetBrains Mono, bold)

**EKG line variants** (via `EkgLine` component, one per metric):
- Air: smooth sine wave (breathing rhythm)
- Transit: sharp ECG spikes (heartbeat)
- Sentiment: gentle curves (brain waves)
- Immune: small pulses (immune ticks)
- Green Space: organic undulations suggesting growth/foliage

**Interactivity:**
- **Hover a borough** → header scores transition to that borough's scores. On leave → back to London-wide.
- **Click a metric** → map recolours to that metric only. Click again → resets to composite. "ALL" button resets.
- Active metric: X-ray blue background + text. Inactive: slate text, transparent background.

**Accessibility:** `aria-pressed` on all metric toggle buttons.

---

## Section 3: London Thermal Map

**Component:** `LondonMap` — orchestrates 33 `BoroughPath` components.

**Source:** ONS GeoJSON (`lib/london-boroughs.json`) projected to SVG via Mercator projection in `lib/geo.ts`. ViewBox: 800x600.

**Fill:** Each borough filled with `scoreToColour(score)`. When a metric filter is active, uses that metric's score.

**Hover behaviour (focus mode):**
1. Hovered borough: opacity 1, scale 1.05, brightness 1.2, glow intensifies
2. All other boroughs: opacity 0.3, brightness 0.5
3. Tooltip appears above the borough (positioned at centroid):
   - Borough name (uppercase, tracking)
   - Metric scores (abbreviations: AIR, TRS, SNT, IMM, GRN)
   - Divider
   - Overall composite score
   - Border colour matches the borough's thermal colour (with glow)
4. Header scores update to this borough

**No click behaviour** — boroughs are hover-only. Deep questions go through the Doctor chat.

**Performance:** `scoreMap` wrapped in `useMemo([boroughs])`. Tooltip position calculated from SVG centroid mapped to DOM coordinates.

**Vignette:** Radial gradient overlay darkens map edges.

**Accessibility:** SVG has `role="group"` and `aria-label`. Each `<path>` contains `<title>` with borough name and score.

---

## Section 4: Contextual Right Panel

Slide-in panel (35% width desktop, 90% mobile). Fixed position, right-0, top-0, padding-top 52px (below header). Opacity + translateX transition (0.4s ease-out).

### State A: Doctor Chat (on "ASK THE DOCTOR" FAB)

**Component:** `DoctorChat` — SSE streaming chat panel.

**Header:** "DR. CITYSCAN" (uppercase, tracking-widest). Close button (X icon).

**Initial greeting** (pre-populated, not from API):
```
"Good [morning/afternoon/evening]. London's overall health is [score]/100 today. What would you like to know?"
```

**Suggestion chips:** Two static prompts shown on initial load — one policy-oriented, one public-oriented. Auto-detect handles role differentiation.

**Chat behaviour:**
- User submits question → POST /agent/query (SSE)
- Tokens appear one by one (typewriter effect) in JetBrains Mono
- Blinking cyan cursor while streaming
- After `[DONE]`, collapsible source cards appear below the message

**Source cards:** Collapsible, show tool name + raw JSON data on expand.

**Rate limiting:** 3-second cooldown between queries. Send button disabled during cooldown. Prevents rapid-fire API calls.

**Input:** maxLength 500 (matches backend validation). JetBrains Mono. AutoComplete off.

**Accessibility:** Messages container has `role="log"` and `aria-live="polite"`. Input and send button have `aria-label`.

### State B: Analytics Panel (on "ANALYTICS" FAB)

**Component:** `AnalyticsPanel` — Health vs Deprivation scatter plot.

**Header:** "ANALYTICS" (uppercase, tracking-widest). Close button.

**Content:** `DeprivationScatter` chart (Recharts `ScatterChart`) plotting all 33 boroughs:
- X-axis: IMD 2025 deprivation rank (1 = most deprived)
- Y-axis: Composite health score (0-100)
- Each dot: thermal-coloured by composite score (uses `scoreToColour`), sized for visibility
- Outlier boroughs are labelled directly on the chart
- Trend line shows correlation between deprivation and health

**Data source:** `GET /boroughs/deprivation` for IMD data, merged with borough scores already loaded.

**Empty state:** "No deprivation data available." centred text.

Only one panel can be open at a time — opening one closes the other.

> **Note:** `BulletinPanel` still exists but is used only on the landing page (as `BulletinReport`). It is no longer accessible from the live map FABs.

---

## Section 5: Floating Action Buttons

**Component:** `FloatingActions` — fixed bottom-right (bottom: 56px, right: 24px, z-50).

Two pill-shaped buttons stacked vertically (12px gap):
1. **"ANALYTICS"** — toggles analytics panel (Health vs Deprivation scatter plot)
2. **"ASK THE DOCTOR"** — toggles doctor chat panel

**Button style:** Rounded (24px radius), dark background (`#0f172a`), 1px border. Text: uppercase Inter 11px, font-weight 600, tracking 0.1em.

**States:**
- Inactive: border `#1e293b`, text `#64748b`
- Hover/Active: border `#0ea5e9`, text `#0ea5e9`, box-shadow glow

**Visibility:** Hidden during landing and when a panel is open.

**Accessibility:** `aria-label` and `aria-pressed` on both buttons.

---

## Section 6: Footer

**Component:** `Footer` — fixed thin bar at viewport bottom.

**Content:**
```
Ryan Van Agt • Sources: OpenAQ, TfL, Guardian/BBC, Met Police, NHS A&E, GLA Green Cover (yearly) • Powered by Claude Sonnet 4.5, LangGraph, DuckDB, ChromaDB   [LinkedIn] [GitHub]
```

Custom inline SVG icons for LinkedIn (18px) and GitHub (16px).

**Styling:** Inter 12px, `#64748b` text, `#020617` background, `#1e293b` border-top.

**Accessibility:** `aria-label` on social links, `aria-hidden` on icons, `rel="noopener noreferrer"`.

---

## Section 7: Loading State

On initial page load, before API data arrives:
1. Landing overlay visible with pulsing "SCANNING LONDON..." text (cyan, JetBrains Mono)
2. X-ray map renders behind (static, scan-line animation)
3. Once data loads, bulletin card appears and "VIEW LIVE SIGNALS" button becomes active

---

## API Endpoints Consumed

| Endpoint | Method | Used by | Notes |
|---|---|---|---|
| `/london/score` | GET | Header vital signs, landing overall score | Runtime shape validation |
| `/boroughs` | GET | Map fills, tooltips, header on hover | Runtime array validation |
| `/bulletin/latest` | GET | Landing bulletin, bulletin panel | Returns null on 404 |
| `/agent/query` | POST (SSE) | Doctor chat | Manual stream parsing, type-guarded events |
| `/boroughs/deprivation` | GET | Analytics panel scatter chart | IMD 2025 data for all boroughs |

**Base URL:** `NEXT_PUBLIC_API_URL` env var (default `http://localhost:8000`).

**CORS:** API allows `http://localhost:3000`.

**Error handling:** `Promise.allSettled` for parallel initial fetch — partial data renders if any single endpoint fails.

---

## File Structure

```
frontend/
├── app/
│   ├── layout.tsx          ← root layout, fonts (Inter, JetBrains Mono, IBM Plex Sans), metadata
│   ├── page.tsx            ← single page orchestrator (all state, transitions, panels)
│   └── globals.css         ← Tailwind v4 theme, keyframe animations, scrollbar styles
├── components/
│   ├── landing/
│   │   ├── BulletinReport.tsx   ← scan report styled bulletin (truncated, markdown)
│   │   └── XRayMap.tsx          ← static X-ray blue London map with scan-line
│   ├── map/
│   │   ├── LondonMap.tsx        ← interactive SVG thermal map (hover, tooltip, metric filter)
│   │   ├── BoroughPath.tsx      ← individual borough path (thermal fill, glow, pulse)
│   │   └── BoroughTooltip.tsx   ← hover tooltip (metric scores, thermal border)
│   ├── header/
│   │   ├── VitalSigns.tsx       ← sticky header (5 metrics + composite, metric filter)
│   │   └── EkgLine.tsx          ← animated SVG EKG waveform (5 variants)
│   ├── panels/
│   │   ├── DoctorChat.tsx       ← SSE streaming chat (rate-limited, markdown, source cards)
│   │   ├── AnalyticsPanel.tsx   ← analytics panel with Health vs Deprivation scatter chart
│   │   └── BulletinPanel.tsx    ← full bulletin markdown (landing page only, not in live map)
│   ├── charts/
│   │   └── DeprivationScatter.tsx ← Recharts scatter: IMD rank vs health score
│   ├── ui/
│   │   └── FloatingActions.tsx  ← FAB buttons (analytics, doctor)
│   └── Footer.tsx               ← attribution bar with social links
├── lib/
│   ├── api.ts              ← fetch wrappers + SSE async generator (type-guarded)
│   ├── colours.ts          ← scoreToColour(), glowIntensity(), pulseDuration(), constants
│   ├── types.ts            ← TypeScript interfaces (LondonScore, BoroughScore, PanelState, etc.)
│   ├── geo.ts              ← GeoJSON → SVG path converter (Mercator projection)
│   └── london-boroughs.json ← ONS GeoJSON borough boundaries
├── public/
│   └── (static assets)
├── package.json
├── tsconfig.json
├── eslint.config.mjs
├── postcss.config.mjs
└── next.config.ts
```

---

## Component Hierarchy

```
RootLayout (layout.tsx)
└─ Page (page.tsx)
   ├─ VitalSigns
   │  └─ EkgLine (x5)
   ├─ LondonMap
   │  ├─ BoroughPath (x33)
   │  └─ BoroughTooltip (0 or 1)
   ├─ Panel container
   │  ├─ DoctorChat [conditional]
   │  │  └─ SourceCard (xN)
   │  └─ AnalyticsPanel [conditional]
   │     └─ DeprivationScatter
   ├─ FloatingActions [conditional]
   │  └─ FabButton (x2)
   ├─ Footer [conditional]
   ├─ BulletinReport [landing only]
   │  └─ (XRayMap rendered separately)
   ├─ XRayMap [landing only]
   └─ Error toast [conditional]
```

---

## Responsive Behaviour

**Desktop (md+):** Full layout. Map responsive width. Panel 35% width from right.

**Mobile (<md):** Panel takes 90% width. Metric labels hidden in header (scores + EKG lines only). Borough name label hidden.

---

## Environment Variables

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

In Docker, set to the API service's internal URL.
