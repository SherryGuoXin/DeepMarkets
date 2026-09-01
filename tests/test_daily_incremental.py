from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.backend import queries
from etl import (
    build_canonical_filings,
    build_daily_cik,
    build_instruments,
    build_latest_filings,
    daily_edgar,
)


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
            "(QUARTER_ID, STATUS, FILING_COUNT, UPDATED_AT, LATEST_FILING_DATE) "
            "VALUES (202602, 'PARTIAL', 1, 'unchanged', '2026-08-20')"
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
        build_latest_filings.refresh_daily_accession(connection, accession)
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
        quarter = connection.execute(queries.QUARTERS).fetchone()
        self.assertEqual(quarter[0:2], (202602, "2026Q2"))
        self.assertEqual(quarter[4:6], (1, "PARTIAL"))
        self.assertEqual(quarter[7], "2026-08-21")
        overview = connection.execute(
            queries.DAILY_OVERVIEW, (202602,)
        ).fetchone()
        self.assertEqual(overview[2:5], (2, 55_320, 2))
        security = connection.execute(
            """
            SELECT TOTAL_VALUE_USD, MANAGER_COUNT, SECURITY_TYPE
            FROM DAILY_CUSIP_QUARTER_SUMMARY
            WHERE CUSIP = '84615Q103' AND QUARTER_ID = 202602
            """
        ).fetchone()
        self.assertEqual(security, (54_321, 1, "COMMON_STOCK"))
        activity = connection.execute(
            queries.DAILY_ACTIVITY_EXPLORER_ALL,
            tuple([202602, *([""] * 10), 25, 0]),
        ).fetchall()
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0][0:4], (
            "0000000001", "TEST CAPITAL MANAGEMENT",
            "84615Q103", "SPACE EXPLORATION TECHN CORP",
        ))
        holders_sql = queries.DAILY_SECURITY_HOLDERS.format(
            order_expression="H.MARKET_VALUE_USD"
        )
        holders = connection.execute(
            holders_sql,
            (202602, "84615Q103", "", "", "", "", "", "", 25, 0),
        ).fetchall()
        self.assertEqual(len(holders), 1)
        relationship = connection.execute(
            queries.DAILY_RELATIONSHIP_HISTORY_ROW,
            ("0000000001", "84615Q103", 202602),
        ).fetchone()
        self.assertEqual(relationship[0:3], (202602, "2026Q2", 54_321))
        plan = connection.execute(
            "EXPLAIN QUERY PLAN " + queries.LATEST_FILINGS, (10, 0)
        ).fetchall()
        self.assertTrue(
            any("LATEST_FILING_FEED_DATE_IDX" in row[3] for row in plan), plan
        )
        self.assertFalse(any("TEMP B-TREE" in row[3] for row in plan), plan)
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

    def test_bulk_completion_requires_full_filing_coverage(self) -> None:
        accession = "0000000001-26-000001"
        self.insert_filing(accession, filing_date="20-AUG-2026", value=12_345)
        daily_edgar.publish_accessions(self.database, {accession})

        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO ETL_BATCH (
                DATASET_QUARTER, ZIP_FILENAME, ZIP_SHA256, SOURCE_PATH,
                IMPORT_MODE, STATUS, STARTED_AT, COMPLETED_AT
            ) VALUES (
                '2026Q2', '2026q2.zip', ?, 'test',
                'APPEND', 'COMPLETED', 'now', 'now'
            )
            """,
            ("1" * 64,),
        )
        batch_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            "INSERT INTO ETL_BATCH_REPORT_QUARTER VALUES (?, 202602, 2)",
            (batch_id,),
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(RuntimeError, "coverage check failed"):
            build_daily_cik.mark_bulk_complete(self.database)

        connection = sqlite3.connect(self.database)
        self.assertEqual(
            connection.execute(
                "SELECT STATUS FROM DAILY_CIK_QUARTER_STATUS "
                "WHERE QUARTER_ID = 202602"
            ).fetchone(),
            ("PARTIAL",),
        )
        self.assertGreater(
            connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_HOLDING"
            ).fetchone()[0],
            0,
        )
        connection.execute(
            "UPDATE ETL_BATCH_REPORT_QUARTER SET SOURCE_FILING_COUNT = 1"
        )
        connection.commit()
        connection.close()

        self.assertEqual(build_daily_cik.mark_bulk_complete(self.database), 202602)
        connection = sqlite3.connect(self.database)
        status = connection.execute(
            """
            SELECT STATUS, FILING_COUNT, EXPECTED_FILING_COUNT,
                   MISSING_FILING_COUNT
            FROM DAILY_CIK_QUARTER_STATUS WHERE QUARTER_ID = 202602
            """
        ).fetchone()
        self.assertEqual(status, ("COMPLETE", 1, 1, 0))
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_HOLDING"
            ).fetchone()[0],
            0,
        )
        connection.close()

    def test_option_only_daily_security_overrides_stale_common_title(self) -> None:
        accession = "0000000001-26-000003"
        self.insert_filing(accession, filing_date="22-AUG-2026", value=12_345)
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE INFOTABLE SET CUSIP = '67066G105', PUTCALL = 'PUT' "
            "WHERE ACCESSION_NUMBER = ?",
            (accession,),
        )
        build_instruments.seed_reference_data(connection)
        connection.execute("INSERT INTO CUSIP VALUES (1, '67066G105')")
        connection.execute(
            """
            INSERT INTO CUSIP_VARIANT VALUES (
                1, 1, '30-JUN-2026', 'NVIDIA CORPORATION', 'COM', NULL, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO CUSIP_CLASSIFICATION VALUES (
                1, 1, 'RULE_VOTE', 7, 1, 1, 1, 1.0, 'now'
            )
            """
        )
        connection.commit()
        connection.close()

        daily_edgar.publish_accessions(self.database, {accession})
        connection = sqlite3.connect(self.database)
        classification = connection.execute(
            """
            SELECT SECURITY_TYPE, COMMON_STOCK_VALUE_USD, PUT_VALUE_USD
            FROM DAILY_CUSIP_QUARTER_SUMMARY
            WHERE CUSIP = '67066G105' AND QUARTER_ID = 202602
            """
        ).fetchone()
        self.assertEqual(classification, ("OPTION_PUT", 0, 12_345))
        connection.close()

    def test_pre_2023_dollar_filings_are_not_scaled_twice(self) -> None:
        dollar_accession = "0000000003-22-000001"
        thousand_accession = "0000000004-22-000001"
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO QUARTER VALUES "
            "(202104, '2021Q4', '2021-12-31', 2021, 4, NULL)"
        )
        for accession, cik, summary_total in (
            (dollar_accession, "3", 1_000_000),
            (thousand_accession, "4", 1_000),
        ):
            connection.execute(
                "INSERT INTO SUBMISSION VALUES (?, ?, '13F-HR', ?, '31-MAR-2022')",
                (accession, "16-MAY-2022", cik),
            )
            connection.execute(
                """
                INSERT INTO COVERPAGE VALUES (
                    ?, '31-MAR-2022', 'N', NULL, NULL, 'N', NULL, NULL, NULL,
                    'UNIT TEST MANAGER', '1 TEST ST', NULL, 'TORONTO', 'ON',
                    'A1A1A1', '13F HOLDINGS REPORT', '028-TEST',
                    NULL, NULL, 'N', NULL
                )
                """,
                (accession,),
            )
            connection.execute(
                "INSERT INTO SUMMARYPAGE VALUES (?, 0, 10, ?, 'N')",
                (accession, summary_total),
            )
        for line_number in range(1, 11):
            cusip = f"{line_number:09d}"
            for accession, raw_value in (
                (dollar_accession, 100_000),
                (thousand_accession, 100),
            ):
                connection.execute(
                    """
                    INSERT INTO INFOTABLE VALUES (
                        ?, ?, 'TEST ISSUER', 'COMMON STOCK', ?, NULL, ?, 1000,
                        'SH', NULL, 'SOLE', NULL, 1000, 0, 0
                    )
                    """,
                    (accession, line_number, cusip, raw_value),
                )
        connection.commit()
        connection.close()

        build_canonical_filings.build_incremental(
            self.database, {dollar_accession, thousand_accession}
        )
        connection = sqlite3.connect(self.database)
        scales = connection.execute(
            """
            SELECT ACCESSION_NUMBER, VALUE_MULTIPLIER, DETECTION_METHOD
            FROM FILING_VALUE_SCALE
            WHERE ACCESSION_NUMBER IN (?, ?) ORDER BY ACCESSION_NUMBER
            """,
            (dollar_accession, thousand_accession),
        ).fetchall()
        self.assertEqual(
            scales,
            [
                (dollar_accession, 1, "AUTO_LINE_RATIO"),
                (thousand_accession, 1000, "AUTO_LINE_RATIO"),
            ],
        )
        normalized_values = connection.execute(
            """
            SELECT ACCESSION_NUMBER, MIN(VALUE_USD), MAX(VALUE_USD)
            FROM CANONICAL_HOLDING_LINE
            WHERE ACCESSION_NUMBER IN (?, ?)
            GROUP BY ACCESSION_NUMBER ORDER BY ACCESSION_NUMBER
            """,
            (dollar_accession, thousand_accession),
        ).fetchall()
        self.assertEqual(
            normalized_values,
            [
                (dollar_accession, 100_000, 100_000),
                (thousand_accession, 100_000, 100_000),
            ],
        )
        connection.close()

        build_latest_filings.rebuild(self.database)
        connection = sqlite3.connect(self.database)
        feed_values = connection.execute(
            """
            SELECT ACCESSION_NUMBER, REPORTED_ASSETS_USD
            FROM LATEST_FILING_FEED
            WHERE ACCESSION_NUMBER IN (?, ?) ORDER BY ACCESSION_NUMBER
            """,
            (dollar_accession, thousand_accession),
        ).fetchall()
        self.assertEqual(
            feed_values,
            [
                (dollar_accession, 1_000_000),
                (thousand_accession, 1_000_000),
            ],
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
