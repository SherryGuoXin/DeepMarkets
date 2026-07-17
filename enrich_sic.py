#!/usr/bin/env python3
"""Extract SEC SIC metadata for ticker CIKs and update the SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path


SOURCE = "SEC_SUBMISSIONS_API"
SOURCE_URL = "https://data.sec.gov/submissions/CIK##########.json"
BULK_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
)


def sic_major_group_division(sic: str | None) -> str | None:
    """Return the official 1987 SIC division name for a four-digit SIC."""
    if not sic or len(sic) < 2 or not sic[:2].isdigit():
        return None

    major_group = int(sic[:2])
    divisions = (
        (1, 9, "Agriculture, Forestry, and Fishing"),
        (10, 14, "Mining"),
        (15, 17, "Construction"),
        (20, 39, "Manufacturing"),
        (
            40,
            49,
            "Transportation, Communications, Electric, Gas, and Sanitary Services",
        ),
        (50, 51, "Wholesale Trade"),
        (52, 59, "Retail Trade"),
        (60, 67, "Finance, Insurance, and Real Estate"),
        (70, 89, "Services"),
        (91, 99, "Public Administration"),
    )
    for first, last, division in divisions:
        if first <= major_group <= last:
            return division
    return None


def load_ticker_ciks(path: Path) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"unexpected SEC ticker fields in {path}")
    return sorted({f"{int(row[0]):010d}" for row in document["data"]})


def extract_sic(bulk_zip: Path, ciks: list[str]) -> dict[str, dict[str, str | None]]:
    results: dict[str, dict[str, str | None]] = {}
    with zipfile.ZipFile(bulk_zip) as archive:
        for index, cik in enumerate(ciks, start=1):
            member = f"CIK{cik}.json"
            try:
                source_file = archive.open(member)
            except KeyError:
                results[cik] = {"sic": None, "sicDescription": None}
                continue
            with source_file:
                document = json.load(source_file)
            raw_sic = document.get("sic")
            raw_description = document.get("sicDescription")
            results[cik] = {
                "sic": str(raw_sic) if raw_sic not in (None, "") else None,
                "sicDescription": (
                    str(raw_description)
                    if raw_description not in (None, "")
                    else None
                ),
            }
            if index % 1000 == 0:
                print(f"Read {index:,}/{len(ciks):,} CIK files", flush=True)
    return results


def write_cache(
    output: Path, data: dict[str, dict[str, str | None]], as_of_date: str
) -> None:
    document = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "bulk_source_url": BULK_SOURCE_URL,
        "as_of_date": as_of_date,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def ensure_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(CIK_TICKER_EXCHANGE)")
    }
    definitions = {
        "SIC": "CHAR(4)",
        "SIC_DESCRIPTION": "TEXT",
        "SIC_MAJOR_GROUP_DIVISION": "TEXT",
        "SIC_AS_OF_DATE": "DATE",
        "SIC_SOURCE": "TEXT",
    }
    for column, declared_type in definitions.items():
        if column not in existing:
            connection.execute(
                f'ALTER TABLE CIK_TICKER_EXCHANGE ADD COLUMN "{column}" {declared_type}'
            )


def update_database(database: Path, cache: Path) -> dict[str, int]:
    document = json.loads(cache.read_text(encoding="utf-8"))
    data = document["data"]
    as_of_date = document["as_of_date"]
    connection = sqlite3.connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_columns(connection)
        connection.execute(
            """
            UPDATE CIK_TICKER_EXCHANGE
            SET SIC = NULL,
                SIC_DESCRIPTION = NULL,
                SIC_MAJOR_GROUP_DIVISION = NULL,
                SIC_AS_OF_DATE = NULL,
                SIC_SOURCE = NULL
            """
        )
        connection.executemany(
            """
            UPDATE CIK_TICKER_EXCHANGE
            SET SIC = ?,
                SIC_DESCRIPTION = ?,
                SIC_MAJOR_GROUP_DIVISION = ?,
                SIC_AS_OF_DATE = ?,
                SIC_SOURCE = ?
            WHERE CIK = ?
            """,
            (
                (
                    details.get("sic"),
                    details.get("sicDescription"),
                    sic_major_group_division(details.get("sic")),
                    as_of_date,
                    SOURCE,
                    cik,
                )
                for cik, details in data.items()
            ),
        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        counts = {
            "rows": connection.execute(
                "SELECT COUNT(*) FROM CIK_TICKER_EXCHANGE"
            ).fetchone()[0],
            "rows_with_sic": connection.execute(
                "SELECT COUNT(*) FROM CIK_TICKER_EXCHANGE WHERE SIC IS NOT NULL"
            ).fetchone()[0],
            "ciks_with_sic": connection.execute(
                """
                SELECT COUNT(DISTINCT CIK)
                FROM CIK_TICKER_EXCHANGE
                WHERE SIC IS NOT NULL
                """
            ).fetchone()[0],
        }
        connection.commit()
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    project_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk-zip", type=Path, required=True)
    parser.add_argument(
        "--tickers",
        type=Path,
        default=project_dir / "raw_date" / "company_tickers_exchange.json",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=project_dir / "raw_date" / "company_sic.json",
    )
    parser.add_argument(
        "--database", type=Path, default=project_dir / "form13f.sqlite3"
    )
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    arguments = parser.parse_args()

    try:
        ciks = load_ticker_ciks(arguments.tickers)
        data = extract_sic(arguments.bulk_zip, ciks)
        write_cache(arguments.cache, data, arguments.as_of_date)
        counts = update_database(arguments.database, arguments.cache)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Ticker CIKs processed: {len(ciks):,}")
    print(f"Listing rows with SIC: {counts['rows_with_sic']:,}/{counts['rows']:,}")
    print(f"Distinct CIKs with SIC: {counts['ciks_with_sic']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
