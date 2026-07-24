#!/usr/bin/env python3
"""Build normalized quarters, filings, and amendment-resolved holding views."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from . import etl_metadata
except ImportError:  # Allow direct execution: python3 etl/build_canonical_filings.py
    import etl_metadata


PROJECT_DIR = Path(__file__).resolve().parent.parent
VALUE_DOLLAR_CUTOFF = date(2023, 1, 3)

ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS QUARTER (
    QUARTER_ID INTEGER PRIMARY KEY,
    QUARTER_LABEL CHAR(6) NOT NULL UNIQUE,
    QUARTER_END_DATE DATE NOT NULL UNIQUE,
    YEAR INTEGER NOT NULL,
    QUARTER_NUMBER INTEGER NOT NULL CHECK (QUARTER_NUMBER BETWEEN 1 AND 4),
    PREVIOUS_QUARTER_ID INTEGER,
    FOREIGN KEY (PREVIOUS_QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE TABLE IF NOT EXISTS NORMALIZED_FILING (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    ETL_BATCH_ID INTEGER,
    MANAGER_CIK CHAR(10) NOT NULL,
    FILING_DATE_ISO DATE NOT NULL,
    PERIOD_OF_REPORT_ISO DATE NOT NULL,
    REPORT_CALENDAR_OR_QUARTER_ISO DATE,
    QUARTER_ID INTEGER,
    SUBMISSION_TYPE VARCHAR2(10) NOT NULL,
    REPORT_TYPE VARCHAR2(30),
    IS_AMENDMENT INTEGER NOT NULL CHECK (IS_AMENDMENT IN (0, 1)),
    AMENDMENT_NUMBER INTEGER,
    AMENDMENT_TYPE VARCHAR2(20),
    IS_CONFIDENTIAL_OMITTED INTEGER NOT NULL
        CHECK (IS_CONFIDENTIAL_OMITTED IN (0, 1)),
    FORM13F_FILE_NUMBER VARCHAR2(17),
    HAS_INFORMATION_TABLE INTEGER NOT NULL
        CHECK (HAS_INFORMATION_TABLE IN (0, 1)),
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER),
    FOREIGN KEY (ETL_BATCH_ID) REFERENCES ETL_BATCH (ETL_BATCH_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS NORMALIZED_FILING_MANAGER_QUARTER_IDX
    ON NORMALIZED_FILING (MANAGER_CIK, QUARTER_ID);

CREATE INDEX IF NOT EXISTS NORMALIZED_FILING_BATCH_IDX
    ON NORMALIZED_FILING (ETL_BATCH_ID);

CREATE TABLE IF NOT EXISTS FILING_OVERRIDE (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    OVERRIDE_COMPONENT_TYPE TEXT NOT NULL
        CHECK (
            OVERRIDE_COMPONENT_TYPE IN (
                'BASE', 'RESTATEMENT', 'ADDITION', 'EXCLUDE'
            )
        ),
    REASON TEXT NOT NULL,
    REVIEWED_AT TEXT NOT NULL,
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER)
);

CREATE TABLE IF NOT EXISTS CANONICAL_FILING (
    CANONICAL_FILING_ID INTEGER PRIMARY KEY,
    MANAGER_CIK CHAR(10) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    RESOLUTION_STATUS TEXT NOT NULL
        CHECK (
            RESOLUTION_STATUS IN (
                'RESOLVED', 'REVIEW_REQUIRED', 'INCOMPLETE_HISTORY'
            )
        ),
    IS_ANALYTICS_READY INTEGER NOT NULL
        CHECK (IS_ANALYTICS_READY IN (0, 1)),
    HAS_AMENDMENT INTEGER NOT NULL CHECK (HAS_AMENDMENT IN (0, 1)),
    HAS_CONFIDENTIAL_OMISSION INTEGER NOT NULL
        CHECK (HAS_CONFIDENTIAL_OMISSION IN (0, 1)),
    EFFECTIVE_COMPONENT_COUNT INTEGER NOT NULL,
    LATEST_ACCESSION_NUMBER VARCHAR2(25) NOT NULL,
    BUILT_AT TEXT NOT NULL,
    UNIQUE (MANAGER_CIK, QUARTER_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID),
    FOREIGN KEY (LATEST_ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER)
);

CREATE TABLE IF NOT EXISTS CANONICAL_FILING_COMPONENT (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    CANONICAL_FILING_ID INTEGER NOT NULL,
    COMPONENT_TYPE TEXT NOT NULL
        CHECK (
            COMPONENT_TYPE IN (
                'BASE', 'RESTATEMENT', 'ADDITION', 'UNKNOWN', 'EXCLUDE'
            )
        ),
    COMPONENT_SEQUENCE INTEGER NOT NULL,
    IS_EFFECTIVE INTEGER NOT NULL CHECK (IS_EFFECTIVE IN (0, 1)),
    SUPERSEDED_BY_ACCESSION_NUMBER VARCHAR2(25),
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER),
    FOREIGN KEY (CANONICAL_FILING_ID)
        REFERENCES CANONICAL_FILING (CANONICAL_FILING_ID) ON DELETE CASCADE,
    FOREIGN KEY (SUPERSEDED_BY_ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER)
);

CREATE INDEX IF NOT EXISTS CANONICAL_COMPONENT_FILING_IDX
    ON CANONICAL_FILING_COMPONENT (CANONICAL_FILING_ID, IS_EFFECTIVE);
"""

VIEW_SCHEMA = """
DROP VIEW IF EXISTS ANALYTICS_HOLDING_LINE;
DROP VIEW IF EXISTS CANONICAL_HOLDING_LINE;
DROP VIEW IF EXISTS FILING_VALUE_RECONCILIATION;

CREATE VIEW FILING_VALUE_RECONCILIATION AS
WITH HOLDING_TOTAL AS (
    SELECT
        C.ACCESSION_NUMBER,
        SUM(I.VALUE) AS HOLDING_RAW_TOTAL,
        COUNT(*) AS HOLDING_ROW_COUNT
    FROM CANONICAL_FILING_COMPONENT C
    JOIN INFOTABLE I USING (ACCESSION_NUMBER)
    WHERE C.IS_EFFECTIVE = 1
    GROUP BY C.ACCESSION_NUMBER
)
SELECT
    H.ACCESSION_NUMBER,
    H.HOLDING_ROW_COUNT,
    H.HOLDING_RAW_TOTAL,
    S.TABLEVALUETOTAL AS SUMMARY_RAW_TOTAL,
    H.HOLDING_RAW_TOTAL - S.TABLEVALUETOTAL AS RAW_DIFFERENCE,
    CASE
        WHEN S.TABLEVALUETOTAL IS NULL THEN 'NO_SUMMARY'
        WHEN H.HOLDING_RAW_TOTAL = S.TABLEVALUETOTAL THEN 'MATCH'
        WHEN ABS(H.HOLDING_RAW_TOTAL - S.TABLEVALUETOTAL) <= 1
            THEN 'ROUNDING_DIFFERENCE'
        WHEN S.TABLEVALUETOTAL = 0 THEN 'SUMMARY_ZERO'
        WHEN H.HOLDING_RAW_TOTAL
             BETWEEN S.TABLEVALUETOTAL * 999
                 AND S.TABLEVALUETOTAL * 1001
            THEN 'HOLDINGS_APPROX_1000X_SUMMARY'
        WHEN S.TABLEVALUETOTAL
             BETWEEN H.HOLDING_RAW_TOTAL * 999
                 AND H.HOLDING_RAW_TOTAL * 1001
            THEN 'SUMMARY_APPROX_1000X_HOLDINGS'
        ELSE 'MISMATCH'
    END AS RECONCILIATION_STATUS
FROM HOLDING_TOTAL H
LEFT JOIN SUMMARYPAGE S USING (ACCESSION_NUMBER);

CREATE VIEW CANONICAL_HOLDING_LINE AS
SELECT
    F.CANONICAL_FILING_ID,
    F.MANAGER_CIK,
    F.QUARTER_ID,
    Q.QUARTER_LABEL,
    Q.QUARTER_END_DATE,
    F.RESOLUTION_STATUS,
    F.IS_ANALYTICS_READY,
    F.HAS_CONFIDENTIAL_OMISSION,
    C.ACCESSION_NUMBER,
    R.RECONCILIATION_STATUS AS VALUE_RECONCILIATION_STATUS,
    I.INFOTABLE_SK,
    D.CUSIP_ID,
    I.CUSIP,
    I.NAMEOFISSUER,
    I.TITLEOFCLASS,
    I.FIGI,
    I.VALUE AS RAW_REPORTED_VALUE,
    CASE
        WHEN N.FILING_DATE_ISO < '2023-01-03' THEN 1000
        ELSE 1
    END AS VALUE_MULTIPLIER,
    I.VALUE * CASE
        WHEN N.FILING_DATE_ISO < '2023-01-03' THEN 1000
        ELSE 1
    END AS VALUE_USD,
    I.SSHPRNAMT,
    I.SSHPRNAMTTYPE,
    I.PUTCALL,
    I.INVESTMENTDISCRETION,
    I.OTHERMANAGER,
    I.VOTING_AUTH_SOLE,
    I.VOTING_AUTH_SHARED,
    I.VOTING_AUTH_NONE
FROM CANONICAL_FILING F
JOIN QUARTER Q USING (QUARTER_ID)
JOIN CANONICAL_FILING_COMPONENT C
    ON C.CANONICAL_FILING_ID = F.CANONICAL_FILING_ID
   AND C.IS_EFFECTIVE = 1
JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
JOIN INFOTABLE I USING (ACCESSION_NUMBER)
LEFT JOIN FILING_VALUE_RECONCILIATION R USING (ACCESSION_NUMBER)
LEFT JOIN CUSIP D ON D.CUSIP = I.CUSIP;

CREATE VIEW ANALYTICS_HOLDING_LINE AS
SELECT *
FROM CANONICAL_HOLDING_LINE
WHERE IS_ANALYTICS_READY = 1;
"""


def execute_statements(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete SQL statement")


def parse_sec_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value.upper(), "%d-%b-%Y").date()


def normalized_cik(value: str) -> str:
    return f"{int(value):010d}"


def quarter_number(value: date) -> int:
    return (value.month - 1) // 3 + 1


def quarter_id(value: date) -> int:
    return value.year * 100 + quarter_number(value)


def quarter_end(year: int, number: int) -> date:
    return date(year, number * 3, (31, 30, 30, 31)[number - 1])


def next_quarter(year: int, number: int) -> tuple[int, int]:
    return (year + 1, 1) if number == 4 else (year, number + 1)


def quarter_rows(observed_dates: list[date]) -> list[tuple[object, ...]]:
    first = min(observed_dates)
    last = max(observed_dates)
    year, number = first.year, quarter_number(first)
    last_key = (last.year, quarter_number(last))
    rows: list[tuple[object, ...]] = []
    previous: int | None = None
    while (year, number) <= last_key:
        identifier = year * 100 + number
        rows.append(
            (
                identifier,
                f"{year}Q{number}",
                quarter_end(year, number).isoformat(),
                year,
                number,
                previous,
            )
        )
        previous = identifier
        year, number = next_quarter(year, number)
    return rows


def component_type(row: sqlite3.Row) -> str:
    if row["OVERRIDE_COMPONENT_TYPE"]:
        return str(row["OVERRIDE_COMPONENT_TYPE"])
    if not row["IS_AMENDMENT"]:
        return "BASE"
    amendment_type = (row["AMENDMENT_TYPE"] or "").upper()
    if amendment_type == "RESTATEMENT":
        return "RESTATEMENT"
    if amendment_type == "NEW HOLDINGS":
        return "ADDITION"
    return "UNKNOWN"


def filing_sort_key(row: sqlite3.Row) -> tuple[object, ...]:
    return (
        row["FILING_DATE_ISO"],
        row["AMENDMENT_NUMBER"] if row["AMENDMENT_NUMBER"] is not None else -1,
        row["ACCESSION_NUMBER"],
    )


def build(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    try:
        etl_metadata.execute_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        execute_statements(connection, ANALYTICS_SCHEMA)

        raw_rows = connection.execute(
            """
            SELECT
                S.ACCESSION_NUMBER,
                B.ETL_BATCH_ID,
                S.CIK,
                S.FILING_DATE,
                S.PERIODOFREPORT,
                S.SUBMISSIONTYPE,
                P.REPORTCALENDARORQUARTER,
                P.REPORTTYPE,
                P.ISAMENDMENT,
                P.AMENDMENTNO,
                P.AMENDMENTTYPE,
                P.FORM13FFILENUMBER,
                SP.ISCONFIDENTIALOMITTED,
                EXISTS (
                    SELECT 1
                    FROM INFOTABLE I
                    WHERE I.ACCESSION_NUMBER = S.ACCESSION_NUMBER
                ) AS HAS_INFORMATION_TABLE
            FROM SUBMISSION S
            LEFT JOIN COVERPAGE P USING (ACCESSION_NUMBER)
            LEFT JOIN SUMMARYPAGE SP USING (ACCESSION_NUMBER)
            LEFT JOIN ETL_BATCH_ACCESSION B USING (ACCESSION_NUMBER)
            """
        ).fetchall()

        normalized_rows: list[tuple[object, ...]] = []
        report_dates: list[date] = []
        for row in raw_rows:
            filing_date = parse_sec_date(row["FILING_DATE"])
            period_date = parse_sec_date(row["PERIODOFREPORT"])
            report_date = parse_sec_date(row["REPORTCALENDARORQUARTER"])
            if filing_date is None or period_date is None:
                raise ValueError(
                    f"missing required date for {row['ACCESSION_NUMBER']}"
                )
            if report_date:
                report_dates.append(report_date)
            is_amendment = (
                str(row["ISAMENDMENT"] or "").upper() == "Y"
                or str(row["SUBMISSIONTYPE"]).endswith("/A")
            )
            normalized_rows.append(
                (
                    row["ACCESSION_NUMBER"],
                    row["ETL_BATCH_ID"],
                    normalized_cik(row["CIK"]),
                    filing_date.isoformat(),
                    period_date.isoformat(),
                    report_date.isoformat() if report_date else None,
                    quarter_id(report_date) if report_date else None,
                    row["SUBMISSIONTYPE"],
                    row["REPORTTYPE"],
                    int(is_amendment),
                    row["AMENDMENTNO"],
                    row["AMENDMENTTYPE"],
                    int(str(row["ISCONFIDENTIALOMITTED"] or "").upper() == "Y"),
                    row["FORM13FFILENUMBER"],
                    int(row["HAS_INFORMATION_TABLE"]),
                )
            )

        if not report_dates:
            raise ValueError("no report calendar/quarter dates found")

        connection.executemany(
            """
            INSERT INTO QUARTER (
                QUARTER_ID,
                QUARTER_LABEL,
                QUARTER_END_DATE,
                YEAR,
                QUARTER_NUMBER,
                PREVIOUS_QUARTER_ID
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (QUARTER_ID) DO UPDATE SET
                QUARTER_LABEL = excluded.QUARTER_LABEL,
                QUARTER_END_DATE = excluded.QUARTER_END_DATE,
                YEAR = excluded.YEAR,
                QUARTER_NUMBER = excluded.QUARTER_NUMBER,
                PREVIOUS_QUARTER_ID = excluded.PREVIOUS_QUARTER_ID
            """,
            quarter_rows(report_dates),
        )
        connection.executemany(
            """
            INSERT INTO NORMALIZED_FILING (
                ACCESSION_NUMBER,
                ETL_BATCH_ID,
                MANAGER_CIK,
                FILING_DATE_ISO,
                PERIOD_OF_REPORT_ISO,
                REPORT_CALENDAR_OR_QUARTER_ISO,
                QUARTER_ID,
                SUBMISSION_TYPE,
                REPORT_TYPE,
                IS_AMENDMENT,
                AMENDMENT_NUMBER,
                AMENDMENT_TYPE,
                IS_CONFIDENTIAL_OMITTED,
                FORM13F_FILE_NUMBER,
                HAS_INFORMATION_TABLE
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ACCESSION_NUMBER) DO UPDATE SET
                ETL_BATCH_ID = excluded.ETL_BATCH_ID,
                MANAGER_CIK = excluded.MANAGER_CIK,
                FILING_DATE_ISO = excluded.FILING_DATE_ISO,
                PERIOD_OF_REPORT_ISO = excluded.PERIOD_OF_REPORT_ISO,
                REPORT_CALENDAR_OR_QUARTER_ISO =
                    excluded.REPORT_CALENDAR_OR_QUARTER_ISO,
                QUARTER_ID = excluded.QUARTER_ID,
                SUBMISSION_TYPE = excluded.SUBMISSION_TYPE,
                REPORT_TYPE = excluded.REPORT_TYPE,
                IS_AMENDMENT = excluded.IS_AMENDMENT,
                AMENDMENT_NUMBER = excluded.AMENDMENT_NUMBER,
                AMENDMENT_TYPE = excluded.AMENDMENT_TYPE,
                IS_CONFIDENTIAL_OMITTED =
                    excluded.IS_CONFIDENTIAL_OMITTED,
                FORM13F_FILE_NUMBER = excluded.FORM13F_FILE_NUMBER,
                HAS_INFORMATION_TABLE = excluded.HAS_INFORMATION_TABLE
            """,
            normalized_rows,
        )

        connection.execute(
            """
            DELETE FROM NORMALIZED_FILING
            WHERE ACCESSION_NUMBER NOT IN (
                SELECT ACCESSION_NUMBER FROM SUBMISSION
            )
            """
        )

        filing_rows = connection.execute(
            """
            SELECT N.*, O.OVERRIDE_COMPONENT_TYPE
            FROM NORMALIZED_FILING N
            LEFT JOIN FILING_OVERRIDE O USING (ACCESSION_NUMBER)
            WHERE N.SUBMISSION_TYPE LIKE '13F-HR%'
              AND N.QUARTER_ID IS NOT NULL
            ORDER BY
                N.MANAGER_CIK,
                N.QUARTER_ID,
                N.FILING_DATE_ISO,
                COALESCE(N.AMENDMENT_NUMBER, -1),
                N.ACCESSION_NUMBER
            """
        ).fetchall()
        groups: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
        for row in filing_rows:
            groups[(row["MANAGER_CIK"], row["QUARTER_ID"])].append(row)

        built_at = datetime.now(timezone.utc).isoformat()
        existing_ids = {
            (row["MANAGER_CIK"], row["QUARTER_ID"]): row[
                "CANONICAL_FILING_ID"
            ]
            for row in connection.execute(
                """
                SELECT CANONICAL_FILING_ID, MANAGER_CIK, QUARTER_ID
                FROM CANONICAL_FILING
                """
            )
        }
        connection.execute("DELETE FROM CANONICAL_FILING_COMPONENT")
        seen_groups: set[tuple[str, int]] = set()
        review_count = 0
        incomplete_count = 0

        for key, rows in groups.items():
            rows.sort(key=filing_sort_key)
            seen_groups.add(key)
            components: list[dict[str, object]] = []
            effective_indexes: list[int] = []
            established_base = False
            review_required = False
            incomplete_history = False

            for sequence, row in enumerate(rows, start=1):
                kind = component_type(row)
                component = {
                    "accession": row["ACCESSION_NUMBER"],
                    "type": kind,
                    "sequence": sequence,
                    "effective": False,
                    "superseded_by": None,
                }
                components.append(component)
                current_index = len(components) - 1

                if kind in ("BASE", "RESTATEMENT"):
                    if kind == "BASE" and established_base:
                        review_required = True
                    for old_index in effective_indexes:
                        components[old_index]["effective"] = False
                        components[old_index]["superseded_by"] = row[
                            "ACCESSION_NUMBER"
                        ]
                    effective_indexes = [current_index]
                    component["effective"] = True
                    established_base = True
                    incomplete_history = False
                elif kind == "ADDITION":
                    component["effective"] = True
                    effective_indexes.append(current_index)
                    if not established_base:
                        incomplete_history = True
                elif kind == "UNKNOWN":
                    review_required = True

            if incomplete_history:
                status = "INCOMPLETE_HISTORY"
                incomplete_count += 1
            elif review_required:
                status = "REVIEW_REQUIRED"
                review_count += 1
            else:
                status = "RESOLVED"
            analytics_ready = int(
                status == "RESOLVED" and bool(effective_indexes)
            )
            effective_rows = [rows[index] for index in effective_indexes]
            has_confidential = int(
                any(row["IS_CONFIDENTIAL_OMITTED"] for row in effective_rows)
            )
            canonical_values = (
                key[0],
                key[1],
                status,
                analytics_ready,
                int(any(row["IS_AMENDMENT"] for row in rows)),
                has_confidential,
                len(effective_indexes),
                rows[-1]["ACCESSION_NUMBER"],
                built_at,
            )
            if key in existing_ids:
                canonical_id = existing_ids[key]
                connection.execute(
                    """
                    UPDATE CANONICAL_FILING
                    SET RESOLUTION_STATUS = ?,
                        IS_ANALYTICS_READY = ?,
                        HAS_AMENDMENT = ?,
                        HAS_CONFIDENTIAL_OMISSION = ?,
                        EFFECTIVE_COMPONENT_COUNT = ?,
                        LATEST_ACCESSION_NUMBER = ?,
                        BUILT_AT = ?
                    WHERE CANONICAL_FILING_ID = ?
                    """,
                    canonical_values[2:] + (canonical_id,),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO CANONICAL_FILING (
                        MANAGER_CIK,
                        QUARTER_ID,
                        RESOLUTION_STATUS,
                        IS_ANALYTICS_READY,
                        HAS_AMENDMENT,
                        HAS_CONFIDENTIAL_OMISSION,
                        EFFECTIVE_COMPONENT_COUNT,
                        LATEST_ACCESSION_NUMBER,
                        BUILT_AT
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    canonical_values,
                )
                canonical_id = int(cursor.lastrowid)

            connection.executemany(
                """
                INSERT INTO CANONICAL_FILING_COMPONENT (
                    ACCESSION_NUMBER,
                    CANONICAL_FILING_ID,
                    COMPONENT_TYPE,
                    COMPONENT_SEQUENCE,
                    IS_EFFECTIVE,
                    SUPERSEDED_BY_ACCESSION_NUMBER
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        component["accession"],
                        canonical_id,
                        component["type"],
                        component["sequence"],
                        int(component["effective"]),
                        component["superseded_by"],
                    )
                    for component in components
                ),
            )

        for key, canonical_id in existing_ids.items():
            if key not in seen_groups:
                connection.execute(
                    """
                    DELETE FROM CANONICAL_FILING
                    WHERE CANONICAL_FILING_ID = ?
                    """,
                    (canonical_id,),
                )

        execute_statements(connection, VIEW_SCHEMA)
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:5]}"
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        canonical_holding_rows, analytics_holding_rows = connection.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(IS_ANALYTICS_READY), 0)
            FROM CANONICAL_HOLDING_LINE
            """
        ).fetchone()
        counts = {
            "quarters": connection.execute(
                "SELECT COUNT(*) FROM QUARTER"
            ).fetchone()[0],
            "normalized_filings": len(normalized_rows),
            "canonical_filings": len(groups),
            "review_required": review_count,
            "incomplete_history": incomplete_count,
            "effective_components": connection.execute(
                """
                SELECT COUNT(*)
                FROM CANONICAL_FILING_COMPONENT
                WHERE IS_EFFECTIVE = 1
                """
            ).fetchone()[0],
            "canonical_holding_rows": canonical_holding_rows,
            "analytics_holding_rows": analytics_holding_rows,
            "value_reconciliation_issues": connection.execute(
                """
                SELECT COUNT(*)
                FROM FILING_VALUE_RECONCILIATION
                WHERE RECONCILIATION_STATUS NOT IN (
                    'MATCH', 'ROUNDING_DIFFERENCE'
                )
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3"
    )
    arguments = parser.parse_args()
    try:
        counts = build(arguments.database.expanduser().resolve())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Quarter rows: {counts['quarters']:,}")
    print(f"Normalized filings: {counts['normalized_filings']:,}")
    print(f"Canonical manager/quarters: {counts['canonical_filings']:,}")
    print(f"Effective filing components: {counts['effective_components']:,}")
    print(f"Review-required groups: {counts['review_required']:,}")
    print(f"Incomplete-history groups: {counts['incomplete_history']:,}")
    print(f"Canonical holding rows: {counts['canonical_holding_rows']:,}")
    print(f"Analytics-ready holding rows: {counts['analytics_holding_rows']:,}")
    print(
        "Effective filings with value-reconciliation issues: "
        f"{counts['value_reconciliation_issues']:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
