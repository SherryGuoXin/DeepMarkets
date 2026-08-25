#!/usr/bin/env python3
"""Build the compact, ordered feed used by the Latest Filings API."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS LATEST_FILING_FEED (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    MANAGER_CIK CHAR(10) NOT NULL,
    INSTITUTION_NAME TEXT NOT NULL,
    FILING_DATE_ISO DATE NOT NULL,
    SUBMISSION_TYPE VARCHAR2(10) NOT NULL,
    QUARTER_ID INTEGER,
    QUARTER_LABEL CHAR(6),
    PERIOD_END_DATE DATE,
    REPORTED_ASSETS_USD INTEGER,
    HOLDING_COUNT INTEGER,
    IS_PARTIAL INTEGER NOT NULL CHECK (IS_PARTIAL IN (0, 1)),
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS LATEST_FILING_FEED_DATE_IDX
    ON LATEST_FILING_FEED (FILING_DATE_ISO DESC, ACCESSION_NUMBER DESC);

CREATE INDEX IF NOT EXISTS LATEST_FILING_FEED_MANAGER_QUARTER_IDX
    ON LATEST_FILING_FEED (MANAGER_CIK, QUARTER_ID);
"""

RAW_QUARTER_ID = """
CAST(substr(C.REPORTCALENDARORQUARTER, 8, 4) AS INTEGER) * 100
    + CASE substr(upper(C.REPORTCALENDARORQUARTER), 4, 3)
        WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 1 WHEN 'MAR' THEN 1
        WHEN 'APR' THEN 2 WHEN 'MAY' THEN 2 WHEN 'JUN' THEN 2
        WHEN 'JUL' THEN 3 WHEN 'AUG' THEN 3 WHEN 'SEP' THEN 3
        WHEN 'OCT' THEN 4 WHEN 'NOV' THEN 4 WHEN 'DEC' THEN 4
      END
"""

RAW_FILING_DATE = """
substr(S.FILING_DATE, 8, 4) || '-' ||
    CASE substr(upper(S.FILING_DATE), 4, 3)
        WHEN 'JAN' THEN '01' WHEN 'FEB' THEN '02' WHEN 'MAR' THEN '03'
        WHEN 'APR' THEN '04' WHEN 'MAY' THEN '05' WHEN 'JUN' THEN '06'
        WHEN 'JUL' THEN '07' WHEN 'AUG' THEN '08' WHEN 'SEP' THEN '09'
        WHEN 'OCT' THEN '10' WHEN 'NOV' THEN '11' WHEN 'DEC' THEN '12'
    END || '-' || substr(S.FILING_DATE, 1, 2)
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _insert_sql(*, scoped: bool = False, accession_only: bool = False) -> str:
    if scoped:
        daily_scope = """
        JOIN temp.LATEST_FILING_SCOPE X
          ON X.MANAGER_CIK = printf('%010d', CAST(S.CIK AS INTEGER))
         AND X.QUARTER_ID = COALESCE(N.QUARTER_ID, {raw_quarter})
        """.format(raw_quarter=RAW_QUARTER_ID)
        canonical_scope = """
        JOIN temp.LATEST_FILING_SCOPE X
          ON X.MANAGER_CIK = F.MANAGER_CIK
         AND X.QUARTER_ID = F.QUARTER_ID
        """
        accession_filter = ""
    elif accession_only:
        daily_scope = ""
        canonical_scope = ""
        accession_filter = "WHERE D.ACCESSION_NUMBER = ?"
        canonical_filter = "AND 0"
    else:
        daily_scope = ""
        canonical_scope = ""
        accession_filter = ""
        canonical_filter = ""
    if scoped:
        canonical_filter = ""

    return f"""
    WITH FILING_FEED AS (
        SELECT
            printf('%010d', CAST(S.CIK AS INTEGER)) AS MANAGER_CIK,
            COALESCE(N.QUARTER_ID, {RAW_QUARTER_ID}) AS QUARTER_ID,
            S.ACCESSION_NUMBER,
            COALESCE(N.FILING_DATE_ISO, {RAW_FILING_DATE}) AS FILING_DATE_ISO,
            S.SUBMISSIONTYPE AS SUBMISSION_TYPE,
            1 AS IS_DAILY,
            C.FILINGMANAGER_NAME AS RAW_MANAGER_NAME
        FROM DAILY_EDGAR_ACCESSION D
        JOIN SUBMISSION S USING (ACCESSION_NUMBER)
        JOIN COVERPAGE C USING (ACCESSION_NUMBER)
        LEFT JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
        {daily_scope}
        {accession_filter}
        UNION ALL
        SELECT
            F.MANAGER_CIK,
            F.QUARTER_ID,
            F.LATEST_ACCESSION_NUMBER,
            N.FILING_DATE_ISO,
            N.SUBMISSION_TYPE,
            0 AS IS_DAILY,
            NULL AS RAW_MANAGER_NAME
        FROM CANONICAL_FILING F
        JOIN NORMALIZED_FILING N
          ON N.ACCESSION_NUMBER = F.LATEST_ACCESSION_NUMBER
        {canonical_scope}
        WHERE NOT EXISTS (
            SELECT 1 FROM DAILY_EDGAR_ACCESSION D
            WHERE D.ACCESSION_NUMBER = F.LATEST_ACCESSION_NUMBER
        )
        {canonical_filter}
    )
    INSERT OR REPLACE INTO LATEST_FILING_FEED (
        ACCESSION_NUMBER, MANAGER_CIK, INSTITUTION_NAME, FILING_DATE_ISO,
        SUBMISSION_TYPE, QUARTER_ID, QUARTER_LABEL, PERIOD_END_DATE,
        REPORTED_ASSETS_USD, HOLDING_COUNT, IS_PARTIAL
    )
    SELECT
        R.ACCESSION_NUMBER,
        R.MANAGER_CIK,
        COALESCE(NULLIF(R.RAW_MANAGER_NAME, ''), NULLIF(C.MANAGER_NAME, ''),
            NULLIF(C.SEC_COMPANY_NAME, ''), R.MANAGER_CIK),
        R.FILING_DATE_ISO,
        R.SUBMISSION_TYPE,
        R.QUARTER_ID,
        COALESCE(
            Q.QUARTER_LABEL,
            substr(CAST(R.QUARTER_ID AS TEXT), 1, 4) || 'Q' ||
                substr(CAST(R.QUARTER_ID AS TEXT), 6, 1)
        ),
        COALESCE(
            Q.QUARTER_END_DATE,
            substr(CAST(R.QUARTER_ID AS TEXT), 1, 4) ||
                CASE R.QUARTER_ID % 100
                    WHEN 1 THEN '-03-31' WHEN 2 THEN '-06-30'
                    WHEN 3 THEN '-09-30' WHEN 4 THEN '-12-31'
                END
        ),
        COALESCE(
            D.PORTFOLIO_VALUE_USD,
            QS.PORTFOLIO_VALUE_USD,
            CASE
                WHEN R.FILING_DATE_ISO < '2023-01-03'
                    THEN SP.TABLEVALUETOTAL * 1000
                ELSE SP.TABLEVALUETOTAL
            END
        ),
        COALESCE(D.CUSIP_COUNT, QS.CUSIP_COUNT, SP.TABLEENTRYTOTAL),
        CASE WHEN R.IS_DAILY = 1 OR D.MANAGER_CIK IS NOT NULL THEN 1 ELSE 0 END
    FROM FILING_FEED R
    LEFT JOIN QUARTER Q ON Q.QUARTER_ID = R.QUARTER_ID
    LEFT JOIN CIK C ON C.CIK = R.MANAGER_CIK
    LEFT JOIN CIK_QUARTER_SUMMARY QS
      ON QS.MANAGER_CIK = R.MANAGER_CIK
     AND QS.QUARTER_ID = R.QUARTER_ID
    LEFT JOIN DAILY_CIK_QUARTER_SUMMARY D
      ON D.MANAGER_CIK = R.MANAGER_CIK
     AND D.QUARTER_ID = R.QUARTER_ID
     AND EXISTS (
         SELECT 1 FROM DAILY_CIK_QUARTER_STATUS DS
         WHERE DS.QUARTER_ID = D.QUARTER_ID AND DS.STATUS = 'PARTIAL'
     )
    LEFT JOIN SUMMARYPAGE SP ON SP.ACCESSION_NUMBER = R.ACCESSION_NUMBER
    """


def refresh_daily_accession(
    connection: sqlite3.Connection, accession_number: str
) -> None:
    """Expose a committed raw daily filing before derived publication."""
    connection.execute(_insert_sql(accession_only=True), (accession_number,))


def refresh_manager_quarters(
    database: Path, manager_quarters: set[tuple[str, int]]
) -> int:
    """Refresh only manager/quarters affected by an incremental publication."""
    if not manager_quarters:
        return 0
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TEMP TABLE LATEST_FILING_SCOPE ("
            "MANAGER_CIK TEXT, QUARTER_ID INTEGER, "
            "PRIMARY KEY (MANAGER_CIK, QUARTER_ID))"
        )
        connection.executemany(
            "INSERT INTO LATEST_FILING_SCOPE VALUES (?, ?)",
            sorted(manager_quarters),
        )
        connection.execute(
            """
            DELETE FROM LATEST_FILING_FEED
            WHERE EXISTS (
                SELECT 1 FROM temp.LATEST_FILING_SCOPE X
                WHERE X.MANAGER_CIK = LATEST_FILING_FEED.MANAGER_CIK
                  AND X.QUARTER_ID = LATEST_FILING_FEED.QUARTER_ID
            )
            """
        )
        connection.execute(_insert_sql(scoped=True))
        count = int(connection.execute("SELECT changes()").fetchone()[0])
        connection.commit()
        return count
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def rebuild(database: Path) -> int:
    """Rebuild the complete feed after a quarterly derived-data rebuild."""
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM LATEST_FILING_FEED")
        connection.execute(_insert_sql())
        count = int(
            connection.execute("SELECT COUNT(*) FROM LATEST_FILING_FEED").fetchone()[0]
        )
        connection.commit()
        return count
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3"
    )
    arguments = parser.parse_args()
    try:
        count = rebuild(arguments.database.expanduser().resolve())
        print(f"Materialized {count:,} latest-filing rows")
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
