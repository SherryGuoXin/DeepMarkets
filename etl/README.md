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
```
