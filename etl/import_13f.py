#!/usr/bin/env python3
"""Build a SQLite database from an SEC Form 13F quarterly TSV data set."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


TABLES = (
    "SUBMISSION",
    "COVERPAGE",
    "OTHERMANAGER",
    "SIGNATURE",
    "SUMMARYPAGE",
    "OTHERMANAGER2",
    "INFOTABLE",
)

NUMBER_COLUMNS = {
    "COVERPAGE": {"AMENDMENTNO"},
    "OTHERMANAGER": {"OTHERMANAGER_SK"},
    "SUMMARYPAGE": {
        "OTHERINCLUDEDMANAGERSCOUNT",
        "TABLEENTRYTOTAL",
        "TABLEVALUETOTAL",
    },
    "OTHERMANAGER2": {"SEQUENCENUMBER"},
    "INFOTABLE": {
        "INFOTABLE_SK",
        "VALUE",
        "SSHPRNAMT",
        "VOTING_AUTH_SOLE",
        "VOTING_AUTH_SHARED",
        "VOTING_AUTH_NONE",
    },
}

# The SEC 01jun2025-31aug2025 data set contains one blank NAMEOFISSUER even
# though FORM13F_metadata.json declares the column required. Preserve that
# as-filed blank as an empty string so the documented NOT NULL raw schema does
# not need to be weakened or populated with invented data.
PRESERVE_EMPTY_STRING_COLUMNS = {
    "INFOTABLE": {"NAMEOFISSUER"},
}


def table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def converted_rows(
    reader: csv.reader,
    numeric_indexes: set[int],
    preserve_empty_indexes: set[int],
):
    for line_number, row in enumerate(reader, start=2):
        converted = []
        for index, value in enumerate(row):
            if value == "" and index in preserve_empty_indexes:
                converted.append("")
            elif value == "":
                converted.append(None)
            elif index in numeric_indexes:
                try:
                    converted.append(int(value))
                except ValueError as error:
                    raise ValueError(
                        f"line {line_number}: expected an integer, got {value!r}"
                    ) from error
            else:
                converted.append(value)
        yield tuple(converted)


def import_table(
    connection: sqlite3.Connection, source_dir: Path, table: str
) -> int:
    path = source_dir / f"{table}.tsv"
    columns = table_columns(connection, table)
    placeholders = ", ".join("?" for _ in columns)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    statement = f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})'

    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.reader(input_file, delimiter="\t")
        header = next(reader)
        if header != columns:
            raise ValueError(
                f"{path}: header does not match schema\n"
                f"expected: {columns}\n"
                f"actual:   {header}"
            )
        numeric_indexes = {
            columns.index(column) for column in NUMBER_COLUMNS.get(table, set())
        }
        preserve_empty_indexes = {
            columns.index(column)
            for column in PRESERVE_EMPTY_STRING_COLUMNS.get(table, set())
        }
        before = connection.total_changes
        try:
            connection.executemany(
                statement,
                converted_rows(
                    reader,
                    numeric_indexes,
                    preserve_empty_indexes,
                ),
            )
        except Exception as error:
            raise RuntimeError(f"failed while importing {path}: {error}") from error
        return connection.total_changes - before


def build_database(source_dir: Path, schema_path: Path, output_path: Path) -> None:
    temporary_path = output_path.with_suffix(output_path.suffix + ".building")
    temporary_path.unlink(missing_ok=True)

    connection = sqlite3.connect(temporary_path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA cache_size = -262144")
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.execute("BEGIN")

        for table in TABLES:
            row_count = import_table(connection, source_dir, table)
            print(f"{table}: {row_count:,} rows", flush=True)

        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    except Exception:
        connection.rollback()
        connection.close()
        temporary_path.unlink(missing_ok=True)
        raise
    else:
        connection.close()

    temporary_path.replace(output_path)


def append_database(
    source_dir: Path,
    output_path: Path,
    verify_integrity: bool = True,
) -> None:
    if not output_path.is_file():
        raise FileNotFoundError(f"database does not exist: {output_path}")

    connection = sqlite3.connect(output_path)
    try:
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA cache_size = -262144")

        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        missing_tables = set(TABLES) - existing_tables
        if missing_tables:
            raise ValueError(
                "database is missing required tables: "
                + ", ".join(sorted(missing_tables))
            )

        connection.execute("BEGIN IMMEDIATE")
        for table in TABLES:
            row_count = import_table(connection, source_dir, table)
            print(f"{table}: appended {row_count:,} rows", flush=True)

        if verify_integrity:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project_dir / "raw_date")
    parser.add_argument("--schema", type=Path, default=project_dir / "schema.sql")
    parser.add_argument(
        "--output", type=Path, default=project_dir / "form13f.sqlite3"
    )
    parser.add_argument(
        "--replace", action="store_true", help="replace an existing output database"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="atomically append the source files to an existing database",
    )
    arguments = parser.parse_args()

    if arguments.append and arguments.replace:
        parser.error("--append and --replace cannot be used together")
    if arguments.output.exists() and not (arguments.replace or arguments.append):
        parser.error(f"output already exists: {arguments.output} (use --replace)")

    try:
        if arguments.append:
            append_database(arguments.source, arguments.output)
        else:
            build_database(arguments.source, arguments.schema, arguments.output)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    action = "Updated" if arguments.append else "Created"
    print(f"{action} {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
