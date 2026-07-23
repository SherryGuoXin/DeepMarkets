#!/usr/bin/env python3
"""Extract and append one SEC Form 13F ZIP, then rebuild enrichments."""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path, PurePosixPath

try:
    from . import (
        build_canonical_filings,
        build_instruments,
        enrich_cik,
        enrich_cusip,
        etl_metadata,
        import_13f,
    )
except ImportError:  # Allow direct execution: python3 etl/run_etl.py
    import build_canonical_filings
    import build_instruments
    import enrich_cik
    import enrich_cusip
    import etl_metadata
    import import_13f


PROJECT_DIR = Path(__file__).resolve().parent.parent
REQUIRED_SOURCE_FILES = tuple(f"{table}.tsv" for table in import_13f.TABLES)


def default_extract_dir(zip_path: Path) -> Path:
    match = re.search(r"(?i)(\d{4})q([1-4])", zip_path.stem)
    name = f"{match.group(1)}Q{match.group(2)}" if match else zip_path.stem
    return PROJECT_DIR / "raw_date" / name


def validate_source_dir(source_dir: Path) -> None:
    missing = [name for name in REQUIRED_SOURCE_FILES if not (source_dir / name).is_file()]
    if missing:
        raise ValueError(
            f"{source_dir} is missing required files: {', '.join(missing)}"
        )


def extract_dataset(zip_path: Path, destination: Path, replace: bool) -> Path:
    if not zip_path.is_file():
        raise FileNotFoundError(f"ZIP does not exist: {zip_path}")

    if destination.exists() and not replace:
        validate_source_dir(destination)
        print(f"Using existing extracted directory: {destination}", flush=True)
        return destination

    temporary = destination.with_name(destination.name + ".extracting")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"ZIP CRC check failed for {bad_member}")
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"unsafe ZIP member path: {member.filename}")
            archive.extractall(temporary)
        validate_source_dir(temporary)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(f"Extracted {zip_path} to {destination}", flush=True)
    return destination


def verify_database(database: Path) -> None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:5]}"
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    finally:
        connection.close()


def run(
    zip_path: Path,
    database: Path,
    extract_dir: Path,
    listings: Path,
    sic_cache: Path,
    replace_extracted: bool,
    skip_import: bool,
) -> None:
    source_dir = extract_dataset(zip_path, extract_dir, replace_extracted)

    if skip_import:
        print("Skipping raw-table append", flush=True)
    else:
        print("\n[1/5] Registering and appending original SEC tables", flush=True)
        batch_id, should_append = etl_metadata.prepare_batch(
            database, zip_path, source_dir
        )
        if should_append:
            try:
                import_13f.append_database(source_dir, database)
                etl_metadata.complete_batch(database, batch_id, source_dir)
            except Exception as error:
                etl_metadata.fail_batch(database, batch_id, error)
                raise
        else:
            print(
                f"ETL batch {batch_id} is already present; raw append skipped",
                flush=True,
            )

    print("\n[2/5] Rebuilding CIK, ticker, SIC, and division data", flush=True)
    cik_counts = enrich_cik.populate(database, listings, sic_cache)
    print(
        f"CIK rows: {cik_counts['ciks']:,}; "
        f"ticker/exchange rows: {cik_counts['listings']:,}",
        flush=True,
    )

    print("\n[3/5] Rebuilding CUSIP dimensions", flush=True)
    cusip_counts = enrich_cusip.populate(database)
    print(
        f"CUSIP rows: {cusip_counts['cusips']:,}; "
        f"variants: {cusip_counts['variants']:,}; "
        f"holding rows: {cusip_counts['holdings']:,}",
        flush=True,
    )

    print("\n[4/5] Resolving canonical filings and amendments", flush=True)
    canonical_counts = build_canonical_filings.build(database)
    print(
        f"Canonical manager/quarters: "
        f"{canonical_counts['canonical_filings']:,}; "
        f"analytics-ready holding rows: "
        f"{canonical_counts['analytics_holding_rows']:,}",
        flush=True,
    )

    print("\n[5/5] Building instruments and quarterly summaries", flush=True)
    instrument_counts = build_instruments.build(database)
    print(
        f"Active instruments: {instrument_counts['instruments']:,}; "
        f"quarterly positions: "
        f"{instrument_counts['quarterly_positions']:,}",
        flush=True,
    )

    verify_database(database)
    print(f"\nETL completed successfully: {database}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path, help="SEC quarterly Form 13F ZIP")
    parser.add_argument(
        "--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3"
    )
    parser.add_argument(
        "--extract-dir",
        type=Path,
        help="extraction directory (default: raw_date/YYYYQ# from ZIP name)",
    )
    parser.add_argument(
        "--listings",
        type=Path,
        default=PROJECT_DIR / "raw_date" / "company_tickers_exchange.json",
    )
    parser.add_argument(
        "--sic-cache",
        type=Path,
        default=PROJECT_DIR / "raw_date" / "company_sic.json",
    )
    parser.add_argument(
        "--replace-extracted",
        action="store_true",
        help="replace an existing extracted directory with ZIP contents",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="skip raw append and rerun only CIK/CUSIP enrichments",
    )
    arguments = parser.parse_args()

    zip_path = arguments.zip.expanduser().resolve()
    database = arguments.database.expanduser().resolve()
    extract_dir = (
        arguments.extract_dir.expanduser().resolve()
        if arguments.extract_dir
        else default_extract_dir(zip_path)
    )

    try:
        run(
            zip_path=zip_path,
            database=database,
            extract_dir=extract_dir,
            listings=arguments.listings.expanduser().resolve(),
            sic_cache=arguments.sic_cache.expanduser().resolve(),
            replace_extracted=arguments.replace_extracted,
            skip_import=arguments.skip_import,
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
