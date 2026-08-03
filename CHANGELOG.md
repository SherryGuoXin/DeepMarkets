# Changelog

This file records material changes to the 13F ingestion programs, database
schema, derived tables, and external data sources. Downloaded SEC files and
generated databases are intentionally excluded from Git.

## 2026-07-31

### Search indexing

- Added server-rendered titles, descriptions, canonical URLs, social metadata,
  structured data and crawlable page summaries for public application routes.
- Resolved institution, security and relationship metadata from the analytical
  database so detail pages identify the actual manager and issuer before the
  React application loads.
- Added a dynamic sitemap index covering 13,106 institution pages and 159,994
  security pages in files below the 50,000-URL sitemap limit.
- Added valid `HEAD` responses for public pages, sitemaps and the health check;
  unknown application routes now return HTTP 404 with `noindex` metadata.
- Added the required description to the nested `Dataset` structured-data item
  so it passes Google Search's dataset eligibility validation.
- Declared the SEC dataset creator as the Google-supported `Organization` type
  instead of the narrower Schema.org `GovernmentOrganization` subtype.
- Removed `ProfilePage` and generic `Thing` `mainEntity` markup from independent
  institution, security and relationship records; these are now accurately
  represented as `WebPage` items rather than affiliated-user profiles.

## 2026-07-29

### Site identity

- Added a reproducible production SSH policy that disables password,
  keyboard-interactive, root and X11 access, limits authentication attempts,
  and permits only the Ubuntu administration account.
- Enabled a deny-by-default host firewall for rate-limited SSH and public
  HTTP/HTTPS, preserved TLS across future releases, and added one-year HSTS.
- Changed deployment activation to validate the API through local HTTPS when a
  certificate is installed instead of accepting the HTTP redirect as health.
- Migrated the deployed hostname, canonical URLs, legal copy, crawler files,
  trusted hosts and server configuration from `13f-data.com` to `13fdata.net`.

- Renamed the application and public-facing references to `13f-data.com`,
  including browser metadata, API metadata, documentation and legal copy.
- Replaced the navigation wordmark tile with the supplied site icon while
  retaining the same image for browser and Apple touch icons.
- Replaced the original PNG brand asset with the supplied SVG in the navigation,
  browser favicon and Apple touch icon metadata.
- Clarified on the homepage that all displayed data and analysis derive from
  SEC Form 13F filings, and that holdings, values and changes follow the
  selected and applicable comparison-quarter reports.
- Renamed the homepage institution snapshot to “Largest institutions holding
  reports” and removed the obsolete issuer-mapping notice from the Securities
  directory.
- Added route-specific SEO titles, descriptions, SEC Form 13F keyword metadata,
  canonical URLs, social-sharing tags and structured WebPage/Dataset data for
  the overview, institution, security, relationship, comparison, activity and
  disclaimer pages.
- Added crawler directives and a sitemap for the public site routes.
- Added a production Ubuntu release builder, hardened systemd service, Nginx
  reverse proxy, environment template, database activation checks and deployment
  documentation. Runtime archives exclude the database, ETL code and SEC source
  files.
- Disabled interactive API documentation in production, restricted accepted
  hostnames and removed the local database path from the public health response.
- Added a hash-verified activation mode for large databases on low-throughput
  server disks while retaining required-table and live-query validation.

### Base-security and option separation

- Separated non-option, call, and put exposure throughout the security profile
  and institution/security relationship workflows.
- Defined security-holder actions and activity counts from the non-option
  instrument only; call and put values remain visible but no longer affect the
  base action.
- Added base-only ownership and relationship history plus independently listed
  call and put quantities and values.
- Added explicit UI notices that quantity actions are not value-based and are
  not adjusted for stock splits.
- Added materialized CUSIP/quarter/option-type and base-action summaries so
  instrument separation does not reaggregate the full fact history at request
  time.
- Changed comparison movers to calculate directly from any two selected
  quarterly position snapshots instead of requiring an adjacent-quarter change
  record. Arbitrary-quarter actions use base-security quantities only and
  remain explicitly non-split-adjusted.
- Refined confidential-omission handling for comparisons: disclosed positions
  present in both selected quarters remain comparable, while `UNKNOWN` is
  reserved for a position missing from a quarter that reports omissions.
- Removed the frontend SIC aggregation page and navigation entry because most
  filing-manager CIKs remain unclassified. The underlying SIC data and API are
  retained for future enrichment.
- Removed classification confidence and the pending ticker/sector/industry
  notice from the Security identity panel.
- Removed FIGI from the Security identity panel and changed its remaining four
  fields to a complete two-column grid without an empty gray cell.
- Reversed the navigation to a dark, high-contrast palette, expanded both
  homepage leader snapshots to ten rows, and replaced identifier-heavy homepage
  copy with softer capital-flow messaging.
- Replaced the footer market-price note with a dedicated Disclaimers page
  covering informational use, no professional advice, SEC public-data
  attribution, third-party rights, processing limitations, no warranties,
  limitation of liability, external links and service availability.
- Added the supplied project artwork as the browser favicon and Apple touch
  icon.
- Reworked the Disclaimers page as a single formal legal document with numbered
  provisions and expanded Form 13F data, processing, warranty, liability and
  third-party-service limitations.
- Kept option strike and expiration detail out of scope because those fields
  are not available in the Form 13F source data.

## 2026-07-24

### API performance materialization

- Added materialized manager-quarter and CUSIP-quarter activity tables derived
  from `CIK_INSTRUMENT_CHANGE` so ranking filters and sorts no longer regroup
  tens of millions of change rows at request time.
- Added action-level activity summary tables for institution and security
  profile cards.
- Added `etl/build_api_activity.py` to rebuild the API activity layer
  quarter-by-quarter with progress output and per-quarter commits.
- Rewired institution/security ranking, history, and activity SQL to read the
  materialized summaries.
- Added relationship-oriented indexes and forced the security-holder endpoint
  to start from the selected CUSIP before reading quarter facts.

### Frontend workflow completeness

- Added quarter-to-quarter comparison APIs and a Compare page for institution
  CIKs and security CUSIPs.
- Added a position Activity page for new, exited, added, reduced, unchanged,
  and unknown adjacent-quarter relationship changes.
- Added SEC SIC aggregation APIs and an SIC page that groups filing managers
  by SEC division and industry.
- Wired Compare, Activity, and SIC into the React routes and top navigation.
- Kept SIC aggregation scoped to filing-manager classifications; held-security
  sector mapping remains intentionally separate until a CUSIP/issuer sector
  source is added.

## 2026-07-23

### Complete historical bulk ingestion

- Added a resumable bulk downloader/importer for every SEC Form 13F data-set
  ZIP published from 2013Q2 through May 2026.
- Deferred expensive dimension, amendment, instrument, summary, and motion
  rebuilds until all missing raw batches are atomically appended.
- Normalized the SEC June–August 2025 archive's nested directory layout.
- Preserved its single as-filed blank `NAMEOFISSUER` as an empty string because
  the SEC metadata marks the raw column required; no issuer value is invented.
- Optimized full-history CUSIP rebuilding with accession-clustered raw scans
  and indexed variant upserts, replacing random cover-page lookups and
  correlated per-variant updates.
- Added derived-only stage recovery so an interrupted full-history rebuild can
  resume without downloading or importing raw data again.
- Switched large derived-table temporary groupings to disk-backed storage to
  bound memory pressure, and consolidated canonical holding counts into one
  full-history pass.
- Materialized the one-row-per-CUSIP current variant with primary, foreign, and
  issuer indexes so application queries do not rerank 17.7 million historical
  variants on every request.

### Local intelligence application

- Added a read-only FastAPI backend with reviewable SQL for overview,
  institution, security, holding, ownership, activity, allocation, history,
  relationship, leaderboard, filtering, pagination, and global-search
  components.
- Added a responsive React interface for institution lists and profiles,
  security lists and profiles, and the shared institution/security
  relationship page.
- Added portfolio and ownership history charts, activity summaries, asset-type
  allocation, behavior metrics, holdings/holder tables, SEC filing links, and
  explicit data-availability notices.
- Added a one-command local launcher that builds the frontend and serves the
  application against SQLite in read-only mode.
- Added server-side ascending/descending sorting for every institution and
  security ranking-table column, plus portfolio, holding, ownership, activity,
  concentration, security-class, and value-change filters applied before
  pagination.
- Replaced overview-page calls into full activity rankings with indexed,
  purpose-built top-five summary queries so the landing page remains responsive
  across the complete history.

### ETL provenance and canonical filings

- Added ZIP SHA-256, source row counts, database row counts, batch status, and
  accession lineage through `ETL_BATCH`, `ETL_BATCH_TABLE_COUNT`, and
  `ETL_BATCH_ACCESSION`.
- Made quarterly imports idempotent: a completed ZIP is validated and skipped,
  while partial accession overlap is rejected.
- Added ISO filing dates and a sortable `QUARTER` dimension that distinguishes
  report quarters from source ZIP names.
- Added deterministic amendment resolution for base reports, restatements, and
  new-holdings additions, with review and incomplete-history statuses.
- Added `FILING_OVERRIDE` for reviewed corrections to as-filed amendment types.
- Added canonical holding views that normalize pre-2023 values from thousands
  of dollars to dollars while preserving the original reported value.

### Instruments and quarterly relationship facts

- Added a controlled security-type taxonomy, ordered classification rules,
  CUSIP-level reviewed overrides, weighted CUSIP classifications, and stable
  instrument surrogate keys.
- Kept common shares, calls, puts, and principal amounts in separate
  instruments even when they share one CUSIP.
- Added stable CIK/instrument relationships and one materialized position per
  relationship and report quarter.
- Added manager-quarter and CUSIP-quarter summaries with normalized value
  breakdowns, concentration metrics, shared-discretion/confidential flags, and
  propagated value-quality status.
- Added adjacent-quarter CIK/instrument changes with inferred position actions;
  missing quarters do not create exits, and confidential comparisons are
  retained as explicitly non-comparable.
- Integrated instrument and summary rebuilding into the unified ETL driver.

## 2026-07-22

### Unified ETL driver

- Moved the Python ETL programs into the `etl/` package.
- Added `etl/run_etl.py` to extract a quarterly SEC ZIP, append all original
  tables, rebuild CIK/ticker/SIC/division data, rebuild CUSIP dimensions, and
  run final database checks with one command.
- Added safe ZIP path validation, required-file validation, automatic
  `raw_date/YYYYQ#` extraction-directory naming, and a `--skip-import` recovery
  option for rerunning enrichments after an interrupted workflow.
- Updated all standalone program defaults to resolve project data and schema
  paths correctly from their new directory.

## 2026-07-17

### Repository and ingestion

- Initialized the project as a Git repository.
- Added `import_13f.py` to create the original SEC Form 13F schema and load the
  tab-separated source files into SQLite.
- Loaded the latest available Form 13F dataset and the 2013 Q2 dataset into the
  corresponding original-schema tables.
- Kept SEC accession numbers and other source identifiers as supplied rather
  than treating later rows as replacements merely because they occur later in
  a filing.

### CIK enrichment

- Added `enrich_cik.py` and the `CIK` and `CIK_TICKER_EXCHANGE` tables.
- Used SEC `company_tickers_exchange.json` for company name, ticker, and
  exchange data.
- Preserved multiple ticker/exchange pairs for a CIK in
  `CIK_TICKER_EXCHANGE`.
- Added relationships between CIKs and original 13F filing-manager and
  other-manager records.

### CUSIP enrichment

- Added `enrich_cusip.py` and integer surrogate keys for the `CUSIP`,
  `CUSIP_VARIANT`, and current-variant data model.
- Removed time-varying aggregate counts from the stable `CUSIP` dimension.
- Recorded issuer-name, title-of-class, and FIGI variants using the filing
  report calendar or quarter to establish their observed periods.

### SIC enrichment and division classification

- Added `enrich_sic.py` to read current `sic` and `sicDescription` values from
  the SEC Submissions bulk archive and populate `CIK_TICKER_EXCHANGE`.
- Added `SIC_AS_OF_DATE` and `SIC_SOURCE` so the mutable SEC classification has
  explicit snapshot provenance.
- Added `SIC_MAJOR_GROUP_DIVISION`, derived from the first two SIC digits using
  the official 1987 SIC division ranges.
- Updated both `enrich_sic.py` and `enrich_cik.py` so SIC divisions are
  populated during either a SIC refresh or a complete CIK/listing rebuild.
- Left missing SIC values and SIC `0000` without an assigned division.
- Verified a complete rebuild with 10,428 listing rows, 9,084 rows containing
  SIC values, 9,074 rows assigned to divisions, and a successful SQLite
  integrity check.

### Documentation and repository hygiene

- Added `schema.sql` as the reproducible database definition.
- Added `DATA_DICTIONARY.md` documenting enrichment-table fields, sources,
  conflicts, and special treatments.
- Added `.gitignore` rules for downloaded/extracted SEC source data, ZIP files,
  generated SQLite databases, Python caches, and local scratch files.
