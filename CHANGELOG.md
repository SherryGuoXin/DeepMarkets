# Changelog

This file records material changes to the 13F ingestion programs, database
schema, derived tables, and external data sources. Downloaded SEC files and
generated databases are intentionally excluded from Git.

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
