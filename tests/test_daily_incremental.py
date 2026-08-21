from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.backend import queries
from etl import daily_edgar


PROJECT_DIR = Path(__file__).resolve().parents[1]


class DailyIncrementalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="13f-daily-test-"
        )
        self.database = Path(self.temporary_directory.name) / "test.sqlite3"
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            (PROJECT_DIR / "schema.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            "INSERT INTO QUARTER VALUES "
            "(202601, '2026Q1', '2026-03-31', 2026, 1, NULL)"
        )
        connection.execute(
            "INSERT INTO QUARTER VALUES "
            "(202602, '2026Q2', '2026-06-30', 2026, 2, 202601)"
        )
        connection.execute(
            "INSERT INTO DAILY_CIK_QUARTER_STATUS "
            "VALUES (202602, 'PARTIAL', 1, 'unchanged')"
        )
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_SUMMARY (
                MANAGER_CIK, QUARTER_ID, PORTFOLIO_VALUE_USD,
                INSTRUMENT_COUNT, CUSIP_COUNT, COMMON_STOCK_VALUE_USD,
                ETF_VALUE_USD, CALL_VALUE_USD, PUT_VALUE_USD,
                UNKNOWN_VALUE_USD, LARGEST_HOLDING_CUSIP,
                LARGEST_HOLDING_ISSUER, LARGEST_POSITION_VALUE_USD,
                LARGEST_POSITION_WEIGHT, TOP_10_WEIGHT,
                HAS_SHARED_DISCRETION, HAS_CONFIDENTIAL_OMISSION,
                VALUE_QUALITY_STATUS, UPDATED_AT
            ) VALUES (
                '0000000002', 202602, 999, 1, 1, 0, 0, 0, 0, 999,
                '999999999', 'UNCHANGED', 999, 1.0, 1.0, 0, 0,
                'OK', 'unchanged'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO DAILY_EDGAR_RUN (INDEX_URL, STATUS, STARTED_AT)
            VALUES ('test', 'RUNNING', 'now')
            """
        )
        self.run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def insert_filing(
        self,
        accession: str,
        *,
        filing_date: str,
        value: int,
        amendment: bool = False,
    ) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        submission_type = "13F-HR/A" if amendment else "13F-HR"
        connection.execute(
            "INSERT INTO SUBMISSION VALUES (?, ?, ?, '1', '30-JUN-2026')",
            (accession, filing_date, submission_type),
        )
        connection.execute(
            """
            INSERT INTO COVERPAGE VALUES (
                ?, '30-JUN-2026', ?, ?, ?, 'N', NULL, NULL, NULL,
                'TEST CAPITAL MANAGEMENT', '1 TEST ST', NULL, 'TORONTO',
                'ON', 'A1A1A1', '13F HOLDINGS REPORT', '028-TEST',
                NULL, NULL, 'N', NULL
            )
            """,
            (
                accession,
                "Y" if amendment else "N",
                1 if amendment else None,
                "RESTATEMENT" if amendment else None,
            ),
        )
        connection.execute(
            "INSERT INTO SUMMARYPAGE VALUES (?, 0, 1, ?, 'N')",
            (accession, value),
        )
        connection.execute(
            """
            INSERT INTO INFOTABLE VALUES (
                ?, 1, 'SPACE EXPLORATION TECHN CORP', 'CLASS A COM STK',
                '84615Q103', NULL, ?, 100,
                'SH', NULL, 'SOLE', NULL, 100, 0, 0
            )
            """,
            (accession, value),
        )
        connection.execute(
            """
            INSERT INTO DAILY_EDGAR_ACCESSION VALUES (
                ?, ?, 'directory', 'primary', NULL, ?, NULL, 'now'
            )
            """,
            (accession, self.run_id, "0" * 64),
        )
        connection.commit()
        connection.close()

    def test_discovery_is_newest_first(self) -> None:
        index = b"""CIK|Company Name|Form Type|Date Filed|Filename
2|OLDER|13F-HR|2026-08-19|edgar/data/2/0000000002-26-000001.txt
1|NEWER|13F-HR|2026-08-20|edgar/data/1/0000000001-26-000001.txt
"""
        filings = daily_edgar.discover_filings(index)
        self.assertEqual([row.company_name for row in filings], ["NEWER", "OLDER"])

    def test_immediate_feed_scoped_publish_amendment_and_retry(self) -> None:
        base = "0000000001-26-000001"
        amendment = "0000000001-26-000002"
        self.insert_filing(base, filing_date="20-AUG-2026", value=12_345)

        connection = sqlite3.connect(self.database)
        latest = connection.execute(queries.LATEST_FILINGS, (10, 0)).fetchall()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0][1], "TEST CAPITAL MANAGEMENT")
        self.assertEqual(latest[0][8:11], (12_345, 1, 1))
        connection.close()

        self.assertEqual(
            daily_edgar.publish_accessions(self.database, {base}),
            {"filings": 1, "institutions": 1},
        )
        self.insert_filing(
            amendment,
            filing_date="21-AUG-2026",
            value=54_321,
            amendment=True,
        )
        daily_edgar.publish_accessions(self.database, {amendment})
        daily_edgar.publish_accessions(self.database, {amendment})

        connection = sqlite3.connect(self.database)
        canonical = connection.execute(
            """
            SELECT LATEST_ACCESSION_NUMBER, RESOLUTION_STATUS,
                   IS_ANALYTICS_READY, HAS_AMENDMENT
            FROM CANONICAL_FILING
            """
        ).fetchone()
        self.assertEqual(canonical, (amendment, "RESOLVED", 1, 1))
        components = connection.execute(
            """
            SELECT ACCESSION_NUMBER, COMPONENT_TYPE, IS_EFFECTIVE,
                   SUPERSEDED_BY_ACCESSION_NUMBER
            FROM CANONICAL_FILING_COMPONENT
            ORDER BY COMPONENT_SEQUENCE
            """
        ).fetchall()
        self.assertEqual(
            components,
            [
                (base, "BASE", 0, amendment),
                (amendment, "RESTATEMENT", 1, None),
            ],
        )
        summary = connection.execute(
            """
            SELECT PORTFOLIO_VALUE_USD, CUSIP_COUNT
            FROM DAILY_CIK_QUARTER_SUMMARY
            WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602
            """
        ).fetchone()
        self.assertEqual(summary, (54_321, 1))
        classification = connection.execute(
            """
            SELECT SECURITY_TYPE
            FROM DAILY_CIK_HOLDING
            WHERE MANAGER_CIK = '0000000001'
              AND QUARTER_ID = 202602
              AND CUSIP = '84615Q103'
            """
        ).fetchone()
        self.assertEqual(classification, ("COMMON_STOCK",))
        unaffected = connection.execute(
            """
            SELECT PORTFOLIO_VALUE_USD, UPDATED_AT
            FROM DAILY_CIK_QUARTER_SUMMARY
            WHERE MANAGER_CIK = '0000000002' AND QUARTER_ID = 202602
            """
        ).fetchone()
        self.assertEqual(unaffected, (999, "unchanged"))
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM DAILY_EDGAR_PUBLICATION"
            ).fetchone()[0],
            2,
        )
        latest = connection.execute(queries.LATEST_FILINGS, (10, 0)).fetchall()
        self.assertEqual([row[2] for row in latest], [amendment, base])
        connection.close()

        self.assertEqual(daily_edgar.rollback_daily(self.database), 2)
        connection = sqlite3.connect(self.database)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM SUBMISSION").fetchone()[0],
            0,
        )
        self.assertIsNone(
            connection.execute(
                """
                SELECT 1 FROM sqlite_schema
                WHERE type = 'table' AND name = 'DAILY_EDGAR_PUBLICATION'
                """
            ).fetchone()
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
