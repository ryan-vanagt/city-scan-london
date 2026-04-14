# CityScan London — Competition Roadmap

**Competition:** Analytics for Society Awards 2026 (UCL School of Management + Imperial Gandhi Centre + IoA)
**Deadline:** April 18 2026 (MVP submission) | May 7 2026 (Final presentation)
**SDG Focus:** SDG 11 — Sustainable Cities and Communities (targets 11.6, 11.2, 11.7, 11.3, 11.9)

---

## Narrative

> London is a living organism. Its lungs choke on pollution, its arteries seize during rush hour, its immune system fights crime and A&E overload, its brain reflects collective mood, and its skin — green space — is where the city breathes.
>
> CityScan models London as a human body. Five biological systems, seven public data sources, 33 boroughs scored 0-100 in real time. Not just a dashboard — a diagnostic and treatment system that prescribes data-driven policy interventions aligned with UN SDG 11.
>
> The boroughs that score worst are also the most deprived. Inequality isn't abstract — it's visible on the thermal map.

---

## Two-Stage Delivery

### Stage 1: MVP Submission (April 18)

**Already live:**
- 4 organs (Lungs, Arteries, Brain, Immune) with real-time data from 7 public APIs
- Thermal borough map with medical scan aesthetic (X-ray landing -> live thermal flood)
- "City Doctor" NLP agent (natural language queries, SSE streaming, 6 tools)
- Daily LLM-generated health bulletin with source attribution
- MCP server for external agent integration
- Docker deployment (5 services, single `docker compose up`)

**Done:**
- Per-capita crime normalisation — ONS population data, winsorised at 95th percentile

**Building by April 16:**
- Green Space organ ("Skin") — London Datastore data (TBC after data spike), SDG 11.7
- IMD deprivation data + Doctor tool — equity-aware prescriptions (SDG 11.3, 11.9). Not scored, fuels the prescriptive layer.
- Prescriptive policy layer — Doctor and Bulletin recommend evidence-based "treatments" per borough (co-designed after all organs exist)

**Explaining as roadmap (for May 7):**
- Radar/pentagon chart for borough comparison
- IMD frontend overlay on thermal map
- Structured "Treatment Plan" agent output

### Stage 2: Final Presentation (May 7)

Everything from Stage 1, plus:
- Radar chart (Recharts pentagon per borough, all 5 organs at a glance)
- IMD frontend overlay on map (toggle, hatching/border visual)
- Treatment Plan feature (structured: Diagnosis -> Prognosis -> Prescriptions)
- Polished video with live demo walkthrough

---

## Implementation Phases

### Phase 0: Doc Updates (Apr 14) — DONE
Update README, CLAUDE.md with competition framing. Create skeleton files for competition artifacts.

### Phase 1: Per-Capita Crime Normalisation (Apr 14) — DONE
**Impact:** Fixes analytical flaw (Westminster foot traffic != resident danger). Credibility with judges.

| Change | File | Status |
|--------|------|--------|
| Borough population data (ONS Nomis API) | `scripts/fetch_population.py` → `pipeline/lookups.json` | Done |
| Per-capita rates (crimes per 1,000 residents) | `pipeline/silver.py` (`_transform_met_police`) | Done |
| Winsorisation at 95th percentile | `pipeline/silver.py` | Done |

City of London (15k residents, 500k daily workers) was capping the scale at 154/1k. Winsorisation at P95 restores full 0-100 spread. Score range verified: 0.0 (Westminster/City of London) to 100.0 (Richmond).

### Phase 2: Green Space Organ (Apr 15-16) — ~8h
**Impact:** 5th organ = SDG 11.7 alignment. Pentagon radar becomes possible.

Data spike FIRST: verify London Datastore availability, inspect fields/ranges, then decide scoring formula.

Touches every layer: fetcher -> silver -> gold -> schema -> scheduler -> API -> agent tools -> embedding -> frontend.

| Layer | Key change |
|-------|-----------|
| Bronze | `ingestion/sources/green_space.py` — reads static JSON or London Datastore CSV |
| Silver | `pipeline/silver.py` — `_transform_green_space()`, scoring TBC after data spike |
| Gold | `pipeline/gold.py` — weights 4->5 (0.20 each), add green_space_score to aggregate |
| Schema | `pipeline/schemas.py` — DDL column + ALTER TABLE migration |
| API | `api/routers/health.py`, `boroughs.py` — add to SELECT + response |
| Agent | `agents/tools/*.py` — add to valid metrics, update docstrings |
| Frontend | types.ts, VitalSigns.tsx, EkgLine.tsx, BoroughTooltip.tsx |

### Phase 2b: IMD Deprivation Data + Doctor Tool (Apr 16) — ~2h
**Impact:** Enables equity-aware prescriptions. Fuels SDG 11.3 and 11.9 narrative.

Data spike FIRST: verify MHCLG IMD availability, check if borough-level aggregation exists.

NOT a scored organ. Static JSON + Doctor Agent tool + system prompt context.

### Phase 3: Prescriptive Reframe (Apr 16) — ~3h
**Impact:** Transforms dashboard -> decision-support system. Highest ROI for Solution score.

Co-designed (not implemented solo). Done AFTER all organs exist so prompts reference real data.

**Design:** LLM does NOT freestyle policy. System prompt embeds a **constrained intervention menu** — evidence-based policies referencing real London strategy documents. The LLM selects, contextualises, and cites. Per organ:

- Lungs (11.6): ULEZ expansion (Mayor's Transport Strategy), cycling infra (TfL Cycling Action Plan), green corridors (London Environment Strategy), school-gate monitors (GLA Air Quality Audit)
- Arteries (11.2): bus bridges for disrupted lines, Overground/DLR extension studies (TfL Business Plan), bus frequency review (TfL Bus Action Plan)
- Skin (11.7): pocket parks (London Plan G4), green roofs (London Plan G5), community gardens (London Plan G8)
- Brain: public realm improvements (Healthy Streets Approach), community engagement (GLA Talk London)
- Immune: Safer Neighbourhood Teams (Met Police Ward Panels), urgent treatment centres (NHS Long Term Plan), early intervention (Marmot Review 2020)

Each prescription must cite the data point that triggered it + the policy reference.

### Phase 4: Competition Artifacts (Apr 16-17) — ~4h

| Artifact | Location | Notes |
|----------|----------|-------|
| 400-word summary | `docs/competition/summary_400w.md` | Required submission |
| Video script (5 min) | `docs/competition/video_script.md` | Timing cues, demo flow |

### Phase 5: Post-MVP Polish (Apr 18 - May 7)

| Feature | Effort | Impact |
|---------|--------|--------|
| Radar/pentagon chart (Recharts) | Medium | Strong visual for final presentation |
| IMD frontend overlay on map | Medium | Visual equity layer |
| MCP server: expose new tools | Low | Completeness |
| Video recording + polish | High | Required |

---

## Scoring Discussion

### Approach: Data-First

Scoring formulas are TBC until we fetch the actual data and inspect it. Each new source gets a spike: fetch -> inspect distribution -> pick formula.

### Green Space — TBC After Data Spike

Need to verify what's actually available (London Datastore, GLA reports, etc.), what granularity (borough-level or needs aggregation), and what the value ranges look like before committing to a formula.

### Equity — Prescriptive Fuel, Not Organ

Deprivation is structural — boroughs can't "fix" their IMD in a year. Scoring it as an organ would penalise deprived boroughs twice. Instead, IMD data fuels the prescriptive layer: "prioritise interventions in the most deprived boroughs." This hits SDG 11.3 (inclusive urbanisation) and 11.9 (policies for inclusion).

### Weights — Equal (0.20 each)

With 5 organs: 0.20 each. Equal weights are easiest to defend ("we let the data speak"). Configurable via SCORE_WEIGHTS env var.

---

## SDG 11 Target Alignment

| Target | Description | CityScan Coverage | Organ/Layer |
|--------|-------------|-------------------|-------------|
| **11.6** | Reduce environmental impact (air quality) | PM2.5/NO2 monitoring from OpenAQ | Lungs |
| **11.2** | Sustainable transport systems | TfL tube line status scoring | Arteries |
| **11.7** | Green and public spaces | Green cover % per borough | Skin |
| **11.3** | Inclusive urbanisation | IMD deprivation context for prescriptions | Overlay |
| **11.9** | Policies for inclusion | Evidence-based intervention menu | Prescriptive layer |

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Green space data unavailable online | Fallback: static JSON with GLA report values |
| IMD data not borough-level | Aggregate from LSOA level, or use pre-aggregated summary |
| DDL migration breaks existing DuckDB | ALTER TABLE IF NOT EXISTS in init_db |
| 5-metric header crowded on mobile | Reduce EKG width, test responsive |
| Existing SCORE_WEIGHTS env (4 values) breaks | Graceful fallback to new defaults + warning |
| Video takes longer than expected | Record MVP demo early (Apr 16), polish later |
