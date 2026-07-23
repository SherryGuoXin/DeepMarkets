# Changelog

This file records material changes to the 13F ingestion programs, database
schema, derived tables, and external data sources. Downloaded SEC files and
generated databases are intentionally excluded from Git.

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
