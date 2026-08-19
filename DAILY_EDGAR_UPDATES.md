# Daily EDGAR updates

## Why

The SEC Form 13F bulk ZIPs are authoritative but delayed. Direct EDGAR XML
ingestion makes new `13F-HR` and `13F-HR/A` filings available daily. Later bulk
ZIPs are coverage backfills only: an accession already present is never
overwritten.

## What changed

- `etl/daily_edgar.py` reads the current quarterly `master.idx`, skips known
  accessions, downloads each new filing's primary and information-table XML,
  and atomically fills the existing seven raw SEC tables.
- `DAILY_EDGAR_RUN` and `DAILY_EDGAR_ACCESSION` record crawl status, source
  URLs, timestamps, and document hashes without altering the raw tables.
- Bulk imports now anti-join on `SUBMISSION.ACCESSION_NUMBER` and load only
  accessions absent from the database.

Set an SEC-compliant identity and run once per day:

```bash
export SEC_USER_AGENT="Company Name admin@example.com"
python3 etl/daily_edgar.py
```

Use `--year` and `--quarter` to repair an earlier quarter. The command rebuilds
derived data after importing; use `--skip-derived` when a separate job handles
that work.

## Rollback

The database changes are reversible because every daily-added accession is
tracked separately. Before the first production run, retain a normal SQLite
backup for the strongest point-in-time recovery guarantee.

```bash
sqlite3 form13f.sqlite3 ".backup 'form13f.before-daily.sqlite3'"
```

To remove all daily-added raw rows and drop the two provenance tables:

```bash
python3 etl/daily_edgar.py --database form13f.sqlite3 --rollback
python3 etl/bulk_etl.py --database form13f.sqlite3
```

Run rollback **before** switching back to code that does not contain this
feature. Existing bulk data is not deleted. The bulk rerun restores any daily
accessions that a previously completed ZIP had skipped, then rebuilds derived
data. Alternatively, restoring the pre-feature SQLite backup returns both raw
and derived data to the exact prior state.
