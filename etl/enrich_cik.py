#!/usr/bin/env python3
"""Create and populate the CIK dimension from 13F data and SEC listings."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

try:
    from .enrich_sic import sic_major_group_division
except ImportError:  # Allow direct execution: python3 etl/enrich_cik.py
    from enrich_sic import sic_major_group_division


CIK_SCHEMA = """
CREATE TABLE IF NOT EXISTS CIK (
    CIK CHAR(10) NOT NULL,
    SEC_COMPANY_NAME VARCHAR2(200),
    MANAGER_NAME VARCHAR2(150),
    TICKER TEXT,
    EXCHANGE TEXT,
    FILINGMANAGER_STREET1 VARCHAR2(40),
    FILINGMANAGER_STREET2 VARCHAR2(40),
    FILINGMANAGER_CITY VARCHAR2(30),
    FILINGMANAGER_STATEORCOUNTRY CHAR(2),
    FILINGMANAGER_ZIPCODE VARCHAR2(10),
    FORM13FFILENUMBER VARCHAR2(17),
    CRDNUMBER VARCHAR2(9),
    SECFILENUMBER VARCHAR2(17),
    LATEST_RELATED_ACCESSION_NUMBER VARCHAR2(25),
    LATEST_FILING_DATE DATE,
    LATEST_PERIOD_OF_REPORT DATE,
    SUBMISSION_COUNT NUMBER(10) NOT NULL DEFAULT 0,
    OTHER_MANAGER_MENTION_COUNT NUMBER(10) NOT NULL DEFAULT 0,
    PRIMARY KEY (CIK)
);

CREATE TABLE IF NOT EXISTS CIK_TICKER_EXCHANGE (
    CIK CHAR(10) NOT NULL,
    SEC_COMPANY_NAME VARCHAR2(200) NOT NULL,
    TICKER VARCHAR2(32) NOT NULL,
    EXCHANGE VARCHAR2(32),
    SIC CHAR(4),
    SIC_DESCRIPTION TEXT,
    SIC_MAJOR_GROUP_DIVISION TEXT,
    SIC_AS_OF_DATE DATE,
    SIC_SOURCE TEXT,
    PRIMARY KEY (CIK, TICKER),
    FOREIGN KEY (CIK) REFERENCES CIK (CIK)
);

CREATE INDEX IF NOT EXISTS CIK_TICKER_EXCHANGE_TICKER_IDX
    ON CIK_TICKER_EXCHANGE (TICKER);
"""

RELATIONSHIP_VIEW = """
DROP VIEW IF EXISTS CIK_13F_RELATIONSHIP;
CREATE VIEW CIK_13F_RELATIONSHIP AS
SELECT printf('%010d', CAST(CIK AS INTEGER)) AS CIK,
       ACCESSION_NUMBER,
       'FILING_MANAGER' AS RELATIONSHIP_TYPE
FROM SUBMISSION
UNION ALL
SELECT printf('%010d', CAST(CIK AS INTEGER)) AS CIK,
       ACCESSION_NUMBER,
       'OTHER_MANAGER' AS RELATIONSHIP_TYPE
FROM OTHERMANAGER
WHERE CIK IS NOT NULL AND CIK <> ''
UNION ALL
SELECT printf('%010d', CAST(CIK AS INTEGER)) AS CIK,
       ACCESSION_NUMBER,
       'INCLUDED_OTHER_MANAGER' AS RELATIONSHIP_TYPE
FROM OTHERMANAGER2
WHERE CIK IS NOT NULL AND CIK <> '';
"""


def execute_statements(connection: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit commit."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete SQL statement")


def normalized_cik(value: object) -> str:
    try:
        numeric_cik = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid CIK: {value!r}") from error
    if numeric_cik < 0 or numeric_cik > 9_999_999_999:
        raise ValueError(f"CIK is outside the ten-digit range: {value!r}")
    return f"{numeric_cik:010d}"


def load_listings(path: Path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"unexpected SEC JSON fields in {path}")
    if not isinstance(document.get("data"), list):
        raise ValueError(f"expected a data array in {path}")

    by_cik: dict[str, dict[str, object]] = OrderedDict()
    normalized_rows: list[tuple[str, str, str, str | None]] = []
    seen_rows: set[tuple[str, str, str | None]] = set()

    for row_number, row in enumerate(document["data"], start=1):
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(f"invalid listing row {row_number}: {row!r}")
        cik_value, name, ticker, exchange = row
        cik = normalized_cik(cik_value)
        if not all(isinstance(value, str) and value for value in (name, ticker)):
            raise ValueError(f"invalid listing row {row_number}: {row!r}")
        if exchange is not None and not (
            isinstance(exchange, str) and exchange
        ):
            raise ValueError(f"invalid listing row {row_number}: {row!r}")

        entry = by_cik.setdefault(
            cik, {"name": name, "tickers": [], "exchanges": []}
        )
        if ticker not in entry["tickers"]:
            entry["tickers"].append(ticker)
        entry["exchanges"].append(exchange)

        row_key = (cik, ticker, exchange)
        if row_key not in seen_rows:
            normalized_rows.append((cik, name, ticker, exchange))
            seen_rows.add(row_key)

    return by_cik, normalized_rows


def load_sic_cache(path: Path) -> tuple[dict[str, dict[str, str | None]], str | None]:
    if not path.is_file():
        return {}, None
    document = json.loads(path.read_text(encoding="utf-8"))
    data = document.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"expected a CIK-keyed data object in {path}")
    as_of_date = document.get("as_of_date")
    if as_of_date is not None and not isinstance(as_of_date, str):
        raise ValueError(f"invalid as_of_date in {path}")
    return data, as_of_date


def ensure_sic_columns(connection: sqlite3.Connection) -> None:
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


def populate(database: Path, listings_path: Path, sic_path: Path) -> dict[str, int]:
    listings_by_cik, listing_rows = load_listings(listings_path)
    sic_by_cik, sic_as_of_date = load_sic_cache(sic_path)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        execute_statements(connection, CIK_SCHEMA)
        ensure_sic_columns(connection)
        execute_statements(connection, RELATIONSHIP_VIEW)
        connection.execute("DELETE FROM CIK_TICKER_EXCHANGE")
        connection.execute("DELETE FROM CIK")

        connection.executemany(
            """
            INSERT INTO CIK (CIK, SEC_COMPANY_NAME, TICKER, EXCHANGE)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    cik,
                    details["name"],
                    ", ".join(details["tickers"]),
                    ", ".join(exchange or "" for exchange in details["exchanges"]),
                )
                for cik, details in listings_by_cik.items()
            ),
        )

        for source_table in ("SUBMISSION", "OTHERMANAGER", "OTHERMANAGER2"):
            connection.execute(
                f"""
                INSERT OR IGNORE INTO CIK (CIK)
                SELECT DISTINCT printf('%010d', CAST(CIK AS INTEGER))
                FROM {source_table}
                WHERE CIK IS NOT NULL AND CIK <> ''
                """
            )

        connection.executemany(
            """
            INSERT INTO CIK_TICKER_EXCHANGE
                (CIK, SEC_COMPANY_NAME, TICKER, EXCHANGE)
            VALUES (?, ?, ?, ?)
            """,
            listing_rows,
        )

        if sic_by_cik:
            connection.executemany(
                """
                UPDATE CIK_TICKER_EXCHANGE
                SET SIC = ?,
                    SIC_DESCRIPTION = ?,
                    SIC_MAJOR_GROUP_DIVISION = ?,
                    SIC_AS_OF_DATE = ?,
                    SIC_SOURCE = 'SEC_SUBMISSIONS_API'
                WHERE CIK = ?
                """,
                (
                    (
                        details.get("sic") or None,
                        details.get("sicDescription") or None,
                        sic_major_group_division(details.get("sic") or None),
                        sic_as_of_date,
                        cik,
                    )
                    for cik, details in sic_by_cik.items()
                ),
            )

        execute_statements(
            connection,
            """
            DROP TABLE IF EXISTS temp.LATEST_FILER;
            CREATE TEMP TABLE LATEST_FILER AS
            SELECT *
            FROM (
                SELECT
                    printf('%010d', CAST(S.CIK AS INTEGER)) AS CIK,
                    C.FILINGMANAGER_NAME AS MANAGER_NAME,
                    C.FILINGMANAGER_STREET1,
                    C.FILINGMANAGER_STREET2,
                    C.FILINGMANAGER_CITY,
                    C.FILINGMANAGER_STATEORCOUNTRY,
                    C.FILINGMANAGER_ZIPCODE,
                    C.FORM13FFILENUMBER,
                    C.CRDNUMBER,
                    C.SECFILENUMBER,
                    S.ACCESSION_NUMBER,
                    S.FILING_DATE,
                    S.PERIODOFREPORT,
                    COUNT(*) OVER (PARTITION BY printf('%010d', CAST(S.CIK AS INTEGER)))
                        AS SUBMISSION_COUNT,
                    ROW_NUMBER() OVER (
                        PARTITION BY printf('%010d', CAST(S.CIK AS INTEGER))
                        ORDER BY S.ACCESSION_NUMBER DESC
                    ) AS RN
                FROM SUBMISSION S
                JOIN COVERPAGE C USING (ACCESSION_NUMBER)
            )
            WHERE RN = 1;

            UPDATE CIK AS C
            SET
                MANAGER_NAME = F.MANAGER_NAME,
                FILINGMANAGER_STREET1 = F.FILINGMANAGER_STREET1,
                FILINGMANAGER_STREET2 = F.FILINGMANAGER_STREET2,
                FILINGMANAGER_CITY = F.FILINGMANAGER_CITY,
                FILINGMANAGER_STATEORCOUNTRY = F.FILINGMANAGER_STATEORCOUNTRY,
                FILINGMANAGER_ZIPCODE = F.FILINGMANAGER_ZIPCODE,
                FORM13FFILENUMBER = F.FORM13FFILENUMBER,
                CRDNUMBER = F.CRDNUMBER,
                SECFILENUMBER = F.SECFILENUMBER,
                LATEST_RELATED_ACCESSION_NUMBER = F.ACCESSION_NUMBER,
                LATEST_FILING_DATE = F.FILING_DATE,
                LATEST_PERIOD_OF_REPORT = F.PERIODOFREPORT,
                SUBMISSION_COUNT = F.SUBMISSION_COUNT
            FROM LATEST_FILER F
            WHERE C.CIK = F.CIK;

            DROP TABLE IF EXISTS temp.LATEST_OTHER_MANAGER;
            CREATE TEMP TABLE LATEST_OTHER_MANAGER AS
            SELECT *
            FROM (
                SELECT
                    CIK,
                    NAME,
                    FORM13FFILENUMBER,
                    CRDNUMBER,
                    SECFILENUMBER,
                    ACCESSION_NUMBER,
                    COUNT(*) OVER (PARTITION BY CIK) AS MENTION_COUNT,
                    ROW_NUMBER() OVER (
                        PARTITION BY CIK
                        ORDER BY ACCESSION_NUMBER DESC, SOURCE_PRIORITY, SOURCE_KEY DESC
                    ) AS RN
                FROM (
                    SELECT
                        printf('%010d', CAST(CIK AS INTEGER)) AS CIK,
                        NAME,
                        FORM13FFILENUMBER,
                        CRDNUMBER,
                        SECFILENUMBER,
                        ACCESSION_NUMBER,
                        1 AS SOURCE_PRIORITY,
                        OTHERMANAGER_SK AS SOURCE_KEY
                    FROM OTHERMANAGER
                    WHERE CIK IS NOT NULL AND CIK <> ''
                    UNION ALL
                    SELECT
                        printf('%010d', CAST(CIK AS INTEGER)) AS CIK,
                        NAME,
                        FORM13FFILENUMBER,
                        CRDNUMBER,
                        SECFILENUMBER,
                        ACCESSION_NUMBER,
                        2 AS SOURCE_PRIORITY,
                        SEQUENCENUMBER AS SOURCE_KEY
                    FROM OTHERMANAGER2
                    WHERE CIK IS NOT NULL AND CIK <> ''
                )
            )
            WHERE RN = 1;

            UPDATE CIK AS C
            SET
                MANAGER_NAME = COALESCE(C.MANAGER_NAME, O.NAME),
                FORM13FFILENUMBER = COALESCE(C.FORM13FFILENUMBER, O.FORM13FFILENUMBER),
                CRDNUMBER = COALESCE(C.CRDNUMBER, O.CRDNUMBER),
                SECFILENUMBER = COALESCE(C.SECFILENUMBER, O.SECFILENUMBER),
                LATEST_RELATED_ACCESSION_NUMBER = CASE
                    WHEN C.LATEST_RELATED_ACCESSION_NUMBER IS NULL
                         OR O.ACCESSION_NUMBER > C.LATEST_RELATED_ACCESSION_NUMBER
                    THEN O.ACCESSION_NUMBER
                    ELSE C.LATEST_RELATED_ACCESSION_NUMBER
                END,
                OTHER_MANAGER_MENTION_COUNT = O.MENTION_COUNT
            FROM LATEST_OTHER_MANAGER O
            WHERE C.CIK = O.CIK;

            UPDATE CIK
            SET MANAGER_NAME = SEC_COMPANY_NAME
            WHERE MANAGER_NAME IS NULL;
            """,
        )

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        counts = {
            "ciks": connection.execute("SELECT COUNT(*) FROM CIK").fetchone()[0],
            "listings": connection.execute(
                "SELECT COUNT(*) FROM CIK_TICKER_EXCHANGE"
            ).fetchone()[0],
            "ciks_with_13f_relationships": connection.execute(
                """
                SELECT COUNT(DISTINCT C.CIK)
                FROM CIK C
                JOIN CIK_13F_RELATIONSHIP R USING (CIK)
                """
            ).fetchone()[0],
            "ciks_with_tickers": connection.execute(
                "SELECT COUNT(*) FROM CIK WHERE TICKER IS NOT NULL"
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
    project_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=project_dir / "form13f.sqlite3"
    )
    parser.add_argument(
        "--listings",
        type=Path,
        default=project_dir / "raw_date" / "company_tickers_exchange.json",
    )
    parser.add_argument(
        "--sic",
        type=Path,
        default=project_dir / "raw_date" / "company_sic.json",
    )
    arguments = parser.parse_args()

    try:
        counts = populate(arguments.database, arguments.listings, arguments.sic)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"CIK rows: {counts['ciks']:,}")
    print(f"Ticker/exchange rows: {counts['listings']:,}")
    print(f"CIKs with 13F relationships: {counts['ciks_with_13f_relationships']:,}")
    print(f"CIKs with tickers: {counts['ciks_with_tickers']:,}")
    print(f"CIKs with SIC: {counts['ciks_with_sic']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
