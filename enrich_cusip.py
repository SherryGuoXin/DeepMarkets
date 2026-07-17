#!/usr/bin/env python3
"""Build stable CUSIP keys and quarter-specific identity history."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


CUSIP_SCHEMA = """
CREATE TABLE IF NOT EXISTS CUSIP (
    CUSIP_ID INTEGER PRIMARY KEY,
    CUSIP CHAR(9) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS CUSIP_VARIANT (
    CUSIP_VARIANT_ID INTEGER PRIMARY KEY,
    CUSIP_ID INTEGER NOT NULL,
    REPORTCALENDARORQUARTER DATE NOT NULL,
    NAMEOFISSUER VARCHAR2(200) NOT NULL,
    TITLEOFCLASS VARCHAR2(150) NOT NULL,
    FIGI VARCHAR2(12),
    OCCURRENCE_COUNT NUMBER(16) NOT NULL,
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS CUSIP_VARIANT_UQ
    ON CUSIP_VARIANT (
        CUSIP_ID,
        REPORTCALENDARORQUARTER,
        NAMEOFISSUER,
        TITLEOFCLASS,
        COALESCE(FIGI, '')
    );

CREATE INDEX IF NOT EXISTS CUSIP_VARIANT_CUSIP_ID_IDX
    ON CUSIP_VARIANT (CUSIP_ID);

CREATE INDEX IF NOT EXISTS INFOTABLE_CUSIP_IDX ON INFOTABLE (CUSIP);
"""

CUSIP_VIEWS = """
DROP VIEW IF EXISTS CUSIP_13F_HOLDING;
DROP VIEW IF EXISTS CUSIP_CURRENT_VARIANT;

CREATE VIEW CUSIP_CURRENT_VARIANT AS
WITH RANKED AS (
    SELECT
        D.CUSIP_ID,
        V.CUSIP_VARIANT_ID,
        D.CUSIP,
        V.REPORTCALENDARORQUARTER,
        V.NAMEOFISSUER,
        V.TITLEOFCLASS,
        V.FIGI,
        V.OCCURRENCE_COUNT,
        ROW_NUMBER() OVER (
            PARTITION BY D.CUSIP_ID
            ORDER BY
                substr(V.REPORTCALENDARORQUARTER, 8, 4) DESC,
                CASE substr(V.REPORTCALENDARORQUARTER, 4, 3)
                    WHEN 'DEC' THEN 12 WHEN 'SEP' THEN 9
                    WHEN 'JUN' THEN 6 WHEN 'MAR' THEN 3 ELSE 0
                END DESC,
                substr(V.REPORTCALENDARORQUARTER, 1, 2) DESC,
                V.OCCURRENCE_COUNT DESC,
                V.NAMEOFISSUER,
                V.TITLEOFCLASS,
                COALESCE(V.FIGI, ''),
                V.CUSIP_VARIANT_ID
        ) AS RN
    FROM CUSIP D
    JOIN CUSIP_VARIANT V USING (CUSIP_ID)
)
SELECT
    CUSIP_ID,
    CUSIP_VARIANT_ID AS CURRENT_CUSIP_VARIANT_ID,
    CUSIP,
    NAMEOFISSUER AS CURRENT_NAMEOFISSUER,
    TITLEOFCLASS AS CURRENT_TITLEOFCLASS,
    FIGI AS CURRENT_FIGI,
    REPORTCALENDARORQUARTER,
    OCCURRENCE_COUNT
FROM RANKED
WHERE RN = 1;

CREATE VIEW CUSIP_13F_HOLDING AS
SELECT
    D.CUSIP_ID,
    V.CUSIP_VARIANT_ID,
    I.CUSIP,
    I.ACCESSION_NUMBER,
    I.INFOTABLE_SK,
    printf('%010d', CAST(S.CIK AS INTEGER)) AS FILING_MANAGER_CIK,
    COALESCE(C.MANAGER_NAME, P.FILINGMANAGER_NAME) AS FILING_MANAGER_NAME,
    S.FILING_DATE,
    S.SUBMISSIONTYPE,
    S.PERIODOFREPORT,
    P.REPORTTYPE,
    P.FORM13FFILENUMBER,
    I.NAMEOFISSUER,
    I.TITLEOFCLASS,
    I.FIGI,
    I.VALUE,
    I.SSHPRNAMT,
    I.SSHPRNAMTTYPE,
    I.PUTCALL,
    I.INVESTMENTDISCRETION,
    I.OTHERMANAGER,
    I.VOTING_AUTH_SOLE,
    I.VOTING_AUTH_SHARED,
    I.VOTING_AUTH_NONE
FROM INFOTABLE I
JOIN SUBMISSION S USING (ACCESSION_NUMBER)
LEFT JOIN COVERPAGE P USING (ACCESSION_NUMBER)
JOIN CUSIP D ON D.CUSIP = I.CUSIP
LEFT JOIN CUSIP_VARIANT V
    ON V.CUSIP_ID = D.CUSIP_ID
   AND V.REPORTCALENDARORQUARTER = P.REPORTCALENDARORQUARTER
   AND V.NAMEOFISSUER = I.NAMEOFISSUER
   AND V.TITLEOFCLASS = I.TITLEOFCLASS
   AND V.FIGI IS I.FIGI
LEFT JOIN CIK C
    ON C.CIK = printf('%010d', CAST(S.CIK AS INTEGER));
"""

STAGE_SQL = """
DROP TABLE IF EXISTS temp.CUSIP_VARIANT_STAGE;
CREATE TEMP TABLE CUSIP_VARIANT_STAGE AS
SELECT
    I.CUSIP,
    P.REPORTCALENDARORQUARTER,
    I.NAMEOFISSUER,
    I.TITLEOFCLASS,
    I.FIGI,
    COUNT(*) AS OCCURRENCE_COUNT
FROM INFOTABLE I
JOIN COVERPAGE P USING (ACCESSION_NUMBER)
GROUP BY
    I.CUSIP,
    P.REPORTCALENDARORQUARTER,
    I.NAMEOFISSUER,
    I.TITLEOFCLASS,
    I.FIGI;

CREATE UNIQUE INDEX temp.CUSIP_VARIANT_STAGE_UQ
    ON CUSIP_VARIANT_STAGE (
        CUSIP,
        REPORTCALENDARORQUARTER,
        NAMEOFISSUER,
        TITLEOFCLASS,
        COALESCE(FIGI, '')
    );
"""

SYNC_SQL = """
INSERT OR IGNORE INTO CUSIP (CUSIP)
SELECT DISTINCT CUSIP
FROM CUSIP_VARIANT_STAGE
ORDER BY CUSIP;

INSERT OR IGNORE INTO CUSIP_VARIANT (
    CUSIP_ID,
    REPORTCALENDARORQUARTER,
    NAMEOFISSUER,
    TITLEOFCLASS,
    FIGI,
    OCCURRENCE_COUNT
)
SELECT
    D.CUSIP_ID,
    S.REPORTCALENDARORQUARTER,
    S.NAMEOFISSUER,
    S.TITLEOFCLASS,
    S.FIGI,
    S.OCCURRENCE_COUNT
FROM CUSIP_VARIANT_STAGE S
JOIN CUSIP D USING (CUSIP)
ORDER BY
    D.CUSIP_ID,
    S.REPORTCALENDARORQUARTER,
    S.NAMEOFISSUER,
    S.TITLEOFCLASS,
    COALESCE(S.FIGI, '');

UPDATE CUSIP_VARIANT
SET OCCURRENCE_COUNT = (
    SELECT S.OCCURRENCE_COUNT
    FROM CUSIP_VARIANT_STAGE S
    JOIN CUSIP D ON D.CUSIP = S.CUSIP
    WHERE D.CUSIP_ID = CUSIP_VARIANT.CUSIP_ID
      AND S.REPORTCALENDARORQUARTER = CUSIP_VARIANT.REPORTCALENDARORQUARTER
      AND S.NAMEOFISSUER = CUSIP_VARIANT.NAMEOFISSUER
      AND S.TITLEOFCLASS = CUSIP_VARIANT.TITLEOFCLASS
      AND S.FIGI IS CUSIP_VARIANT.FIGI
)
WHERE EXISTS (
    SELECT 1
    FROM CUSIP_VARIANT_STAGE S
    JOIN CUSIP D ON D.CUSIP = S.CUSIP
    WHERE D.CUSIP_ID = CUSIP_VARIANT.CUSIP_ID
      AND S.REPORTCALENDARORQUARTER = CUSIP_VARIANT.REPORTCALENDARORQUARTER
      AND S.NAMEOFISSUER = CUSIP_VARIANT.NAMEOFISSUER
      AND S.TITLEOFCLASS = CUSIP_VARIANT.TITLEOFCLASS
      AND S.FIGI IS CUSIP_VARIANT.FIGI
);

DELETE FROM CUSIP_VARIANT
WHERE NOT EXISTS (
    SELECT 1
    FROM CUSIP_VARIANT_STAGE S
    JOIN CUSIP D ON D.CUSIP = S.CUSIP
    WHERE D.CUSIP_ID = CUSIP_VARIANT.CUSIP_ID
      AND S.REPORTCALENDARORQUARTER = CUSIP_VARIANT.REPORTCALENDARORQUARTER
      AND S.NAMEOFISSUER = CUSIP_VARIANT.NAMEOFISSUER
      AND S.TITLEOFCLASS = CUSIP_VARIANT.TITLEOFCLASS
      AND S.FIGI IS CUSIP_VARIANT.FIGI
);

DELETE FROM CUSIP
WHERE NOT EXISTS (
    SELECT 1
    FROM CUSIP_VARIANT V
    WHERE V.CUSIP_ID = CUSIP.CUSIP_ID
);
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


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def migrate_legacy_schema(connection: sqlite3.Connection) -> bool:
    columns = table_columns(connection, "CUSIP")
    if not columns or "CUSIP_ID" in columns:
        return False

    connection.execute("DROP VIEW IF EXISTS CUSIP_13F_HOLDING")
    connection.execute("DROP VIEW IF EXISTS CUSIP_CURRENT_VARIANT")
    connection.execute("DROP TABLE IF EXISTS CUSIP_VARIANT")
    connection.execute("DROP TABLE CUSIP")
    return True


def populate(database: Path) -> dict[str, int | bool]:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA cache_size = -262144")
    try:
        connection.execute("BEGIN IMMEDIATE")
        migrated = migrate_legacy_schema(connection)
        execute_statements(connection, CUSIP_SCHEMA)
        execute_statements(connection, STAGE_SQL)
        execute_statements(connection, SYNC_SQL)
        execute_statements(connection, CUSIP_VIEWS)

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

        counts: dict[str, int | bool] = {
            "migrated": migrated,
            "cusips": connection.execute("SELECT COUNT(*) FROM CUSIP").fetchone()[0],
            "variants": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_VARIANT"
            ).fetchone()[0],
            "current_variants": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_CURRENT_VARIANT"
            ).fetchone()[0],
            "holdings": connection.execute(
                "SELECT SUM(OCCURRENCE_COUNT) FROM CUSIP_VARIANT"
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
    parser.add_argument(
        "--database", type=Path, default=project_dir / "form13f.sqlite3"
    )
    arguments = parser.parse_args()

    try:
        counts = populate(arguments.database)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if counts["migrated"]:
        print("Migrated legacy CUSIP tables")
    print(f"CUSIP rows: {counts['cusips']:,}")
    print(f"Quarter-specific CUSIP variants: {counts['variants']:,}")
    print(f"Current CUSIP variants: {counts['current_variants']:,}")
    print(f"Related holding rows: {counts['holdings']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
