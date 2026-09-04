#!/usr/bin/env python3
"""Load reviewed manager/person associations without altering SEC filing data."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_DIR / "curated" / "notable_people.csv"

NOTABLE_PEOPLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS NOTABLE_PERSON (
    PERSON_ID INTEGER PRIMARY KEY,
    DISPLAY_NAME TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS CIK_NOTABLE_PERSON (
    CIK CHAR(10) NOT NULL,
    PERSON_ID INTEGER NOT NULL,
    ROLE TEXT,
    RELATIONSHIP_STATUS TEXT NOT NULL
        CHECK (RELATIONSHIP_STATUS IN ('CURRENT', 'FORMER', 'ASSOCIATED')),
    SOURCE_URL TEXT NOT NULL,
    SOURCE_LABEL TEXT NOT NULL,
    SOURCE_TYPE TEXT NOT NULL
        CHECK (SOURCE_TYPE IN ('SEC', 'OFFICIAL', 'CURATED_DIRECTORY', 'OTHER')),
    REVIEW_STATUS TEXT NOT NULL
        CHECK (REVIEW_STATUS IN ('PUBLISHED', 'DRAFT')),
    VERIFIED_ON DATE NOT NULL,
    DISPLAY_ORDER INTEGER NOT NULL DEFAULT 1,
    CURATION_SET TEXT NOT NULL,
    PRIMARY KEY (CIK, PERSON_ID),
    FOREIGN KEY (PERSON_ID)
        REFERENCES NOTABLE_PERSON (PERSON_ID) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS CIK_NOTABLE_PERSON_CIK_ORDER_IDX
    ON CIK_NOTABLE_PERSON (CIK, REVIEW_STATUS, DISPLAY_ORDER, PERSON_ID);
"""

FIELDS = (
    "cik",
    "person_name",
    "role",
    "relationship_status",
    "source_url",
    "source_label",
    "source_type",
    "review_status",
    "verified_on",
    "display_order",
    "curation_set",
)


def read_rows(source: Path) -> list[dict[str, object]]:
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"unexpected columns in {source}: {reader.fieldnames}")
        records: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for line_number, raw in enumerate(reader, start=2):
            cik = raw["cik"].strip()
            name = raw["person_name"].strip()
            key = (cik, name.casefold())
            if not re.fullmatch(r"\d{10}", cik):
                raise ValueError(f"line {line_number}: CIK must contain 10 digits")
            if not name:
                raise ValueError(f"line {line_number}: person_name is required")
            source_url = raw["source_url"].strip()
            source_host = (urlparse(source_url).hostname or "").lower()
            if source_host != "sec.gov" and not source_host.endswith(".sec.gov"):
                raise ValueError(
                    f"line {line_number}: source_url must be an SEC.gov URL"
                )
            if raw["source_type"].strip() != "SEC":
                raise ValueError(f"line {line_number}: source_type must be SEC")
            if key in seen:
                raise ValueError(f"line {line_number}: duplicate association {key}")
            seen.add(key)
            record: dict[str, object] = {
                field: (raw[field].strip() or None) for field in FIELDS
            }
            record["display_order"] = int(raw["display_order"])
            for required in (
                "relationship_status", "source_url", "source_label",
                "source_type", "review_status", "verified_on", "curation_set",
            ):
                if record[required] is None:
                    raise ValueError(f"line {line_number}: {required} is required")
            records.append(record)
    return records


def load(database: Path, source: Path = DEFAULT_SOURCE) -> dict[str, int]:
    records = read_rows(source)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(NOTABLE_PEOPLE_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            DELETE FROM CIK_NOTABLE_PERSON
            WHERE lower(SOURCE_URL) NOT LIKE 'https://sec.gov/%'
              AND lower(SOURCE_URL) NOT LIKE 'https://%.sec.gov/%'
            """
        )
        known_ciks = {
            row[0] for row in connection.execute(
                "SELECT CIK FROM CIK WHERE CIK IN ({})".format(
                    ",".join("?" for _ in records)
                ),
                [record["cik"] for record in records],
            )
        } if records else set()
        missing = sorted({str(record["cik"]) for record in records} - known_ciks)
        if missing:
            raise ValueError(
                "curated associations reference CIKs absent from CIK: "
                + ", ".join(missing)
            )

        curation_sets = sorted({str(record["curation_set"]) for record in records})
        connection.executemany(
            "DELETE FROM CIK_NOTABLE_PERSON WHERE CURATION_SET = ?",
            ((value,) for value in curation_sets),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO NOTABLE_PERSON (DISPLAY_NAME) VALUES (?)",
            ((record["person_name"],) for record in records),
        )
        connection.executemany(
            """
            INSERT INTO CIK_NOTABLE_PERSON (
                CIK, PERSON_ID, ROLE, RELATIONSHIP_STATUS, SOURCE_URL,
                SOURCE_LABEL, SOURCE_TYPE, REVIEW_STATUS, VERIFIED_ON,
                DISPLAY_ORDER, CURATION_SET
            )
            SELECT ?, PERSON_ID, ?, ?, ?, ?, ?, ?, ?, ?, ?
            FROM NOTABLE_PERSON WHERE DISPLAY_NAME = ?
            """,
            (
                (
                    record["cik"], record["role"],
                    record["relationship_status"], record["source_url"],
                    record["source_label"], record["source_type"],
                    record["review_status"], record["verified_on"],
                    record["display_order"], record["curation_set"],
                    record["person_name"],
                )
                for record in records
            ),
        )
        connection.execute(
            "DELETE FROM NOTABLE_PERSON WHERE PERSON_ID NOT IN "
            "(SELECT PERSON_ID FROM CIK_NOTABLE_PERSON)"
        )
        connection.commit()
        return {
            "people": connection.execute(
                "SELECT COUNT(*) FROM NOTABLE_PERSON"
            ).fetchone()[0],
            "associations": connection.execute(
                "SELECT COUNT(*) FROM CIK_NOTABLE_PERSON"
            ).fetchone()[0],
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    arguments = parser.parse_args()
    counts = load(arguments.database, arguments.source)
    print(
        f"Loaded {counts['associations']:,} manager/person associations "
        f"for {counts['people']:,} people"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
