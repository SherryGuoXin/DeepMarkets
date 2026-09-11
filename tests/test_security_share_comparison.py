from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from app.backend import main, queries


class SecurityShareComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE QUARTER (QUARTER_ID INTEGER PRIMARY KEY, PREVIOUS_QUARTER_ID INTEGER);
            INSERT INTO QUARTER VALUES (202504, 202503), (202601, 202504), (202602, 202601);
            CREATE TABLE CIK (CIK TEXT PRIMARY KEY, MANAGER_NAME TEXT, SEC_COMPANY_NAME TEXT);
            CREATE TABLE DAILY_CIK_HOLDING (
                MANAGER_CIK TEXT, QUARTER_ID INTEGER, CUSIP TEXT,
                OPTION_TYPE TEXT, AMOUNT_TYPE TEXT, ACTION TEXT,
                REPORTED_AMOUNT INTEGER, AMOUNT_CHANGE INTEGER,
                MARKET_VALUE_USD INTEGER DEFAULT 100,
                PORTFOLIO_WEIGHT REAL DEFAULT 0.1,
                VALUE_CHANGE_USD INTEGER DEFAULT 0,
                IS_COMPARABLE INTEGER DEFAULT 1
            );
            CREATE INDEX DAILY_CIK_HOLDING_CUSIP_QUARTER_IDX
                ON DAILY_CIK_HOLDING (CUSIP, QUARTER_ID, MARKET_VALUE_USD DESC);
            CREATE TABLE CUSIP (CUSIP_ID INTEGER PRIMARY KEY, CUSIP TEXT);
            INSERT INTO CUSIP VALUES (1, '67066G104');
            CREATE TABLE INSTRUMENT (
                INSTRUMENT_ID INTEGER PRIMARY KEY, CUSIP_ID INTEGER,
                OPTION_TYPE TEXT, AMOUNT_TYPE TEXT
            );
            CREATE INDEX INSTRUMENT_CUSIP_IDX ON INSTRUMENT (CUSIP_ID);
            CREATE TABLE CIK_INSTRUMENT (
                CIK_INSTRUMENT_ID INTEGER PRIMARY KEY, INSTRUMENT_ID INTEGER,
                MANAGER_CIK TEXT
            );
            CREATE TABLE CIK_INSTRUMENT_QUARTER (
                CIK_INSTRUMENT_ID INTEGER, QUARTER_ID INTEGER,
                AMOUNT_TYPE TEXT, REPORTED_AMOUNT INTEGER,
                UNIQUE (CIK_INSTRUMENT_ID, QUARTER_ID)
            );
            CREATE TABLE CIK_INSTRUMENT_CHANGE (
                CIK_INSTRUMENT_ID INTEGER, TO_QUARTER_ID INTEGER, ACTION TEXT,
                AMOUNT_CHANGE INTEGER, IS_COMPARABLE INTEGER
            );
            CREATE INDEX CIK_INSTRUMENT_CHANGE_REL_TO_ACTION_IDX
                ON CIK_INSTRUMENT_CHANGE (CIK_INSTRUMENT_ID, TO_QUARTER_ID, ACTION);
            CREATE INDEX CIK_INSTRUMENT_INSTRUMENT_MANAGER_IDX
                ON CIK_INSTRUMENT (INSTRUMENT_ID, CIK_INSTRUMENT_ID);
            CREATE TABLE CUSIP_INSTRUMENT_QUARTER_SUMMARY (
                CUSIP_ID INTEGER, QUARTER_ID INTEGER, OPTION_TYPE TEXT,
                REPORTED_SHARE_AMOUNT INTEGER, REPORTED_AMOUNT INTEGER
            );
        """)
        self.rows_patch = patch.object(main, "rows", side_effect=self.query_rows)
        self.row_patch = patch.object(main, "row", side_effect=self.query_row)
        self.rows_patch.start()
        self.row_patch.start()

    def tearDown(self) -> None:
        self.rows_patch.stop()
        self.row_patch.stop()
        self.connection.close()

    def query_rows(self, sql: str, parameters: tuple = ()) -> list[dict]:
        return [dict(item) for item in self.connection.execute(sql, parameters)]

    def query_row(self, sql: str, parameters: tuple = ()) -> dict | None:
        results = self.query_rows(sql, parameters)
        return results[0] if results else None

    def position(
        self, manager: str, quarter: int, amount: int, change: int = 0,
        *, action: str = "UNCHANGED", amount_type: str = "SH",
        option: str = "NONE", comparable: int = 1, cusip: str = "67066G104",
    ) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO CIK VALUES (?, ?, NULL)",
            (manager, f"Manager {manager}"),
        )
        self.connection.execute(
            "INSERT INTO DAILY_CIK_HOLDING (MANAGER_CIK, QUARTER_ID, CUSIP, "
            "OPTION_TYPE, AMOUNT_TYPE, ACTION, REPORTED_AMOUNT, AMOUNT_CHANGE, IS_COMPARABLE) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (manager, quarter, cusip, option, amount_type, action, amount, change, comparable),
        )

    def test_share_units_and_comparable_new_and_exited_movers(self) -> None:
        self.position("A", 202601, 100)
        self.position("B", 202601, 20)
        self.position("C", 202601, 300)
        self.position("A", 202602, 130, 30, action="ADDED")
        self.position("B", 202602, 20, -20, action="EXITED")
        self.position("C", 202602, 290, -10, action="REDUCED")
        self.position("N", 202602, 60, 60, action="NEW")
        self.position("P", 202601, 500, amount_type="PRN")
        self.position("P", 202602, 900, 400, action="ADDED", amount_type="PRN")
        self.position("O", 202602, 10000, 10000, action="NEW", option="CALL")
        self.position("U", 202602, 10000, 10000, action="UNKNOWN")
        self.position("I", 202602, 7, 99999, action="ADDED", comparable=0)
        self.position("X", 202602, 100000, 100000, action="NEW", cusip="OTHER")

        result = main.security_share_comparison("67066G104", 202602, True)
        self.assertEqual(result["current_shares"], 487)
        self.assertEqual(result["prior_shares"], 420)
        self.assertEqual(result["total_share_change"], 67)
        self.assertEqual(result["largest_increase"], {
            "cik": "N", "institution_name": "Manager N", "share_change": 60,
        })
        self.assertEqual(result["largest_decrease"], {
            "cik": "B", "institution_name": "Manager B", "share_change": -20,
        })

    def test_principal_only_security_has_no_share_comparison(self) -> None:
        self.position("P", 202601, 500, amount_type="PRN")
        self.position("P", 202602, 900, 400, action="ADDED", amount_type="PRN")
        self.assertIsNone(main.security_share_comparison("67066G104", 202602, True))

    def test_canonical_fallback_sums_actual_share_units(self) -> None:
        self.connection.executescript("""
            INSERT INTO INSTRUMENT VALUES (1, 1, 'NONE', 'SH'), (2, 1, 'CALL', 'SH');
            INSERT INTO CIK_INSTRUMENT VALUES (1, 1, 'A'), (2, 1, 'B'), (3, 2, 'C');
            INSERT INTO CIK_INSTRUMENT_QUARTER VALUES
                (1, 202601, 'SH', 100), (1, 202602, 'SH', 125),
                (2, 202601, 'PRN', 700), (2, 202602, 'PRN', 800),
                (3, 202601, 'SH', 999), (3, 202602, 'SH', 9999);
        """)
        with patch.object(main, "rows", return_value=[]):
            result = main.security_share_comparison("67066G104", 202602, False)
        self.assertEqual(result["current_shares"], 125)
        self.assertEqual(result["prior_shares"], 100)
        self.assertEqual(result["total_share_change"], 25)

    def test_canonical_movers_use_typed_comparable_share_changes(self) -> None:
        self.connection.executescript("""
            INSERT INTO CIK VALUES ('A', 'Manager A', NULL), ('B', 'Manager B', NULL);
            INSERT INTO INSTRUMENT VALUES
                (1, 1, 'NONE', 'SH'), (2, 1, 'NONE', 'PRN'),
                (3, 1, 'CALL', 'SH');
            INSERT INTO CIK_INSTRUMENT VALUES
                (1, 1, 'A'), (2, 2, 'A'), (3, 3, 'A'), (4, 1, 'B');
            INSERT INTO CIK_INSTRUMENT_CHANGE VALUES
                (1, 202602, 'ADDED', 40, 1),
                (2, 202602, 'ADDED', 900, 1),
                (3, 202602, 'ADDED', 5000, 1),
                (4, 202602, 'UNKNOWN', 100, 0);
        """)
        movers = self.query_rows(
            queries.SECURITY_SHARE_MOVERS.format(comparison=">", direction="DESC"),
            (202602, "67066G104"),
        )
        self.assertEqual(movers, [{
            "cik": "A", "institution_name": "Manager A", "share_change": 40,
        }])

    def test_tied_movers_are_omitted_independently(self) -> None:
        self.position("A", 202601, 100)
        self.position("A", 202602, 150, 50, action="ADDED")
        self.position("B", 202602, 50, 50, action="NEW")
        self.position("C", 202602, 10, -10, action="REDUCED")
        result = main.security_share_comparison("67066G104", 202602, True)
        self.assertIsNone(result["largest_increase"])
        self.assertEqual(result["largest_decrease"]["cik"], "C")

    def test_all_unknown_managers_and_absent_direction_are_not_movers(self) -> None:
        self.position("A", 202601, 100)
        self.position("A", 202602, 100)
        self.position("U", 202602, 100, 500, action="ADDED")
        self.position("U", 202602, 1, action="UNKNOWN", amount_type="PRN")
        result = main.security_share_comparison("67066G104", 202602, True)
        self.assertIsNone(result["largest_increase"])
        self.assertIsNone(result["largest_decrease"])

    def test_missing_immediate_prior_does_not_use_older_or_canonical_data(self) -> None:
        self.position("A", 202504, 100)
        self.position("A", 202602, 200, 100, action="ADDED")
        self.connection.execute(
            "INSERT INTO CUSIP_INSTRUMENT_QUARTER_SUMMARY VALUES (1, 202601, 'NONE', 150, 150)"
        )
        self.assertIsNone(main.security_share_comparison("67066G104", 202602, True))

    def test_year_boundary_uses_previous_quarter_relation(self) -> None:
        self.position("A", 202504, 200)
        self.position("A", 202601, 150, -50, action="REDUCED")
        result = main.security_share_comparison("67066G104", 202601, True)
        self.assertEqual(result["total_share_change"], -50)

    def test_canonical_totals_use_share_column_and_preserve_missing_data(self) -> None:
        self.connection.executemany(
            "INSERT INTO CUSIP_INSTRUMENT_QUARTER_SUMMARY VALUES (1, ?, 'NONE', ?, ?)",
            ((202601, 100, 5000), (202602, 120, 10000)),
        )
        result = self.query_row(queries.SECURITY_SHARE_TOTALS, ("67066G104", 202602))
        self.assertEqual(result, {"prior_quarter_id": 202601, "current_shares": 120, "prior_shares": 100})
        self.connection.execute(
            "UPDATE CUSIP_INSTRUMENT_QUARTER_SUMMARY SET REPORTED_SHARE_AMOUNT = NULL WHERE QUARTER_ID = 202601"
        )
        self.assertIsNone(main.security_share_comparison("67066G104", 202602, False))


if __name__ == "__main__":
    unittest.main()
