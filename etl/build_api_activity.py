#!/usr/bin/env python3
"""Materialize API activity summaries without rebuilding all 13F facts."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

try:
    from .build_canonical_filings import execute_statements
    from .build_instruments import INSTRUMENT_SCHEMA
except ImportError:  # Allow direct execution: python3 etl/build_api_activity.py
    from build_canonical_filings import execute_statements
    from build_instruments import INSTRUMENT_SCHEMA


PROJECT_DIR = Path(__file__).resolve().parent.parent


MANAGER_ACTIVITY_SQL = """
INSERT INTO CIK_QUARTER_ACTIVITY (
    MANAGER_CIK,
    QUARTER_ID,
    NEW_COUNT,
    ADDED_COUNT,
    REDUCED_COUNT,
    EXITED_COUNT,
    GROSS_BUY_VALUE_USD,
    GROSS_SELL_VALUE_USD,
    GROSS_VALUE_CHANGE_USD,
    NET_VALUE_CHANGE_USD
)
SELECT
    R.MANAGER_CIK,
    X.TO_QUARTER_ID,
    COUNT(*) FILTER (WHERE X.ACTION = 'NEW') AS NEW_COUNT,
    COUNT(*) FILTER (WHERE X.ACTION = 'ADDED') AS ADDED_COUNT,
    COUNT(*) FILTER (WHERE X.ACTION = 'REDUCED') AS REDUCED_COUNT,
    COUNT(*) FILTER (WHERE X.ACTION = 'EXITED') AS EXITED_COUNT,
    SUM(CASE
        WHEN X.ACTION IN ('NEW', 'ADDED')
            THEN COALESCE(X.VALUE_CHANGE_USD, X.CURRENT_VALUE_USD, 0)
        ELSE 0
    END) AS GROSS_BUY_VALUE_USD,
    SUM(CASE
        WHEN X.ACTION IN ('REDUCED', 'EXITED')
            THEN ABS(COALESCE(X.VALUE_CHANGE_USD, X.PRIOR_VALUE_USD, 0))
        ELSE 0
    END) AS GROSS_SELL_VALUE_USD,
    SUM(CASE WHEN X.IS_COMPARABLE = 1
        THEN ABS(COALESCE(X.VALUE_CHANGE_USD, 0)) ELSE 0 END)
        AS GROSS_VALUE_CHANGE_USD,
    SUM(CASE WHEN X.IS_COMPARABLE = 1
        THEN COALESCE(X.VALUE_CHANGE_USD, 0) ELSE 0 END)
        AS NET_VALUE_CHANGE_USD
FROM CIK_INSTRUMENT_CHANGE X
JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
WHERE X.TO_QUARTER_ID = ?
GROUP BY R.MANAGER_CIK, X.TO_QUARTER_ID
"""


CUSIP_ACTIVITY_SQL = """
INSERT INTO CUSIP_QUARTER_ACTIVITY (
    CUSIP_ID,
    QUARTER_ID,
    NEW_INVESTOR_COUNT,
    EXITED_INVESTOR_COUNT,
    ADDED_HOLDER_COUNT,
    REDUCED_HOLDER_COUNT,
    NET_VALUE_CHANGE_USD
)
SELECT
    I.CUSIP_ID,
    X.TO_QUARTER_ID,
    COUNT(DISTINCT CASE WHEN X.ACTION = 'NEW'
        THEN R.MANAGER_CIK END) AS NEW_INVESTOR_COUNT,
    COUNT(DISTINCT CASE WHEN X.ACTION = 'EXITED'
        THEN R.MANAGER_CIK END) AS EXITED_INVESTOR_COUNT,
    COUNT(DISTINCT CASE WHEN X.ACTION = 'ADDED'
        THEN R.MANAGER_CIK END) AS ADDED_HOLDER_COUNT,
    COUNT(DISTINCT CASE WHEN X.ACTION = 'REDUCED'
        THEN R.MANAGER_CIK END) AS REDUCED_HOLDER_COUNT,
    SUM(CASE WHEN X.IS_COMPARABLE = 1
        THEN COALESCE(X.VALUE_CHANGE_USD, 0) ELSE 0 END)
        AS NET_VALUE_CHANGE_USD
FROM CIK_INSTRUMENT_CHANGE X
JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
JOIN INSTRUMENT I USING (INSTRUMENT_ID)
WHERE X.TO_QUARTER_ID = ?
GROUP BY I.CUSIP_ID, X.TO_QUARTER_ID
"""


MANAGER_ACTION_ACTIVITY_SQL = """
INSERT INTO CIK_QUARTER_ACTION_ACTIVITY (
    MANAGER_CIK,
    QUARTER_ID,
    ACTION,
    POSITION_COUNT,
    POSITION_VALUE_USD,
    AMOUNT_CHANGE,
    VALUE_CHANGE_USD
)
SELECT
    R.MANAGER_CIK,
    X.TO_QUARTER_ID,
    X.ACTION,
    COUNT(*) AS POSITION_COUNT,
    SUM(COALESCE(X.CURRENT_VALUE_USD, X.PRIOR_VALUE_USD, 0))
        AS POSITION_VALUE_USD,
    SUM(COALESCE(X.AMOUNT_CHANGE, 0)) AS AMOUNT_CHANGE,
    SUM(COALESCE(X.VALUE_CHANGE_USD, 0)) AS VALUE_CHANGE_USD
FROM CIK_INSTRUMENT_CHANGE X
JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
WHERE X.TO_QUARTER_ID = ?
GROUP BY R.MANAGER_CIK, X.TO_QUARTER_ID, X.ACTION
"""


CUSIP_ACTION_ACTIVITY_SQL = """
INSERT INTO CUSIP_QUARTER_ACTION_ACTIVITY (
    CUSIP_ID,
    QUARTER_ID,
    ACTION,
    INSTITUTION_COUNT,
    VALUE_CHANGE_USD
)
SELECT
    I.CUSIP_ID,
    X.TO_QUARTER_ID,
    X.ACTION,
    COUNT(DISTINCT R.MANAGER_CIK) AS INSTITUTION_COUNT,
    SUM(COALESCE(X.VALUE_CHANGE_USD, 0)) AS VALUE_CHANGE_USD
FROM CIK_INSTRUMENT_CHANGE X
JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
JOIN INSTRUMENT I USING (INSTRUMENT_ID)
WHERE X.TO_QUARTER_ID = ?
GROUP BY I.CUSIP_ID, X.TO_QUARTER_ID, X.ACTION
"""


def ensure_activity_schema(connection: sqlite3.Connection) -> None:
    execute_statements(connection, INSTRUMENT_SCHEMA)
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(CIK_QUARTER_ACTIVITY)")
    }
    if "GROSS_VALUE_CHANGE_USD" not in columns:
        connection.execute(
            "ALTER TABLE CIK_QUARTER_ACTIVITY "
            "ADD COLUMN GROSS_VALUE_CHANGE_USD INTEGER NOT NULL DEFAULT 0"
        )


def activity_quarters(
    connection: sqlite3.Connection, quarter_id: int | None
) -> list[sqlite3.Row]:
    if quarter_id is not None:
        rows = connection.execute(
            """
            SELECT Q.QUARTER_ID, Q.QUARTER_LABEL
            FROM QUARTER Q
            WHERE Q.QUARTER_ID = ?
            """,
            (quarter_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT DISTINCT Q.QUARTER_ID, Q.QUARTER_LABEL
            FROM CIK_INSTRUMENT_CHANGE X
            JOIN QUARTER Q ON Q.QUARTER_ID = X.TO_QUARTER_ID
            ORDER BY Q.QUARTER_ID
            """
        ).fetchall()
    if not rows:
        raise ValueError(f"no activity quarter found: {quarter_id}")
    return rows


def build(database: Path, quarter_id: int | None = None) -> dict[str, int]:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA cache_size = -262144")
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_activity_schema(connection)
        quarters = activity_quarters(connection, quarter_id)
        if quarter_id is None:
            connection.execute(
                """
                DELETE FROM CIK_QUARTER_ACTIVITY
                WHERE QUARTER_ID NOT IN (
                    SELECT DISTINCT TO_QUARTER_ID FROM CIK_INSTRUMENT_CHANGE
                )
                """
            )
            connection.execute(
                """
                DELETE FROM CUSIP_QUARTER_ACTIVITY
                WHERE QUARTER_ID NOT IN (
                    SELECT DISTINCT TO_QUARTER_ID FROM CIK_INSTRUMENT_CHANGE
                )
                """
            )
            connection.execute(
                """
                DELETE FROM CIK_QUARTER_ACTION_ACTIVITY
                WHERE QUARTER_ID NOT IN (
                    SELECT DISTINCT TO_QUARTER_ID FROM CIK_INSTRUMENT_CHANGE
                )
                """
            )
            connection.execute(
                """
                DELETE FROM CUSIP_QUARTER_ACTION_ACTIVITY
                WHERE QUARTER_ID NOT IN (
                    SELECT DISTINCT TO_QUARTER_ID FROM CIK_INSTRUMENT_CHANGE
                )
                """
            )
        connection.commit()

        for index, quarter in enumerate(quarters, start=1):
            label = quarter["QUARTER_LABEL"]
            qid = quarter["QUARTER_ID"]
            print(
                f"[{index}/{len(quarters)}] building API activity {label}",
                flush=True,
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM CIK_QUARTER_ACTIVITY WHERE QUARTER_ID = ?",
                (qid,),
            )
            connection.execute(
                """
                DELETE FROM CIK_QUARTER_ACTION_ACTIVITY
                WHERE QUARTER_ID = ?
                """,
                (qid,),
            )
            connection.execute(
                "DELETE FROM CUSIP_QUARTER_ACTIVITY WHERE QUARTER_ID = ?",
                (qid,),
            )
            connection.execute(
                """
                DELETE FROM CUSIP_QUARTER_ACTION_ACTIVITY
                WHERE QUARTER_ID = ?
                """,
                (qid,),
            )
            connection.execute(MANAGER_ACTIVITY_SQL, (qid,))
            connection.execute(MANAGER_ACTION_ACTIVITY_SQL, (qid,))
            connection.execute(CUSIP_ACTIVITY_SQL, (qid,))
            connection.execute(CUSIP_ACTION_ACTIVITY_SQL, (qid,))
            connection.commit()

        connection.execute("BEGIN IMMEDIATE")
        counts = {
            "manager_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CIK_QUARTER_ACTIVITY"
            ).fetchone()[0],
            "cusip_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_QUARTER_ACTIVITY"
            ).fetchone()[0],
            "manager_action_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CIK_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
            "cusip_action_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
        }
        foreign_key_errors = connection.execute(
            """
            SELECT * FROM pragma_foreign_key_check
            WHERE "table" IN (
                'CIK_QUARTER_ACTIVITY',
                'CUSIP_QUARTER_ACTIVITY'
            )
            """
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:5]}"
            )
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
    parser.add_argument("--quarter-id", type=int)
    arguments = parser.parse_args()
    try:
        counts = build(
            arguments.database.expanduser().resolve(),
            arguments.quarter_id,
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        "CIK quarterly activity summaries: "
        f"{counts['manager_activity_summaries']:,}"
    )
    print(
        "CUSIP quarterly activity summaries: "
        f"{counts['cusip_activity_summaries']:,}"
    )
    print(
        "CIK action activity summaries: "
        f"{counts['manager_action_activity_summaries']:,}"
    )
    print(
        "CUSIP action activity summaries: "
        f"{counts['cusip_action_activity_summaries']:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
