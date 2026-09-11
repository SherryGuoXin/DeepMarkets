# Institution and security summary rollout

Both approved templates apply to all institution and security detail routes. No filing-data or ETL changes are required.

Before: generic entity descriptions and metric cards. After: visible summaries using each page's reporting period, Latest Filings date, non-option totals, existing activity classifications and supported highlights. The summaries contain no added links or explanatory notes.

## NVIDIA example

For the latest Q2 2026 SEC Form 13F reporting period, filed through September 8, 2026, NVIDIA CORPORATION (67066G104) had non-option positions reported by 5,969 institutional investment managers, totaling approximately $3.21 trillion. Compared with Q1 2026, 347 managers reported new positions, 2,976 increased their reported positions, 2,327 reduced their reported positions, and 120 no longer reported a position.

The total reported institutional share count changed by +490,449,654 shares from the previous quarter. NORGES BANK (CIK 0001374170) reported the largest quarter-over-quarter increase in reported shares, at approximately 325.95 million shares, while CALIFORNIA PUBLIC EMPLOYEES RETIREMENT SYSTEM (CIK 0000919079) reported the largest decrease, at approximately 22.26 million shares.

Title: NVIDIA CORPORATION (67066G104) Institutional Ownership & 13F Holders | 13FData

Meta description: NVIDIA CORPORATION (67066G104): 5,969 managers reported non-option holdings in Q2 2026. Explore 13FData's SEC Form 13F analysis and reported share changes. Partial coverage.

## Berkshire Hathaway example

For the latest Q2 2026 SEC Form 13F reporting period, filed through September 8, 2026, Berkshire Hathaway Inc (CIK 0001067983) reported 29 non-option positions with a total reported value of approximately $299.25 billion. Compared with Q1 2026, the filing included 1 new reported position, 7 position increases, 6 position reductions, and 1 reported exit.

Berkshire Hathaway Inc's largest reported position was APPLE INC, valued at approximately $65.95 billion. The largest quarter-over-quarter increase in reported position value was ALPHABET INC at approximately $12.56 billion, while OCCIDENTAL PETE CORP recorded the largest decrease at approximately $4.35 billion.

Notable people associated with Berkshire Hathaway Inc include Warren E. Buffett.

Title: Berkshire Hathaway Inc Q2 2026 13F Holdings & Portfolio | 13FData

Meta description: Berkshire Hathaway Inc (CIK 0001067983) reported 29 non-option positions valued at approximately $299.25 billion in Q2 2026. Explore its reported 13F holdings and position changes. Partial coverage.

## Implementation

The same summary is used in the API, React and initial HTML. Titles, descriptions, canonicals, Open Graph, Twitter metadata and JSON-LD stay aligned during client navigation and quarter selection. Security titles include CUSIPs to distinguish securities sharing an issuer.

Structured data describes WebPage, WebSite, Organization and a Dataset created by 13FData, based on SEC Form 13F source data. Dataset descriptions match visible summaries. No advice or recommendation markup was added.

Share comparisons use actual SH quantities, excluding principal amounts and options. Missing canonical share totals fall back to indexed, typed holdings data. Missing periods stay missing. Largest changes use signed values and existing comparability rules; new positions and exits are eligible, unknown comparisons are excluded and tied singular highlights are omitted.

Institution summaries use non-option instrument positions and dollar-value changes. Notable people appear only when stored in the database, separately from institutional activity. Missing prior-period comparisons and absent people are omitted. Historical selections are not labeled latest. The filed-through placeholder uses the Latest Filings feed date, following the user's approved wording.

Daily-only and historical daily-only entities now resolve through available summaries. Entity sitemaps merge canonical and daily records, deduplicated by CIK/CUSIP. Existing charts, tables, filters and routes remain in place.

## Files changed

- `app/backend/page_summary.py`: shared summaries and metadata.
- `app/backend/main.py`, `queries.py`: source facts and profile integration.
- `app/backend/seo.py`: initial HTML and structured data for every detail route.
- `app/backend/sitemaps.py`: daily and canonical entity discovery.
- `app/frontend/src/components/ReportedSummary.jsx`: visible paragraphs and metadata updates.
- `app/frontend/src/components/RouteSeo.jsx`, `app/frontend/src/seoMetadata.js`: shared metadata application.
- `app/frontend/src/pages/SecurityPage.jsx`, `InstitutionPage.jsx`: summary placement and descriptive headings.
- `app/frontend/src/styles.css`: compact summary typography.
- `app/README.md`: behavior documentation.
- `tests/test_page_summaries.py`, `test_entity_sitemaps.py`, `test_institution_summary_facts.py`, `test_security_share_comparison.py`: regression coverage.

## Validation

Frontend build and ESLint passed. All 27 focused tests passed: summary output/escaping, daily/canonical sources, options, principal amounts, unknown comparisons, signed extrema, ties, missing periods, arbitrary IDs, notable-person metadata and sitemap pagination/deduplication. Whitespace checks passed.

HTTP validation passed on 12 local detail pages: Berkshire, BlackRock, IMC, Alphabet, NVIDIA, Apple, SPY, a PRN-only note, a mixed-unit convertible, an option-only security, a new security and a historical daily-only security. Checks covered API/initial HTML/JSON-LD parity, one H1, canonicals, metadata and no added summary links. Historical quarter API behavior and daily-only sitemap entries were also verified.

Automated browser inspection was unavailable because the in-app browser connection failed. No visual or browser-interaction pass is claimed.

## Remaining scope

Other page types retain their existing content. Full tables and charts require JavaScript; the summaries do not. Relationship URLs remain absent from the sitemap. Dedicated person and quarter pages do not exist.

Existing wording outside these templates remains for separate review: homepage “building conviction,” and backend list-page metadata mentioning “buying” and “selling.” Search Console indexing was not changed by this rollout.
