#!/usr/bin/env python3
"""Build materialized base/call/put CUSIP summaries quarter by quarter."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent

STAGE_SCHEMA = """
CREATE TEMP TABLE CUSIP_INSTRUMENT_QUARTER_SUMMARY_STAGE (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    OPTION_TYPE TEXT NOT NULL,
    INSTITUTION_COUNT INTEGER NOT NULL,
    TOTAL_VALUE_USD INTEGER NOT NULL,
    REPORTED_AMOUNT INTEGER NOT NULL,
    AVERAGE_POSITION_VALUE_USD REAL,
    MANAGER_CONCENTRATION_HHI REAL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID, OPTION_TYPE)
);

CREATE TEMP TABLE CUSIP_BASE_QUARTER_ACTION_ACTIVITY_STAGE (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    ACTION TEXT NOT NULL,
    INSTITUTION_COUNT INTEGER NOT NULL,
    VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID, ACTION)
);
"""

INSTRUMENT_SUMMARY_INSERT = """
INSERT INTO {target} (
    CUSIP_ID,
    QUARTER_ID,
    OPTION_TYPE,
    INSTITUTION_COUNT,
    TOTAL_VALUE_USD,
    REPORTED_AMOUNT,
    AVERAGE_POSITION_VALUE_USD,
    MANAGER_CONCENTRATION_HHI
)
WITH MANAGER_INSTRUMENT_TYPE AS (
    SELECT
        I.CUSIP_ID,
        P.QUARTER_ID,
        I.OPTION_TYPE,
        R.MANAGER_CIK,
        SUM(P.VALUE_USD) AS MANAGER_VALUE_USD,
        SUM(P.REPORTED_AMOUNT) AS MANAGER_REPORTED_AMOUNT
    FROM CIK_INSTRUMENT_QUARTER P
    JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
    JOIN INSTRUMENT I USING (INSTRUMENT_ID)
    WHERE P.QUARTER_ID = ?
    GROUP BY
        I.CUSIP_ID,
        P.QUARTER_ID,
        I.OPTION_TYPE,
        R.MANAGER_CIK
),
WITH_TOTAL AS (
    SELECT
        M.*,
        SUM(MANAGER_VALUE_USD) OVER (
            PARTITION BY CUSIP_ID, QUARTER_ID, OPTION_TYPE
        ) AS TOTAL_VALUE_USD
    FROM MANAGER_INSTRUMENT_TYPE M
)
SELECT
    CUSIP_ID,
    QUARTER_ID,
    OPTION_TYPE,
    COUNT(*) AS INSTITUTION_COUNT,
    MAX(TOTAL_VALUE_USD) AS TOTAL_VALUE_USD,
    SUM(MANAGER_REPORTED_AMOUNT) AS REPORTED_AMOUNT,
    AVG(MANAGER_VALUE_USD) AS AVERAGE_POSITION_VALUE_USD,
    CASE WHEN MAX(TOTAL_VALUE_USD) = 0 THEN NULL
        ELSE SUM(
            (1.0 * MANAGER_VALUE_USD / TOTAL_VALUE_USD)
            * (1.0 * MANAGER_VALUE_USD / TOTAL_VALUE_USD)
        )
    END AS MANAGER_CONCENTRATION_HHI
FROM WITH_TOTAL
GROUP BY CUSIP_ID, QUARTER_ID, OPTION_TYPE
"""

BASE_ACTION_INSERT = """
INSERT INTO {target} (
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
WHERE X.TO_QUARTER_ID = ? AND I.OPTION_TYPE = 'NONE'
GROUP BY I.CUSIP_ID, X.TO_QUARTER_ID, X.ACTION
"""


def populate(
    connection: sqlite3.Connection,
    instrument_target: str,
    action_target: str,
    *,
    commit_each_quarter: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
) -> None:
    quarters = [
        int(row[0])
        for row in connection.execute(
            "SELECT QUARTER_ID FROM QUARTER ORDER BY QUARTER_ID"
        )
    ]
    instrument_sql = INSTRUMENT_SUMMARY_INSERT.format(target=instrument_target)
    action_sql = BASE_ACTION_INSERT.format(target=action_target)
    for index, quarter_id in enumerate(quarters, start=1):
        connection.execute(instrument_sql, (quarter_id,))
        connection.execute(action_sql, (quarter_id,))
        if commit_each_quarter:
            connection.commit()
        if progress:
            progress(index, len(quarters), quarter_id)


def refresh_in_transaction(connection: sqlite3.Connection) -> None:
    """Refresh production tables inside the caller's existing transaction."""
    connection.execute("DELETE FROM CUSIP_INSTRUMENT_QUARTER_SUMMARY")
    connection.execute("DELETE FROM CUSIP_BASE_QUARTER_ACTION_ACTIVITY")
    populate(
        connection,
        "CUSIP_INSTRUMENT_QUARTER_SUMMARY",
        "CUSIP_BASE_QUARTER_ACTION_ACTIVITY",
    )


def build(database: Path) -> tuple[int, int]:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")

    try:
        from .build_instruments import INSTRUMENT_SCHEMA, execute_statements
    except ImportError:
        from build_instruments import INSTRUMENT_SCHEMA, execute_statements

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA cache_size = -262144")
    try:
        execute_statements(connection, INSTRUMENT_SCHEMA)
        connection.executescript(STAGE_SCHEMA)

        def report(index: int, total: int, quarter_id: int) -> None:
            print(f"[{index}/{total}] built {quarter_id}", flush=True)

        populate(
            connection,
            "CUSIP_INSTRUMENT_QUARTER_SUMMARY_STAGE",
            "CUSIP_BASE_QUARTER_ACTION_ACTIVITY_STAGE",
            commit_each_quarter=True,
            progress=report,
        )

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM CUSIP_INSTRUMENT_QUARTER_SUMMARY")
        connection.execute(
            "INSERT INTO CUSIP_INSTRUMENT_QUARTER_SUMMARY "
            "SELECT * FROM CUSIP_INSTRUMENT_QUARTER_SUMMARY_STAGE"
        )
        connection.execute("DELETE FROM CUSIP_BASE_QUARTER_ACTION_ACTIVITY")
        connection.execute(
            "INSERT INTO CUSIP_BASE_QUARTER_ACTION_ACTIVITY "
            "SELECT * FROM CUSIP_BASE_QUARTER_ACTION_ACTIVITY_STAGE"
        )
        foreign_key_errors = []
        for table in (
            "CUSIP_INSTRUMENT_QUARTER_SUMMARY",
            "CUSIP_BASE_QUARTER_ACTION_ACTIVITY",
        ):
            foreign_key_errors.extend(
                connection.execute(
                    f"PRAGMA foreign_key_check({table})"
                ).fetchall()
            )
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:5]}"
            )
        connection.commit()
        return (
            connection.execute(
                "SELECT COUNT(*) FROM CUSIP_INSTRUMENT_QUARTER_SUMMARY"
            ).fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM CUSIP_BASE_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_DIR / "form13f.sqlite3",
    )
    arguments = parser.parse_args()
    try:
        instrument_count, action_count = build(
            arguments.database.expanduser().resolve()
        )
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"CUSIP instrument-type summaries: {instrument_count:,}")
    print(f"CUSIP base-action summaries: {action_count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
