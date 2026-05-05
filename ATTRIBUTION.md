# Data Sources & Attribution

CityScan London uses publicly available data from the following sources. All data is used for non-commercial analytical purposes.

## Open Government License v3.0

The following sources publish data under the [Open Government License v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/):

- **Transport for London (TfL)** — Tube line service status
  https://tfl.gov.uk | [API documentation](https://api.tfl.gov.uk/)

- **UK Police Data** — Street-level crime data (Met Police)
  https://data.police.uk | [API documentation](https://data.police.uk/docs/)

- **NHS England** — A&E waiting times and activity statistics
  https://www.england.nhs.uk/statistics/

## CC-BY 4.0

- **OpenAQ** — Air quality monitoring data (PM2.5, NO2)
  https://openaq.org | [API documentation](https://docs.openaq.org/)
  Licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## API Terms of Service

- **The Guardian** — Headlines and trail text via Guardian Open Platform
  https://www.theguardian.com | [API terms](https://open-platform.theguardian.com/access/)
  Headlines are linked to original articles. Full article text is never stored or republished.

- **BBC News** — London headlines via public RSS feed
  https://www.bbc.co.uk/news | [RSS terms](https://www.bbc.co.uk/terms)
  Only article titles and descriptions are used. Full article text is never stored.

- **Reddit** — Post titles from r/london via public JSON endpoint
  https://www.reddit.com | [User Agreement](https://www.redditinc.com/policies/user-agreement)
  Only post metadata (title, score, timestamp) is collected. Post body text is never stored.
  *Note: Reddit's public JSON API has been returning 403 since April 2026. Ingestion code is retained but currently inactive. Sentiment scoring runs on Guardian + BBC only.*

## Open Data (London)

- **Greater London Authority (GLA)** — Green Cover 2024 (satellite imagery + NDVI classification)
  https://data.london.gov.uk/dataset/green-cover-2024-e56n0/
  Borough and ward-level green space coverage percentages.

- **Greater London Authority (GLA)** — London Atmospheric Emissions Inventory (LAEI) 2022, modelled population-weighted PM2.5 / NO2 annual mean
  https://data.london.gov.uk/dataset/london-atmospheric-emissions-inventory-laei-2022/
  Used as `air_quality_modelled_score` for full 33/33 borough coverage alongside live OpenAQ readings. 2022 is the latest published edition.

- **Transport for London (TfL)** — Public Transport Accessibility Levels (PTAL) 2015 borough averages
  https://data.london.gov.uk/dataset/public-transport-accessibility-levels
  Borough-level Average Public Transport Accessibility Index (AvPTAI) and band 1a–6b. Used as the SDG 11.2 access measure. PTAL is republished only on major TfL network changes; 2015 is the most recent borough-average edition (predates the 2022 Elizabeth Line opening, which is disclosed where relevant).

- **MHCLG** — English Indices of Deprivation 2025 (IMD)
  https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025
  Borough-level deprivation ranks and domain sub-scores. Used for equity-aware analysis (overall IMD plus 7 sub-domains: income, employment, education, health, crime, barriers, living).

- **ONS** — Health Index for England (Table 2 — overall index scores)
  https://www.ons.gov.uk/peoplepopulationandcommunity/healthandsocialcare/healthandwellbeing/datasets/healthindexscoresengland
  Composite index covering 2015–2021 (England 2015 = 100 baseline) at Lower-Tier Local Authority level. Built from inputs that don't appear in the CityScan pipeline (life expectancy, mortality, mental-health prevalence, behaviours), so used as an external convergent-validity reference for CityScan composite scores. ONS excludes City of London from this dataset by convention; 32 boroughs covered.

- **ONS** — House Price to Workplace-Based Earnings Ratio 2025 (Table 5c, median)
  https://www.ons.gov.uk/peoplepopulationandcommunity/housing/datasets/ratioofhousepricetoworkplacebasedearningslowerquartileandmedian
  Annual median house price ÷ median workplace-based gross annual earnings, by Local Authority District (year ending September of the latest published vintage; CityScan refreshes once per year on ONS re-publication). Used as a London-specific affordability overlay on the analytics scatter chart (alternate X-axis to IMD rank). Note: workplace-based, not residence-based — captures price relative to where people work, which is more conservative for inner-London boroughs with high commuter inflows.

- **ONS Nomis** — Mid-year population estimates at borough level (dataset NM_31_1) and ward level (dataset NM_2014_1, geography TYPE182 "Wards as of May 2025")
  https://www.nomisweb.co.uk
  Borough populations are used for per-capita crime normalisation. Ward populations power the access-weighted green-space metric (Σ ward green_pct × ward pop / Σ ward pop per borough). Free, no API key required.

- **findthatpostcode.uk** — Ward-to-borough geographic mapping
  https://findthatpostcode.uk
  Used once during setup to map E05 ward codes to E09 borough codes. Open-source ONS geography wrapper.

## Processing & Privacy

- Raw text from Guardian and BBC is scored locally using a sentiment model (`cardiffnlp/twitter-roberta-base-sentiment`) and is never sent to any external LLM or API.
- **Aggregated numerical scores** (0–100) reach the LLM (Claude Haiku 4.5) for agent responses via the gold_scores table.
- **Headline titles** (not article body text) and their per-title sentiment scores are stored in `silver_headlines` and may be returned to the LLM when the agent answers questions about public sentiment. Only titles from the sources listed above are stored; URLs are validated against a domain allowlist.
- **Contextual detail** (crime categories, tube line statuses, air quality station readings, NHS trust performance, ward-level green space coverage) is stored in `silver_detail` for agent breakdown queries. No raw article text, post bodies, or personally identifiable information is included.
- No personally identifiable information is collected, stored, or transmitted.
