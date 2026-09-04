from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.backend import queries
from etl.load_notable_people import FIELDS, load


class NotablePeopleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.database = root / "test.sqlite3"
        self.source = root / "notable.csv"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE CIK (CIK CHAR(10) PRIMARY KEY)")
            connection.execute("INSERT INTO CIK VALUES ('0001536411')")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_source(self, name: str = "Stanley Druckenmiller") -> None:
        with self.source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(
                {
                    "cik": "0001536411",
                    "person_name": name,
                    "role": "Founder",
                    "relationship_status": "CURRENT",
                    "source_url": "https://www.sec.gov/Archives/test-filing.htm",
                    "source_label": "SEC Schedule 13D/G filing",
                    "source_type": "SEC",
                    "review_status": "PUBLISHED",
                    "verified_on": "2026-09-04",
                    "display_order": "1",
                    "curation_set": "TEST",
                }
            )

    def test_load_is_repeatable_and_keeps_provenance_internal(self) -> None:
        self.write_source()
        self.assertEqual(load(self.database, self.source)["associations"], 1)
        self.assertEqual(load(self.database, self.source)["associations"], 1)
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            result = dict(
                connection.execute(
                    queries.INSTITUTION_NOTABLE_PEOPLE, ("0001536411",)
                ).fetchone()
            )
        self.assertEqual(result["name"], "Stanley Druckenmiller")
        self.assertEqual(result["role"], "Founder")
        with sqlite3.connect(self.database) as connection:
            source = connection.execute(
                "SELECT SOURCE_TYPE, SOURCE_URL FROM CIK_NOTABLE_PERSON"
            ).fetchone()
        self.assertEqual(
            source,
            ("SEC", "https://www.sec.gov/Archives/test-filing.htm"),
        )

    def test_non_sec_source_is_rejected(self) -> None:
        self.write_source()
        text = self.source.read_text(encoding="utf-8").replace(
            "https://www.sec.gov/Archives/test-filing.htm",
            "https://example.com/unapproved-source",
        )
        self.source.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be an SEC.gov URL"):
            load(self.database, self.source)

    def test_source_replacement_removes_stale_association(self) -> None:
        self.write_source()
        load(self.database, self.source)
        self.write_source("Replacement Person")
        load(self.database, self.source)
        with sqlite3.connect(self.database) as connection:
            names = connection.execute(
                "SELECT DISPLAY_NAME FROM NOTABLE_PERSON"
            ).fetchall()
        self.assertEqual(names, [("Replacement Person",)])

    def test_missing_manager_rolls_back_rows(self) -> None:
        self.write_source()
        load(self.database, self.source)
        text = self.source.read_text(encoding="utf-8").replace(
            "0001536411", "0000000001"
        )
        self.source.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "absent from CIK"):
            load(self.database, self.source)
        with sqlite3.connect(self.database) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM CIK_NOTABLE_PERSON"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_associations_survive_cik_dimension_rebuild(self) -> None:
        self.write_source()
        load(self.database, self.source)
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("DELETE FROM CIK")
            remaining = connection.execute(
                "SELECT COUNT(*) FROM CIK_NOTABLE_PERSON"
            ).fetchone()[0]
            connection.execute("INSERT INTO CIK VALUES ('0001536411')")
        self.assertEqual(remaining, 1)


if __name__ == "__main__":
    unittest.main()
