# Daily EDGAR updates

## Why

The SEC Form 13F bulk ZIPs are authoritative but delayed. Direct EDGAR XML
ingestion makes new `13F-HR` and `13F-HR/A` filings available daily. Later bulk
ZIPs are coverage backfills only: an accession already present is never
overwritten.

## What changed

- `etl/daily_edgar.py` reads the current quarterly `master.idx`, skips known
  accessions, processes the newest filings first, and atomically fills the
  seven raw SEC tables. Each accession is committed as soon as it parses, so
  the Latest Filings page can show it before derived analytics are ready.
- `DAILY_EDGAR_RUN` and `DAILY_EDGAR_ACCESSION` record crawl status, source
  URLs, progress, timestamps, and document hashes. `DAILY_EDGAR_PUBLICATION`
  records retry-safe derived-publication checkpoints.
- `LATEST_FILING_FEED` materializes the API-ready filing rows and date order.
  Daily publication refreshes only affected manager-quarters; a completed bulk
  rebuild refreshes the full feed.
- Derived data publishes in batches of 100 filings by default. Each batch
  refreshes only the affected manager CIKs and report quarters; it does not
  rebuild complete filing history or global analytics.
- New daily-only CUSIPs use the same conservative title rules as the quarterly
  classifier, so recognized holdings do not wait for the next bulk rebuild.
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

Production uses `13f-data-daily.timer`: 10:00 PM Toronto time on weekdays, with
a 7:00 AM retry Tuesday through Saturday. Each run takes Nginx and the API
offline before writing, publishes affected institutions in batches of 50, and
restores both services even when SEC requests fail. Configure `SEC_USER_AGENT`
in `/etc/13f-data/13f-data.env`; inspect runs with:

```bash
systemctl list-timers 13f-data-daily.timer
journalctl -u 13f-data-daily.service
```

Use `--year` and `--quarter` to repair an earlier quarter. The command refreshes
affected CIK identities, canonical filings, and partial institution rows as
each publication batch completes. Change the batch size with
`--publish-batch-size 50`. Use `--skip-derived` for raw-only ingestion; a later
normal run resumes unpublished checkpoints even if no new filings are found.

Run the focused regression tests with:

```bash
python3 -m unittest discover -s tests -v
```

Backfill the materialization once when upgrading an existing database:

```bash
python3 etl/build_latest_filings.py --database form13f.sqlite3
```

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
