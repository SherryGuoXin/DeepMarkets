from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_recoverable_filing_error_is_partial_and_cli_succeeds(self) -> None:
        self.assertEqual(
            daily_edgar.classify_run_status(100, 1, 0, 1), "PARTIAL"
        )
        self.assertEqual(
            daily_edgar.classify_run_status(1, 1, 0, 1), "FAILED"
        )
        counts = {"discovered": 100, "pending": 1, "imported": 0, "failed": 1}
        with mock.patch.object(daily_edgar, "run_daily", return_value=counts), \
             mock.patch.object(
                 sys,
                 "argv",
                 ["daily_edgar", "--user-agent", "test@example.com"],
             ):
            self.assertEqual(daily_edgar.main(), 0)
        counts = {"discovered": 1, "pending": 1, "imported": 0, "failed": 1}
        with mock.patch.object(daily_edgar, "run_daily", return_value=counts), \
             mock.patch.object(
                 sys,
                 "argv",
                 ["daily_edgar", "--user-agent", "test@example.com"],
             ):
            self.assertEqual(daily_edgar.main(), 1)

    def insert_filing(
        self,
        accession: str,
        *,
        filing_date: str,
        value: int,
        amendment: bool = False,
        manager_cik: str = "1",
        period: str = "30-JUN-2026",
        amount: int = 100,
    ) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        submission_type = "13F-HR/A" if amendment else "13F-HR"
        connection.execute(
            "INSERT INTO SUBMISSION VALUES (?, ?, ?, '1', ?)",
            (accession, filing_date, submission_type, period),
        )
        connection.execute(
            "UPDATE SUBMISSION SET CIK = ? WHERE ACCESSION_NUMBER = ?",
            (manager_cik, accession),
        )
        connection.execute(
            """
            INSERT INTO COVERPAGE VALUES (
                ?, ?, ?, ?, ?, 'N', NULL, NULL, NULL,
                'TEST CAPITAL MANAGEMENT', '1 TEST ST', NULL, 'TORONTO',
                'ON', 'A1A1A1', '13F HOLDINGS REPORT', '028-TEST',
                NULL, NULL, 'N', NULL
            )
            """,
            (
                accession,
                period,
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
                '84615Q103', NULL, ?, ?,
                'SH', NULL, 'SOLE', NULL, ?, 0, 0
            )
            """,
            (accession, value, amount, amount),
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

    def test_sec_nested_amendment_type_is_parsed(self) -> None:
        filing = daily_edgar.Filing(
            accession="0000000001-26-000002",
            cik="0000000001",
            company_name="TEST CAPITAL MANAGEMENT",
            form_type="13F-HR/A",
            filing_date="2026-07-08",
            filename="edgar/data/1/0000000001-26-000002.txt",
        )
        for amendment_type in ("RESTATEMENT", "NEW HOLDINGS"):
            with self.subTest(amendment_type=amendment_type):
                primary = f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><filerInfo><periodOfReport>03-31-2026</periodOfReport></filerInfo></headerData>
  <formData><coverPage>
    <reportCalendarOrQuarter>03-31-2026</reportCalendarOrQuarter>
    <isAmendment>true</isAmendment><amendmentNo>1</amendmentNo>
    <amendmentInfo><amendmentType>{amendment_type}</amendmentType></amendmentInfo>
    <filingManager><name>TEST CAPITAL MANAGEMENT</name><address /></filingManager>
    <reportType>13F HOLDINGS REPORT</reportType>
  </coverPage></formData>
</edgarSubmission>""".encode()
                rows = daily_edgar.parsed_rows(filing, primary, None)
                self.assertEqual(rows["COVERPAGE"][0][4], amendment_type)

    def test_missing_nested_amendment_type_repair_republishes_analytics(self) -> None:
        base = "0000000001-26-000001"
        amendment = "0000000001-26-000002"
        self.insert_filing(base, filing_date="20-AUG-2026", value=12_345)
        daily_edgar.publish_accessions(self.database, {base})
        self.insert_filing(
            amendment, filing_date="21-AUG-2026", value=54_321, amendment=True
        )
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE COVERPAGE SET AMENDMENTTYPE = NULL WHERE ACCESSION_NUMBER = ?",
            (amendment,),
        )
        connection.commit()
        connection.close()
        daily_edgar.publish_accessions(self.database, {amendment})

        primary = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <formData><coverPage><isAmendment>true</isAmendment>
    <amendmentInfo><amendmentType>RESTATEMENT</amendmentType></amendmentInfo>
  </coverPage></formData>
</edgarSubmission>"""
        with mock.patch.object(daily_edgar.SecClient, "get", return_value=primary):
            result = daily_edgar.repair_missing_amendment_types(
                self.database, "test@example.com"
            )
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(result["repaired"], 1)
        self.assertEqual(result["failed"], 0)

        connection = sqlite3.connect(self.database)
        canonical = connection.execute(
            "SELECT RESOLUTION_STATUS, IS_ANALYTICS_READY, LATEST_ACCESSION_NUMBER "
            "FROM CANONICAL_FILING WHERE MANAGER_CIK = '0000000001' "
            "AND QUARTER_ID = 202602"
        ).fetchone()
        summary = connection.execute(
            "SELECT PORTFOLIO_VALUE_USD FROM DAILY_CIK_QUARTER_SUMMARY "
            "WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602"
        ).fetchone()
        connection.close()
        self.assertEqual(canonical, ("RESOLVED", 1, amendment))
        self.assertEqual(summary, (54_321,))
        with mock.patch.object(daily_edgar.SecClient, "get") as get:
            retry = daily_edgar.repair_missing_amendment_types(
                self.database, "test@example.com"
            )
        self.assertEqual(retry["candidates"], 0)
        get.assert_not_called()

    def test_mixed_titles_aggregate_to_one_daily_holding(self) -> None:
        accession = "0000000001-26-000010"
        self.insert_filing(accession, filing_date="20-AUG-2026", value=100)
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO INFOTABLE VALUES (
                ?, 2, 'SPACE EXPLORATION TECHN CORP',
                'CLASS A COM STK *A*', '84615Q103', NULL, 50, 25,
                'SH', NULL, 'SOLE', NULL, 25, 0, 0
            )
            """,
            (accession,),
        )
        connection.execute(
            "UPDATE SUMMARYPAGE SET TABLEVALUETOTAL = 150 "
            "WHERE ACCESSION_NUMBER = ?",
            (accession,),
        )
        connection.commit()
        connection.close()

        self.assertEqual(
            daily_edgar.publish_accessions(self.database, {accession}),
            {"filings": 1, "institutions": 1},
        )
        connection = sqlite3.connect(self.database)
        holdings = connection.execute(
            """
            SELECT SECURITY_TYPE, MARKET_VALUE_USD, REPORTED_AMOUNT
            FROM DAILY_CIK_HOLDING
            WHERE MANAGER_CIK = '0000000001'
              AND QUARTER_ID = 202602
              AND CUSIP = '84615Q103'
              AND OPTION_TYPE = 'NONE'
              AND AMOUNT_TYPE = 'SH'
            """
        ).fetchall()
        connection.close()
        self.assertEqual(holdings, [("COMMON_STOCK", 150, 125)])

    def test_amended_prior_quarter_rebuilds_next_quarter_comparison(self) -> None:
        first = "0000000001-26-000101"
        second = "0000000001-26-000102"
        restatement = "0000000001-26-000103"
        self.insert_filing(
            first, filing_date="11-MAY-2026", value=100,
            period="31-MAR-2026", amount=100,
        )
        daily_edgar.publish_accessions(self.database, {first})
        self.insert_filing(
            second, filing_date="14-AUG-2026", value=120,
            period="30-JUN-2026", amount=120,
        )
        daily_edgar.publish_accessions(self.database, {second})

        connection = sqlite3.connect(self.database)
        before = connection.execute(
            "SELECT ACTION, AMOUNT_CHANGE FROM DAILY_CIK_HOLDING "
            "WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602"
        ).fetchone()
        connection.close()
        self.assertEqual(before, ("ADDED", 20))

        self.insert_filing(
            restatement, filing_date="08-JUL-2026", value=110,
            amendment=True, period="31-MAR-2026", amount=110,
        )
        result = daily_edgar.publish_accessions(self.database, {restatement})
        self.assertEqual(result["institutions"], 2)

        connection = sqlite3.connect(self.database)
        after = connection.execute(
            "SELECT ACTION, AMOUNT_CHANGE FROM DAILY_CIK_HOLDING "
            "WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602"
        ).fetchone()
        connection.close()
        self.assertEqual(after, ("ADDED", 10))

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
        security_activity_plan = connection.execute(
            "EXPLAIN QUERY PLAN " + queries.DAILY_SECURITY_ACTIVITY,
            ("84615Q103", 202602),
        ).fetchall()
        self.assertTrue(
            any(
                "DAILY_CIK_HOLDING_CUSIP_QUARTER_IDX" in row[3]
                for row in security_activity_plan
            ),
            security_activity_plan,
        )
        institution_holdings_sql = queries.DAILY_INSTITUTION_HOLDINGS.format(
            order_expression="H.MARKET_VALUE_USD",
            direction="DESC",
        )
        institution_holdings_plan = connection.execute(
            "EXPLAIN QUERY PLAN " + institution_holdings_sql,
            (
                "0000000001", 202602, "", "", "", "", "", "", "",
                25, 0,
            ),
        ).fetchall()
        self.assertTrue(
            any(
                "DAILY_CIK_HOLDING_MANAGER_QUARTER_IDX" in row[3]
                for row in institution_holdings_plan
            ),
            institution_holdings_plan,
        )
        completed_holdings_sql = queries.INSTITUTION_HOLDINGS.format(
            order_expression="H.MARKET_VALUE_USD",
            direction="DESC",
        )
        completed_holdings_plan = connection.execute(
            "EXPLAIN QUERY PLAN " + completed_holdings_sql,
            (
                "0000000001", 202602, "0000000001", 202602,
                "", "", "", "", "", "", "", 25, 0,
            ),
        ).fetchall()
        self.assertGreaterEqual(
            sum(
                "CIK_INSTRUMENT_MANAGER_IDX" in row[3]
                for row in completed_holdings_plan
            ),
            2,
            completed_holdings_plan,
        )
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

    def test_post_batch_filing_reopens_and_seeds_the_full_quarter(self) -> None:
        first = "0000000001-26-000010"
        second = "0000000002-26-000010"
        self.insert_filing(
            first, filing_date="20-AUG-2026", value=12_345, manager_cik="1"
        )
        daily_edgar.publish_accessions(self.database, {first})

        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO CIK_QUARTER_SUMMARY (
                MANAGER_CIK, QUARTER_ID, PORTFOLIO_VALUE_USD,
                INSTRUMENT_COUNT, CUSIP_COUNT, COMMON_STOCK_VALUE_USD,
                ETF_VALUE_USD, CALL_VALUE_USD, PUT_VALUE_USD,
                UNKNOWN_VALUE_USD, HAS_SHARED_DISCRETION,
                HAS_CONFIDENTIAL_OMISSION, VALUE_QUALITY_STATUS
            ) VALUES (
                '0000000001', 202602, 12345, 1, 1, 12345,
                0, 0, 0, 0, 0, 0, 'OK'
            )
            """
        )
        connection.execute(
            "UPDATE DAILY_CIK_QUARTER_STATUS SET STATUS = 'COMPLETE' "
            "WHERE QUARTER_ID = 202602"
        )
        for table in (
            "DAILY_CIK_HOLDING", "DAILY_CIK_QUARTER_ACTIVITY",
            "DAILY_CIK_QUARTER_SUMMARY", "DAILY_CUSIP_QUARTER_SUMMARY",
            "DAILY_CUSIP_QUARTER_ACTIVITY", "DAILY_CUSIP_OPTION_SUMMARY",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.commit()
        connection.close()

        self.insert_filing(
            second, filing_date="02-SEP-2026", value=54_321, manager_cik="2"
        )
        connection = sqlite3.connect(self.database)
        daily_edgar.ensure_schema(connection)
        self.assertIsNone(
            connection.execute(
                "SELECT 1 FROM DAILY_EDGAR_PUBLICATION "
                "WHERE ACCESSION_NUMBER = ?",
                (second,),
            ).fetchone()
        )
        connection.close()
        daily_edgar.publish_accessions(self.database, {second})

        connection = sqlite3.connect(self.database)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_QUARTER_SUMMARY "
                "WHERE QUARTER_ID = 202602"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            connection.execute(
                "SELECT STATUS, FILING_COUNT, LATEST_FILING_DATE "
                "FROM DAILY_CIK_QUARTER_STATUS WHERE QUARTER_ID = 202602"
            ).fetchone(),
            ("PARTIAL", 2, "2026-09-02"),
        )
        connection.execute(
            "UPDATE DAILY_CIK_QUARTER_SUMMARY SET PORTFOLIO_VALUE_USD = 777 "
            "WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602"
        )
        connection.commit()
        connection.close()

        third = "0000000003-26-000010"
        self.insert_filing(
            third, filing_date="03-SEP-2026", value=66_666, manager_cik="3"
        )
        daily_edgar.publish_accessions(self.database, {third})
        connection = sqlite3.connect(self.database)
        self.assertEqual(
            connection.execute(
                "SELECT PORTFOLIO_VALUE_USD FROM DAILY_CIK_QUARTER_SUMMARY "
                "WHERE MANAGER_CIK = '0000000001' AND QUARTER_ID = 202602"
            ).fetchone()[0],
            777,
        )
        self.assertEqual(
            connection.execute(
                "SELECT FILING_COUNT, LATEST_FILING_DATE "
                "FROM DAILY_CIK_QUARTER_STATUS WHERE QUARTER_ID = 202602"
            ).fetchone(),
            (3, "2026-09-03"),
        )
        connection.close()

    def test_probable_identifier_change_is_not_counted_as_trading(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.create_function(
            "ISSUER_KEY", 1, build_instruments.issuer_comparison_key,
            deterministic=True,
        )
        rows = []
        for number in range(1, 26):
            manager = f"{number:010d}"
            rows.extend(
                [
                    (
                        manager, 202602, "438516106", "HONEYWELL INTL INC",
                        "COM", "COMMON_STOCK", "NONE", "SH", 1_000, 100,
                        None, "EXITED", -100, -1.0, -1_000, 1,
                    ),
                    (
                        manager, 202602, "438516205", "HONEYWELL TECHNOLOGIES",
                        "COM", "COMMON_STOCK", "NONE", "SH", 900, 50,
                        0.1, "NEW", 50, None, 900, 1,
                    ),
                ]
            )
        connection.executemany(
            """
            INSERT INTO DAILY_CIK_HOLDING (
                MANAGER_CIK, QUARTER_ID, CUSIP, ISSUER, TITLE_OF_CLASS,
                SECURITY_TYPE, OPTION_TYPE, AMOUNT_TYPE, MARKET_VALUE_USD,
                REPORTED_AMOUNT, PORTFOLIO_WEIGHT, ACTION, AMOUNT_CHANGE,
                AMOUNT_CHANGE_PERCENT, VALUE_CHANGE_USD, IS_COMPARABLE
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.assertSetEqual(
            build_daily_cik.suppress_probable_identifier_transitions(
                connection, 202602
            ),
            {"438516106", "438516205"},
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_HOLDING "
                "WHERE QUARTER_ID = 202602 AND IS_COMPARABLE = 0"
            ).fetchone()[0],
            50,
        )
        build_daily_cik.rebuild_market_materializations(
            connection, 202602, "now"
        )
        build_daily_cik.rebuild_market_materializations(
            connection, 202602, "later", {"84615Q103"}
        )
        self.assertEqual(
            connection.execute(
                "SELECT NEW_INVESTOR_COUNT, EXITED_INVESTOR_COUNT, "
                "NET_VALUE_CHANGE_USD FROM DAILY_CUSIP_QUARTER_ACTIVITY "
                "WHERE CUSIP = '438516106'"
            ).fetchone(),
            (0, 0, 0),
        )
        self.assertEqual(
            connection.execute(
                "SELECT MANAGER_COUNT, TOTAL_VALUE_USD "
                "FROM DAILY_CUSIP_QUARTER_SUMMARY "
                "WHERE CUSIP = '438516205'"
            ).fetchone(),
            (25, 22_500),
        )
        self.assertEqual(
            connection.execute(
                queries.DAILY_SECURITY_ACTIVITY,
                ("438516106", 202602),
            ).fetchall(),
            [("UNKNOWN", 25, 0)],
        )
        explorer_rows = connection.execute(
            queries.DAILY_ACTIVITY_EXPLORER,
            (202602, "UNKNOWN", *("",) * 10, 100, 0),
        ).fetchall()
        self.assertEqual(len(explorer_rows), 50)
        self.assertTrue(
            all(row[7] == "UNKNOWN" and row[10] == 0 and row[11] == 0
                for row in explorer_rows)
        )
        comparison_rows = connection.execute(
            queries.DAILY_COMPARE_INSTITUTION_MOVERS,
            ("0000000001", 202601, "0000000001", 202602,
             "0000000001", 202602, "", "", 25),
        ).fetchall()
        self.assertEqual(comparison_rows[0][5], "UNKNOWN")
        self.assertEqual(comparison_rows[0][8], 0)
        self.assertEqual(comparison_rows[0][11], 0)
        connection.close()

    def test_daily_security_search_prefers_recognized_type(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executemany(
            """
            INSERT INTO DAILY_CIK_HOLDING (
                MANAGER_CIK, QUARTER_ID, CUSIP, ISSUER, TITLE_OF_CLASS,
                SECURITY_TYPE, OPTION_TYPE, AMOUNT_TYPE, MARKET_VALUE_USD,
                REPORTED_AMOUNT, PORTFOLIO_WEIGHT, ACTION, AMOUNT_CHANGE,
                AMOUNT_CHANGE_PERCENT, VALUE_CHANGE_USD, IS_COMPARABLE
            ) VALUES (?, 202602, ?, ?, ?, ?, 'NONE',
                'SH', ?, ?, 0.5, 'NEW', ?, NULL, ?, 1)
            """,
            [
                (
                    '0000000001', '84615Q103', 'SpaceX', 'cs',
                    'COMMON_STOCK', 1_000, 10, 10, 1_000,
                ),
                (
                    '0000000002', '84615Q103', 'SpaceX', 'Class A',
                    'UNKNOWN', 500, 5, 5, 500,
                ),
                (
                    '0000000001', '000000001', 'Other Issuer', 'COM',
                    'COMMON_STOCK', 100, 1, 1, 100,
                ),
                (
                    '0000000001', '111111111', 'Conflict Issuer', 'COM',
                    'COMMON_STOCK', 100, 1, 1, 100,
                ),
                (
                    '0000000002', '111111111', 'Conflict Issuer', 'ETF',
                    'ETF', 100, 1, 1, 100,
                ),
            ],
        )
        build_daily_cik.rebuild_market_materializations(
            connection, 202602, "now"
        )
        self.assertEqual(
            connection.execute(
                "SELECT SECURITY_TYPE FROM DAILY_CUSIP_QUARTER_SUMMARY "
                "WHERE CUSIP = '84615Q103' AND QUARTER_ID = 202602"
            ).fetchone(),
            ("COMMON_STOCK",),
        )
        self.assertEqual(
            connection.execute(
                "SELECT SECURITY_TYPE FROM DAILY_CUSIP_QUARTER_SUMMARY "
                "WHERE CUSIP = '111111111' AND QUARTER_ID = 202602"
            ).fetchone(),
            ("UNKNOWN",),
        )

        def search_parameters(term: str) -> tuple[str, ...]:
            return (*tuple(f"%{term}%" for _ in range(7)),
                    term, term, f"{term}%", f"{term}%")

        self.assertEqual(
            connection.execute(
                queries.GLOBAL_SEARCH, search_parameters("SpaceX")
            ).fetchone(),
            ("security", "84615Q103", "SpaceX", "84615Q103 · cs"),
        )
        self.assertEqual(
            connection.execute(
                queries.GLOBAL_SEARCH, search_parameters("84615Q103")
            ).fetchall(),
            [("security", "84615Q103", "SpaceX", "84615Q103 · cs")],
        )
        connection.close()

    def test_completed_materialization_suppresses_identifier_transition(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.create_function(
            "ISSUER_KEY", 1, build_instruments.issuer_comparison_key,
            deterministic=True,
        )
        build_instruments.seed_reference_data(connection)
        connection.executemany(
            "INSERT INTO CUSIP (CUSIP_ID, CUSIP) VALUES (?, ?)",
            [(1, "438516106"), (2, "438516205")],
        )
        connection.executemany(
            """
            INSERT INTO CUSIP_VARIANT (
                CUSIP_VARIANT_ID, CUSIP_ID, REPORTCALENDARORQUARTER,
                NAMEOFISSUER, TITLEOFCLASS, OCCURRENCE_COUNT
            ) VALUES (?, ?, '2026-06-30', ?, 'COM', 1)
            """,
            [
                (1, 1, "HONEYWELL INTL INC"),
                (2, 2, "HONEYWELL TECHNOLOGIES"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO INSTRUMENT (
                INSTRUMENT_ID, CUSIP_ID, SECURITY_TYPE_ID, OPTION_TYPE,
                AMOUNT_TYPE, CLASSIFICATION_METHOD
            ) VALUES (?, ?, 1, 'NONE', 'SH', 'RULE_VOTE')
            """,
            [(1, 1), (2, 2)],
        )
        relationships = []
        changes = []
        for number in range(1, 26):
            manager = f"{number:010d}"
            old_id = number * 2 - 1
            new_id = number * 2
            relationships.extend(
                [
                    (old_id, manager, 1, 202601, 202601),
                    (new_id, manager, 2, 202602, 202602),
                ]
            )
            changes.extend(
                [
                    (old_id, 202601, 202602, 1000, None, -1000,
                     100, None, -100, -1.0, "EXITED", 1, None, "OK"),
                    (new_id, 202601, 202602, None, 900, 900,
                     None, 50, 50, None, "NEW", 1, None, "OK"),
                ]
            )
        connection.executemany(
            """
            INSERT INTO CIK_INSTRUMENT (
                CIK_INSTRUMENT_ID, MANAGER_CIK, INSTRUMENT_ID,
                FIRST_OBSERVED_QUARTER_ID, LATEST_OBSERVED_QUARTER_ID
            ) VALUES (?, ?, ?, ?, ?)
            """,
            relationships,
        )
        connection.execute(
            """
            CREATE TEMP TABLE CHANGE_STAGE (
                CIK_INSTRUMENT_ID, FROM_QUARTER_ID, TO_QUARTER_ID,
                PRIOR_VALUE_USD, CURRENT_VALUE_USD, VALUE_CHANGE_USD,
                PRIOR_REPORTED_AMOUNT, CURRENT_REPORTED_AMOUNT,
                AMOUNT_CHANGE, AMOUNT_CHANGE_PERCENT, ACTION,
                IS_COMPARABLE, NONCOMPARABLE_REASON, VALUE_QUALITY_STATUS
            )
            """
        )
        connection.executemany(
            "INSERT INTO CHANGE_STAGE VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            changes,
        )
        self.assertEqual(
            build_instruments.suppress_probable_identifier_transitions(
                connection
            ),
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM CHANGE_STAGE "
                "WHERE ACTION = 'UNKNOWN' AND IS_COMPARABLE = 0 "
                "AND NONCOMPARABLE_REASON = 'POSSIBLE_IDENTIFIER_CHANGE'"
            ).fetchone()[0],
            50,
        )
        build_instruments.sync_changes(connection)
        build_instruments.sync_api_activity_summaries(connection)
        self.assertEqual(
            connection.execute(
                """
                SELECT NEW_INVESTOR_COUNT, EXITED_INVESTOR_COUNT,
                       NET_VALUE_CHANGE_USD
                FROM CUSIP_QUARTER_ACTIVITY
                WHERE CUSIP_ID = 1 AND QUARTER_ID = 202602
                """
            ).fetchone(),
            (0, 0, 0),
        )
        activity_rows = connection.execute(
            queries.ACTIVITY_EXPLORER,
            (202602, "UNKNOWN", "UNKNOWN", *("",) * 10, 100, 0),
        ).fetchall()
        self.assertEqual(len(activity_rows), 50)
        self.assertTrue(
            all(row[6] == "UNKNOWN" and row[9] == 0 and row[12] == 0
                for row in activity_rows)
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
