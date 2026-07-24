#!/usr/bin/env python3
"""Download and bulk-load every published SEC Form 13F data set."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    from . import (
        build_canonical_filings,
        build_instruments,
        enrich_cik,
        enrich_cusip,
        etl_metadata,
        import_13f,
        run_etl,
    )
except ImportError:
    import build_canonical_filings
    import build_instruments
    import enrich_cik
    import enrich_cusip
    import etl_metadata
    import import_13f
    import run_etl


PROJECT_DIR = Path(__file__).resolve().parent.parent
SEC_BASE_URL = (
    "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
)
SEC_REFERER = (
    "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 13F-Institutional-Intelligence/1.0 "
    "contact@localhost.local"
)

DATE_RANGE_DATASETS = (
    "01jan2024-29feb2024_form13f.zip",
    "01mar2024-31may2024_form13f.zip",
    "01jun2024-31aug2024_form13f.zip",
    "01sep2024-30nov2024_form13f.zip",
    "01dec2024-28feb2025_form13f.zip",
    "01mar2025-31may2025_form13f.zip",
    "01jun2025-31aug2025_form13f.zip",
    "01sep2025-30nov2025_form13f.zip",
    "01dec2025-28feb2026_form13f.zip",
    "01mar2026-31may2026_form13f.zip",
)


def published_datasets() -> list[str]:
    quarterly = [
        f"{year}q{quarter}_form13f.zip"
        for year in range(2013, 2024)
        for quarter in range(1, 5)
        if (year, quarter) >= (2013, 2)
    ]
    return quarterly + list(DATE_RANGE_DATASETS)


def completed_filenames(database: Path) -> set[str]:
    connection = sqlite3.connect(database)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT ZIP_FILENAME FROM ETL_BATCH WHERE STATUS = 'COMPLETED'"
            )
        }
    finally:
        connection.close()


def is_valid_zip(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def download_dataset(
    filename: str,
    destination: Path,
    user_agent: str,
    retries: int = 5,
) -> None:
    if is_valid_zip(destination):
        print(f"Already downloaded: {filename}", flush=True)
        return

    partial = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {
            "User-Agent": user_agent,
            "Referer": SEC_REFERER,
            "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.8",
        }
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(
            f"{SEC_BASE_URL}/{filename}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                append = existing > 0 and response.status == 206
                mode = "ab" if append else "wb"
                if existing and not append:
                    existing = 0
                total_header = response.headers.get("Content-Length")
                expected = existing + int(total_header) if total_header else None
                with partial.open(mode) as output:
                    copied = existing
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        copied += len(chunk)
                        if copied % (25 * 1024 * 1024) < len(chunk):
                            total = (
                                f"/{expected / 1024 / 1024:.1f} MB"
                                if expected
                                else ""
                            )
                            print(
                                f"  {filename}: "
                                f"{copied / 1024 / 1024:.1f}{total}",
                                flush=True,
                            )
            partial.replace(destination)
            if not is_valid_zip(destination):
                raise ValueError(f"downloaded file is not a valid ZIP: {filename}")
            print(
                f"Downloaded {filename} "
                f"({destination.stat().st_size / 1024 / 1024:.1f} MB)",
                flush=True,
            )
            time.sleep(0.15)
            return
        except (OSError, urllib.error.URLError, ValueError) as error:
            if destination.exists() and not is_valid_zip(destination):
                destination.unlink()
            if attempt == retries:
                raise RuntimeError(
                    f"failed to download {filename} after {retries} attempts"
                ) from error
            delay = min(30, 2 ** attempt)
            print(
                f"Download attempt {attempt} failed for {filename}: {error}; "
                f"retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)


def import_one(
    zip_path: Path,
    database: Path,
    extract_root: Path,
    keep_extracted: bool,
) -> bool:
    extract_dir = extract_root / zip_path.stem
    source_dir = run_etl.extract_dataset(zip_path, extract_dir, False)
    batch_id, should_append = etl_metadata.prepare_batch(
        database, zip_path, source_dir
    )
    if not should_append:
        print(f"Batch {batch_id} already completed: {zip_path.name}", flush=True)
        if not keep_extracted:
            shutil.rmtree(source_dir, ignore_errors=True)
        return False
    try:
        import_13f.append_database(
            source_dir,
            database,
            verify_integrity=False,
        )
        etl_metadata.complete_batch(database, batch_id, source_dir)
    except Exception as error:
        etl_metadata.fail_batch(database, batch_id, error)
        raise
    finally:
        if not keep_extracted:
            shutil.rmtree(source_dir, ignore_errors=True)
    print(f"Completed raw batch {batch_id}: {zip_path.name}", flush=True)
    return True


def rebuild_derived(
    database: Path,
    listings: Path,
    sic_cache: Path,
    start_stage: str = "cik",
) -> None:
    stages = ("cik", "cusip", "canonical", "instruments")
    start_index = stages.index(start_stage)

    if start_index <= stages.index("cik"):
        print("\nRebuilding CIK/ticker/SIC dimensions", flush=True)
        cik_counts = enrich_cik.populate(database, listings, sic_cache)
        print(
            f"CIKs: {cik_counts['ciks']:,}; "
            f"ticker/exchange rows: {cik_counts['listings']:,}",
            flush=True,
        )

    if start_index <= stages.index("cusip"):
        print("\nRebuilding CUSIP dimensions", flush=True)
        cusip_counts = enrich_cusip.populate(database)
        print(
            f"CUSIPs: {cusip_counts['cusips']:,}; "
            f"variants: {cusip_counts['variants']:,}; "
            f"holding rows: {cusip_counts['holdings']:,}",
            flush=True,
        )

    if start_index <= stages.index("canonical"):
        print("\nResolving filings and amendments", flush=True)
        canonical_counts = build_canonical_filings.build(database)
        print(
            f"Canonical manager/quarters: "
            f"{canonical_counts['canonical_filings']:,}; "
            f"analytics-ready holding rows: "
            f"{canonical_counts['analytics_holding_rows']:,}",
            flush=True,
        )

    if start_index <= stages.index("instruments"):
        print("\nRebuilding instruments and quarterly analytics", flush=True)
        instrument_counts = build_instruments.build(database)
        print(
            f"Active instruments: {instrument_counts['instruments']:,}; "
            f"quarterly positions: "
            f"{instrument_counts['quarterly_positions']:,}",
            flush=True,
        )


def run(
    database: Path,
    download_dir: Path,
    extract_root: Path,
    listings: Path,
    sic_cache: Path,
    user_agent: str,
    keep_extracted: bool,
    download_only: bool,
    derived_only: bool,
    start_derived: str,
) -> None:
    if derived_only:
        rebuild_derived(
            database,
            listings,
            sic_cache,
            start_stage=start_derived,
        )
        run_etl.verify_database(database)
        print("\nDerived rebuild completed successfully", flush=True)
        return

    filenames = published_datasets()
    print(f"Published SEC data sets: {len(filenames)}", flush=True)
    for index, filename in enumerate(filenames, start=1):
        print(f"\nDownload [{index}/{len(filenames)}] {filename}", flush=True)
        download_dataset(
            filename,
            download_dir / filename,
            user_agent,
        )
    if download_only:
        return

    imported = 0
    completed = completed_filenames(database)
    for index, filename in enumerate(filenames, start=1):
        print(f"\nImport [{index}/{len(filenames)}] {filename}", flush=True)
        if filename in completed:
            print(f"Already completed: {filename}", flush=True)
            continue
        if import_one(
            download_dir / filename,
            database,
            extract_root,
            keep_extracted,
        ):
            imported += 1
            completed.add(filename)

    print(f"\nNew raw batches imported: {imported}", flush=True)
    rebuild_derived(database, listings, sic_cache)
    run_etl.verify_database(database)
    print("\nBulk ETL completed successfully", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_DIR / "form13f.sqlite3",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=PROJECT_DIR / "raw_date",
    )
    parser.add_argument(
        "--extract-root",
        type=Path,
        default=PROJECT_DIR / "raw_date" / "datasets",
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
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="SEC-compliant HTTP User-Agent",
    )
    parser.add_argument(
        "--keep-extracted",
        action="store_true",
        help="retain extracted TSV directories after successful import",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="download and validate all ZIPs without importing",
    )
    parser.add_argument(
        "--derived-only",
        action="store_true",
        help="skip download/raw import and rebuild only derived tables",
    )
    parser.add_argument(
        "--start-derived",
        choices=("cik", "cusip", "canonical", "instruments"),
        default="cik",
        help="first derived stage to run with --derived-only (default: cik)",
    )
    arguments = parser.parse_args()
    if arguments.download_only and arguments.derived_only:
        parser.error("--download-only and --derived-only cannot be combined")

    try:
        run(
            database=arguments.database.expanduser().resolve(),
            download_dir=arguments.download_dir.expanduser().resolve(),
            extract_root=arguments.extract_root.expanduser().resolve(),
            listings=arguments.listings.expanduser().resolve(),
            sic_cache=arguments.sic_cache.expanduser().resolve(),
            user_agent=arguments.user_agent,
            keep_extracted=arguments.keep_extracted,
            download_only=arguments.download_only,
            derived_only=arguments.derived_only,
            start_derived=arguments.start_derived,
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
