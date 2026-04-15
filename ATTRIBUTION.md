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

- **MHCLG** — English Indices of Deprivation 2025 (IMD)
  https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025
  Borough-level deprivation ranks and domain sub-scores. Used for equity-aware prescriptions.

- **ONS Nomis** — Mid-year population estimates by London borough
  https://www.nomisweb.co.uk
  Used for per-capita crime normalisation. Free, no API key required.

- **findthatpostcode.uk** — Ward-to-borough geographic mapping
  https://findthatpostcode.uk
  Used once during setup to map E05 ward codes to E09 borough codes. Open-source ONS geography wrapper.

## Processing & Privacy

- Raw text from Guardian and BBC is scored locally using a sentiment model (`cardiffnlp/twitter-roberta-base-sentiment`) and is never sent to any external LLM or API.
- **Aggregated numerical scores** (0–100) reach the LLM (Claude Haiku 4.5) for agent responses via the gold_scores table.
- **Headline titles** (not article body text) and their per-title sentiment scores are stored in `silver_headlines` and may be returned to the LLM when the agent answers questions about public sentiment. Only titles from the sources listed above are stored; URLs are validated against a domain allowlist.
- **Contextual detail** (crime categories, tube line statuses, air quality station readings, NHS trust performance, ward-level green space coverage) is stored in `silver_detail` for agent breakdown queries. No raw article text, post bodies, or personally identifiable information is included.
- No personally identifiable information is collected, stored, or transmitted.
