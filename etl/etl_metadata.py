"""ETL batch provenance and idempotent SEC quarterly data-set registration."""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    from .import_13f import TABLES
except ImportError:  # Allow imports from directly executed ETL scripts.
    from import_13f import TABLES


ETL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ETL_BATCH (
    ETL_BATCH_ID INTEGER PRIMARY KEY,
    DATASET_QUARTER VARCHAR(6),
    ZIP_FILENAME TEXT NOT NULL,
    ZIP_SHA256 CHAR(64) NOT NULL UNIQUE,
    SOURCE_PATH TEXT NOT NULL,
    IMPORT_MODE TEXT NOT NULL
        CHECK (IMPORT_MODE IN ('APPEND', 'REGISTER_EXISTING')),
    STATUS TEXT NOT NULL
        CHECK (STATUS IN ('RUNNING', 'COMPLETED', 'FAILED')),
    STARTED_AT TEXT NOT NULL,
    COMPLETED_AT TEXT,
    ERROR_MESSAGE TEXT
);

CREATE TABLE IF NOT EXISTS ETL_BATCH_TABLE_COUNT (
    ETL_BATCH_ID INTEGER NOT NULL,
    TABLE_NAME TEXT NOT NULL,
    SOURCE_ROW_COUNT INTEGER NOT NULL,
    DATABASE_ROW_COUNT INTEGER,
    PRIMARY KEY (ETL_BATCH_ID, TABLE_NAME),
    FOREIGN KEY (ETL_BATCH_ID)
        REFERENCES ETL_BATCH (ETL_BATCH_ID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ETL_BATCH_ACCESSION (
    ETL_BATCH_ID INTEGER NOT NULL,
    ACCESSION_NUMBER VARCHAR2(25) NOT NULL,
    PRIMARY KEY (ETL_BATCH_ID, ACCESSION_NUMBER),
    UNIQUE (ACCESSION_NUMBER),
    FOREIGN KEY (ETL_BATCH_ID)
        REFERENCES ETL_BATCH (ETL_BATCH_ID) ON DELETE CASCADE,
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_quarter_from_name(path: Path) -> str | None:
    match = re.search(r"(?i)(\d{4})q([1-4])", path.stem)
    if not match:
        return None
    return f"{match.group(1)}Q{match.group(2)}"


def source_row_counts(source_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        path = source_dir / f"{table}.tsv"
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, delimiter="\t")
            next(reader)
            counts[table] = sum(1 for _ in reader)
    return counts


def source_accessions(source_dir: Path) -> list[str]:
    path = source_dir / "SUBMISSION.tsv"
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        accessions = [row["ACCESSION_NUMBER"] for row in reader]
    if len(accessions) != len(set(accessions)):
        raise ValueError(f"{path} contains duplicate accession numbers")
    return accessions


def execute_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(ETL_SCHEMA)


def _load_accession_stage(
    connection: sqlite3.Connection, accessions: list[str]
) -> None:
    connection.execute("DROP TABLE IF EXISTS temp.ETL_SOURCE_ACCESSION")
    connection.execute(
        """
        CREATE TEMP TABLE ETL_SOURCE_ACCESSION (
            ACCESSION_NUMBER TEXT PRIMARY KEY
        )
        """
    )
    connection.executemany(
        "INSERT INTO ETL_SOURCE_ACCESSION VALUES (?)",
        ((accession,) for accession in accessions),
    )


def database_row_counts(
    connection: sqlite3.Connection, accessions: list[str]
) -> dict[str, int]:
    _load_accession_stage(connection, accessions)
    return {
        table: connection.execute(
            f"""
            SELECT COUNT(*)
            FROM "{table}"
            WHERE ACCESSION_NUMBER IN (
                SELECT ACCESSION_NUMBER FROM ETL_SOURCE_ACCESSION
            )
            """
        ).fetchone()[0]
        for table in TABLES
    }


def _validate_counts(
    expected: dict[str, int], actual: dict[str, int]
) -> None:
    mismatches = {
        table: (expected[table], actual[table])
        for table in TABLES
        if expected[table] != actual[table]
    }
    if mismatches:
        details = ", ".join(
            f"{table}: source={source:,}, database={database:,}"
            for table, (source, database) in mismatches.items()
        )
        raise ValueError(f"source/database row-count mismatch: {details}")


def prepare_batch(
    database: Path, zip_path: Path, source_dir: Path
) -> tuple[int, bool]:
    """Return ``(batch_id, should_append)`` for a validated data set."""
    zip_hash = sha256_file(zip_path)
    expected = source_row_counts(source_dir)
    accessions = source_accessions(source_dir)

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        execute_schema(connection)
        existing_batch = connection.execute(
            """
            SELECT ETL_BATCH_ID, STATUS
            FROM ETL_BATCH
            WHERE ZIP_SHA256 = ?
            """,
            (zip_hash,),
        ).fetchone()
        if existing_batch and existing_batch[1] == "COMPLETED":
            actual = database_row_counts(connection, accessions)
            _validate_counts(expected, actual)
            return int(existing_batch[0]), False
        if existing_batch:
            batch_id = int(existing_batch[0])
            connection.execute(
                """
                UPDATE ETL_BATCH
                SET STATUS = 'RUNNING',
                    STARTED_AT = ?,
                    COMPLETED_AT = NULL,
                    ERROR_MESSAGE = NULL
                WHERE ETL_BATCH_ID = ?
                """,
                (utc_now(), batch_id),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO ETL_BATCH (
                    DATASET_QUARTER,
                    ZIP_FILENAME,
                    ZIP_SHA256,
                    SOURCE_PATH,
                    IMPORT_MODE,
                    STATUS,
                    STARTED_AT
                )
                VALUES (?, ?, ?, ?, 'APPEND', 'RUNNING', ?)
                """,
                (
                    dataset_quarter_from_name(zip_path),
                    zip_path.name,
                    zip_hash,
                    str(zip_path),
                    utc_now(),
                ),
            )
            batch_id = int(cursor.lastrowid)

        connection.executemany(
            """
            INSERT INTO ETL_BATCH_TABLE_COUNT (
                ETL_BATCH_ID, TABLE_NAME, SOURCE_ROW_COUNT
            )
            VALUES (?, ?, ?)
            ON CONFLICT (ETL_BATCH_ID, TABLE_NAME)
            DO UPDATE SET
                SOURCE_ROW_COUNT = excluded.SOURCE_ROW_COUNT,
                DATABASE_ROW_COUNT = NULL
            """,
            (
                (batch_id, table, expected[table])
                for table in TABLES
            ),
        )

        actual = database_row_counts(connection, accessions)
        existing_accessions = actual["SUBMISSION"]
        if existing_accessions == 0:
            connection.commit()
            return batch_id, True
        if existing_accessions != len(accessions):
            raise ValueError(
                "data set partially overlaps the database: "
                f"{existing_accessions:,}/{len(accessions):,} accessions exist"
            )

        _validate_counts(expected, actual)
        connection.execute(
            """
            UPDATE ETL_BATCH
            SET IMPORT_MODE = 'REGISTER_EXISTING',
                STATUS = 'COMPLETED',
                COMPLETED_AT = ?
            WHERE ETL_BATCH_ID = ?
            """,
            (utc_now(), batch_id),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO ETL_BATCH_ACCESSION (
                ETL_BATCH_ID, ACCESSION_NUMBER
            )
            VALUES (?, ?)
            """,
            ((batch_id, accession) for accession in accessions),
        )
        connection.executemany(
            """
            UPDATE ETL_BATCH_TABLE_COUNT
            SET DATABASE_ROW_COUNT = ?
            WHERE ETL_BATCH_ID = ? AND TABLE_NAME = ?
            """,
            (
                (actual[table], batch_id, table)
                for table in TABLES
            ),
        )
        connection.commit()
        return batch_id, False
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_batch(
    database: Path, batch_id: int, source_dir: Path
) -> None:
    expected = source_row_counts(source_dir)
    accessions = source_accessions(source_dir)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        actual = database_row_counts(connection, accessions)
        _validate_counts(expected, actual)
        connection.executemany(
            """
            INSERT INTO ETL_BATCH_ACCESSION (
                ETL_BATCH_ID, ACCESSION_NUMBER
            )
            VALUES (?, ?)
            """,
            ((batch_id, accession) for accession in accessions),
        )
        connection.executemany(
            """
            UPDATE ETL_BATCH_TABLE_COUNT
            SET DATABASE_ROW_COUNT = ?
            WHERE ETL_BATCH_ID = ? AND TABLE_NAME = ?
            """,
            (
                (actual[table], batch_id, table)
                for table in TABLES
            ),
        )
        connection.execute(
            """
            UPDATE ETL_BATCH
            SET STATUS = 'COMPLETED',
                COMPLETED_AT = ?,
                ERROR_MESSAGE = NULL
            WHERE ETL_BATCH_ID = ?
            """,
            (utc_now(), batch_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def fail_batch(database: Path, batch_id: int, error: Exception) -> None:
    connection = sqlite3.connect(database)
    try:
        execute_schema(connection)
        connection.execute(
            """
            UPDATE ETL_BATCH
            SET STATUS = 'FAILED',
                COMPLETED_AT = ?,
                ERROR_MESSAGE = ?
            WHERE ETL_BATCH_ID = ?
            """,
            (utc_now(), str(error), batch_id),
        )
        connection.commit()
    finally:
        connection.close()
