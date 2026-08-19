# Daily EDGAR updates

## Why

The SEC Form 13F bulk ZIPs are authoritative but delayed. Direct EDGAR XML
ingestion makes new `13F-HR` and `13F-HR/A` filings available daily. Later bulk
ZIPs are coverage backfills only: an accession already present is never
overwritten.

## What changed

- `etl/daily_edgar.py` reads the current quarterly `master.idx`, skips known
  accessions, downloads each new filing's primary and information-table XML,
  and atomically fills the existing seven raw SEC tables. Each accession is
  committed to SQLite as soon as that filing has downloaded and parsed.
- `DAILY_EDGAR_RUN` and `DAILY_EDGAR_ACCESSION` record crawl status, source
  URLs, timestamps, and document hashes without altering the raw tables.
- Daily runs publish separate `DAILY_CIK_*` holdings, summaries, activity, and
  quarter-status tables. Only the institution list and institution profile
  views/charts read this partial-quarter layer. Security, relationship,
  overview, comparison, and market-wide activity pages remain pinned to the
  latest completed SEC bulk quarter.
- The institution quarter selector and profile notice label this data
  `Partial`. A completed bulk import rebuilds all global analytics, promotes
  the quarter to `Complete`, and removes its temporary daily materializations.
- Bulk imports now anti-join on `SUBMISSION.ACCESSION_NUMBER` and load only
  accessions absent from the database.

Set an SEC-compliant identity and run once per day:

```bash
export SEC_USER_AGENT="Company Name admin@example.com"
python3 etl/daily_edgar.py
```

Use `--year` and `--quarter` to repair an earlier quarter. The command refreshes
CIK identities, canonical filings, and the partial institution layer after the
download; it deliberately does not rebuild global security/relationship
analytics. Use `--skip-derived` to update only the raw database. A later normal
run will publish any previously skipped institution update even when it finds
no new accessions.

## Rollback

The database changes are reversible because every daily-added accession is
tracked separately. Before the first production run, retain a normal SQLite
backup for the strongest point-in-time recovery guarantee.

```bash
sqlite3 form13f.sqlite3 ".backup 'form13f.before-daily.sqlite3'"
```

To remove all daily-added raw rows and drop the provenance and partial
institution tables:

```bash
python3 etl/daily_edgar.py --database form13f.sqlite3 --rollback
python3 etl/bulk_etl.py --database form13f.sqlite3
```

Run rollback **before** switching back to code that does not contain this
feature. Existing bulk data is not deleted. The bulk rerun restores any daily
accessions that a previously completed ZIP had skipped, then rebuilds derived
data. Alternatively, restoring the pre-feature SQLite backup returns both raw
and derived data to the exact prior state.
