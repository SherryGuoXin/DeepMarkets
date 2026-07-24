# ETL commands

Run the complete quarterly pipeline from the project root with one command:

```bash
python3 etl/run_etl.py raw_date/2013q4_form13f.zip
```

The driver derives an extraction directory such as `raw_date/2013Q4`, checks
and extracts the ZIP, records its SHA-256 and source row counts, atomically
appends all seven original SEC TSV tables, rebuilds CIK/ticker/SIC/division
data, rebuilds CUSIP dimensions, resolves filing amendments, and runs final
security classification, instrument, quarterly relationship, summary,
foreign-key, and integrity checks.

The driver is idempotent by ZIP hash. If a completed data set is passed again,
it verifies the database row counts and skips the raw append. A partial overlap
is rejected.

If the raw append succeeded but a later enrichment step was interrupted, rerun
only the enrichments:

```bash
python3 etl/run_etl.py raw_date/2013q4_form13f.zip --skip-import
```

Use `--replace-extracted` when the existing extracted directory must be
replaced from the ZIP. Run `python3 etl/run_etl.py --help` for path overrides.

The individual programs remain available for maintenance:

```bash
python3 etl/import_13f.py --help
python3 etl/enrich_cik.py --help
python3 etl/enrich_cusip.py --help
python3 etl/enrich_sic.py --help
python3 etl/build_canonical_filings.py --help
python3 etl/build_instruments.py --help
python3 etl/bulk_etl.py --help
```

To download all published quarterly data sets, append only missing raw batches,
and rebuild the derived layers once:

```bash
python3 etl/bulk_etl.py
```

Downloads are resumable and ZIP-validated. Extracted TSV directories are
removed after successful imports by default; pass `--keep-extracted` to retain
them. The program skips completed ZIP hashes and is safe to resume.

The SEC `01jun2025-31aug2025` archive has a nested top-level directory, which
the extractor normalizes automatically. It also contains one blank
`INFOTABLE.NAMEOFISSUER` despite that field being marked required in the SEC
metadata. The importer preserves this as-filed blank as an empty string rather
than inventing an issuer name or weakening the documented raw schema.

The CUSIP rebuild forces a direct raw information-table scan. Raw rows are
physically clustered by accession, keeping the cover-page join local without
requiring a separate table lookup through the CUSIP or primary-key indexes.
Variant counts use a single indexed upsert. This avoids the random cover-page
lookup and correlated update plans that become prohibitively slow across the
complete history. The raw ingestion contract is append-only, so existing CUSIP
variants are never deleted during a refresh.

If a complete-history derived rebuild is interrupted, resume from the first
unfinished stage without redownloading or reimporting raw data. For example:

```bash
python3 etl/bulk_etl.py --derived-only --start-derived cusip
```

Large full-history groupings use SQLite disk-backed temporary storage to avoid
unbounded RAM and swap growth. Ensure the database volume has substantial free
space before rebuilding all derived layers.
