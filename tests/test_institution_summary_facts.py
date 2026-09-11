from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from app.backend import main


class InstitutionSummaryFactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE DAILY_CIK_HOLDING (
                MANAGER_CIK TEXT, QUARTER_ID INTEGER, CUSIP TEXT, ISSUER TEXT,
                TITLE_OF_CLASS TEXT DEFAULT 'COM', SECURITY_TYPE TEXT DEFAULT 'COMMON_STOCK',
                OPTION_TYPE TEXT, AMOUNT_TYPE TEXT, MARKET_VALUE_USD INTEGER,
                REPORTED_AMOUNT INTEGER DEFAULT 10, PORTFOLIO_WEIGHT REAL DEFAULT 0.1,
                ACTION TEXT, AMOUNT_CHANGE INTEGER DEFAULT 1,
                AMOUNT_CHANGE_PERCENT REAL DEFAULT 1, VALUE_CHANGE_USD INTEGER,
                IS_COMPARABLE INTEGER
            );
            CREATE INDEX DAILY_CIK_HOLDING_MANAGER_QUARTER_IDX
                ON DAILY_CIK_HOLDING (MANAGER_CIK, QUARTER_ID);
            CREATE TABLE CIK_INSTRUMENT (
                CIK_INSTRUMENT_ID INTEGER PRIMARY KEY, INSTRUMENT_ID INTEGER, MANAGER_CIK TEXT
            );
            CREATE INDEX CIK_INSTRUMENT_MANAGER_IDX ON CIK_INSTRUMENT (MANAGER_CIK);
            CREATE TABLE CIK_INSTRUMENT_QUARTER (
                CIK_INSTRUMENT_QUARTER_ID INTEGER PRIMARY KEY, CIK_INSTRUMENT_ID INTEGER,
                QUARTER_ID INTEGER, VALUE_USD INTEGER, REPORTED_AMOUNT INTEGER,
                AMOUNT_TYPE TEXT, PORTFOLIO_WEIGHT REAL
            );
            CREATE TABLE CIK_INSTRUMENT_CHANGE (
                CIK_INSTRUMENT_ID INTEGER, TO_QUARTER_ID INTEGER, PRIOR_VALUE_USD INTEGER,
                PRIOR_REPORTED_AMOUNT INTEGER, ACTION TEXT, AMOUNT_CHANGE INTEGER,
                AMOUNT_CHANGE_PERCENT REAL, VALUE_CHANGE_USD INTEGER, IS_COMPARABLE INTEGER
            );
            CREATE TABLE INSTRUMENT (
                INSTRUMENT_ID INTEGER PRIMARY KEY, CUSIP_ID INTEGER, SECURITY_TYPE_ID INTEGER,
                OPTION_TYPE TEXT, AMOUNT_TYPE TEXT
            );
            CREATE TABLE SECURITY_TYPE (SECURITY_TYPE_ID INTEGER PRIMARY KEY, SECURITY_TYPE_CODE TEXT);
            INSERT INTO SECURITY_TYPE VALUES (1, 'COMMON_STOCK');
            CREATE TABLE CUSIP_CURRENT_VARIANT (
                CUSIP_ID INTEGER PRIMARY KEY, CUSIP TEXT, CURRENT_NAMEOFISSUER TEXT, CURRENT_TITLEOFCLASS TEXT
            );
        """)
        self.row_patch = patch.object(main, "rows", side_effect=self.query_rows)
        self.row_patch.start()
        self.next_id = 1

    def tearDown(self) -> None:
        self.row_patch.stop()
        self.connection.close()

    def query_rows(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(item) for item in self.connection.execute(sql, params)]

    def daily(
        self, cusip: str, value: int, change: int = 0, *, action: str = "UNCHANGED",
        comparable: int = 1, option: str = "NONE", amount_type: str = "SH",
        cik: str = "0001067983", quarter: int = 202602,
    ) -> None:
        self.connection.execute(
            "INSERT INTO DAILY_CIK_HOLDING (MANAGER_CIK, QUARTER_ID, CUSIP, ISSUER, "
            "OPTION_TYPE, AMOUNT_TYPE, MARKET_VALUE_USD, ACTION, VALUE_CHANGE_USD, IS_COMPARABLE) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cik, quarter, cusip, f"Issuer {cusip}", option, amount_type, value, action, change, comparable),
        )

    def canonical(
        self, value: int, change: int = 0, *, current: bool = True,
        action: str = "UNCHANGED", comparable: int = 1, option: str = "NONE",
        has_change: bool = True,
    ) -> str:
        identifier = self.next_id
        self.next_id += 1
        cusip = str(identifier).zfill(9)
        self.connection.execute(
            "INSERT INTO CIK_INSTRUMENT VALUES (?, ?, '0001067983')", (identifier, identifier),
        )
        self.connection.execute(
            "INSERT INTO INSTRUMENT VALUES (?, ?, 1, ?, 'SH')", (identifier, identifier, option),
        )
        self.connection.execute(
            "INSERT INTO CUSIP_CURRENT_VARIANT VALUES (?, ?, ?, 'COM')",
            (identifier, cusip, f"Issuer {cusip}"),
        )
        if current:
            self.connection.execute(
                "INSERT INTO CIK_INSTRUMENT_QUARTER VALUES (?, ?, 202602, ?, 10, 'SH', 0.1)",
                (identifier, identifier, value),
            )
        if has_change:
            self.connection.execute(
                "INSERT INTO CIK_INSTRUMENT_CHANGE VALUES (?, 202602, ?, 10, ?, 1, 1, ?, ?)",
                (identifier, value - change if current else value, action, change, comparable),
            )
        return cusip

    def test_daily_non_option_instrument_universe_and_signed_extremes(self) -> None:
        self.daily("A", 300, 10, action="ADDED")
        self.daily("A", 20, 0, amount_type="PRN")
        self.daily("N", 100, 100, action="NEW")
        self.daily("R", 50, -25, action="REDUCED")
        self.daily("E", 500, -500, action="EXITED")
        self.daily("O", 10000, 10000, action="NEW", option="CALL")
        self.daily("U", 10000, -10000, action="UNKNOWN", comparable=0)
        self.daily("I", 7, 99999, action="ADDED", comparable=0)
        self.daily("Other", 100000, 100000, action="NEW", cik="another manager")
        self.daily("Prior", 100000, 100000, action="NEW", quarter=202601)

        result = main.institution_non_option_summary("0001067983", 202602, True)
        self.assertEqual(result["holding_count"], 5)
        self.assertEqual(result["portfolio_value"], 477)
        self.assertEqual(result["largest_position"], {
            "issuer": "Issuer A", "cusip": "A", "market_value_usd": 300,
        })
        self.assertEqual(result["largest_increase"]["cusip"], "N")
        self.assertEqual(result["largest_increase"]["value_change_usd"], 100)
        self.assertEqual(result["largest_decrease"]["cusip"], "E")
        self.assertEqual(result["largest_decrease"]["value_change_usd"], -500)
        self.assertEqual(
            {item["action"]: item["position_count"] for item in result["activity"]},
            {"ADDED": 1, "NEW": 1, "REDUCED": 1, "EXITED": 1, "UNCHANGED": 1, "UNKNOWN": 2},
        )

    def test_canonical_current_unknown_is_included_but_omission_is_not(self) -> None:
        current_unknown = self.canonical(300, 99999, action="UNKNOWN", comparable=0)
        self.canonical(10000, -10000, current=False, action="UNKNOWN", comparable=0)
        exited = self.canonical(500, -500, current=False, action="EXITED")
        new = self.canonical(100, 100, action="NEW")
        self.canonical(40, has_change=False)
        self.canonical(100000, 100000, action="NEW", option="PUT")

        result = main.institution_non_option_summary("0001067983", 202602, False)
        self.assertEqual(result["holding_count"], 3)
        self.assertEqual(result["portfolio_value"], 440)
        self.assertEqual(result["largest_position"]["cusip"], current_unknown)
        self.assertEqual(result["largest_increase"]["cusip"], new)
        self.assertEqual(result["largest_decrease"]["cusip"], exited)
        self.assertEqual(
            {item["action"]: item["position_count"] for item in result["activity"]},
            {"UNKNOWN": 2, "EXITED": 1, "NEW": 1, "UNCHANGED": 1},
        )

    def test_tied_singular_highlights_are_omitted(self) -> None:
        self.daily("A", 100, 20, action="ADDED")
        self.daily("B", 100, 20, action="ADDED")
        self.daily("C", 50, -50, action="EXITED")
        self.daily("D", 50, -50, action="EXITED")
        result = main.institution_non_option_summary("0001067983", 202602, True)
        for key in ("largest_position", "largest_increase", "largest_decrease"):
            self.assertIsNone(result[key])

    def test_no_comparable_changes_does_not_invent_movers(self) -> None:
        self.daily("A", 100)
        self.daily("U", 1000, 1000, action="ADDED", comparable=0)
        result = main.institution_non_option_summary("0001067983", 202602, True)
        self.assertIsNone(result["largest_increase"])
        self.assertIsNone(result["largest_decrease"])

    def test_profile_extra_facts_are_available_for_all_institutions(self) -> None:
        identity = {"institution_name": "Example", "filing_date": "2026-09-08"}
        with (
            patch.object(main, "row", return_value=identity),
            patch.object(main, "rows", return_value=[]),
            patch.object(main, "require_institution_quarter", return_value=202602),
            patch.object(main, "is_partial_institution_quarter", return_value=True),
            patch.object(main, "institution_page_summary", return_value=None),
            patch.object(main, "institution_non_option_summary", return_value={"holding_count": 3}) as facts,
        ):
            pilot = main.institution_profile("0001067983")
            other = main.institution_profile("0000000001")
        self.assertEqual(facts.call_count, 2)
        facts.assert_any_call("0001067983", 202602, True)
        facts.assert_any_call("0000000001", 202602, True)
        self.assertEqual(pilot["non_option_summary"], {"holding_count": 3})
        self.assertEqual(pilot["site_latest_filing_date"], "2026-09-08")
        self.assertTrue(pilot["is_latest_reporting_period"])
        self.assertEqual(other["non_option_summary"], {"holding_count": 3})
        self.assertEqual(other["site_latest_filing_date"], "2026-09-08")


if __name__ == "__main__":
    unittest.main()
