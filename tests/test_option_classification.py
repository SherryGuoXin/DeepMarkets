from __future__ import annotations

import sqlite3
import unittest

from etl import build_instruments


class OptionOnlyClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(
            """
            CREATE TABLE CUSIP (
                CUSIP_ID INTEGER PRIMARY KEY,
                CUSIP TEXT NOT NULL UNIQUE
            );
            CREATE TABLE CUSIP_VARIANT (
                CUSIP_ID INTEGER NOT NULL,
                NAMEOFISSUER TEXT NOT NULL,
                TITLEOFCLASS TEXT NOT NULL,
                OCCURRENCE_COUNT INTEGER NOT NULL
            );
            CREATE TABLE ANALYTICS_HOLDING_LINE (
                CUSIP_ID INTEGER NOT NULL,
                PUTCALL TEXT
            );
            """
        )
        self.connection.executescript(build_instruments.INSTRUMENT_SCHEMA)
        build_instruments.seed_reference_data(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_option_evidence_overrides_common_stock_title_vote(self) -> None:
        profiles = {
            "CALLONLY1": ("CALL",),
            "PUTONLY01": ("PUT",),
            "MIXEDOPT1": ("CALL", "PUT"),
            "BASEPLUS1": (None, "CALL", "PUT"),
        }
        for cusip_id, (cusip, option_types) in enumerate(
            profiles.items(), start=1
        ):
            self.connection.execute(
                "INSERT INTO CUSIP VALUES (?, ?)", (cusip_id, cusip)
            )
            self.connection.execute(
                "INSERT INTO CUSIP_VARIANT VALUES (?, 'TEST CORP', 'COM', ?)",
                (cusip_id, len(option_types)),
            )
            for option_type in option_types:
                security_type_id = {
                    None: 1,
                    "CALL": 5,
                    "PUT": 6,
                }[option_type]
                self.connection.execute(
                    """
                    INSERT INTO INSTRUMENT (
                        CUSIP_ID, SECURITY_TYPE_ID, OPTION_TYPE, AMOUNT_TYPE,
                        CLASSIFICATION_METHOD, IS_ACTIVE
                    ) VALUES (?, ?, ?, 'SH', 'TEST', 1)
                    """,
                    (
                        cusip_id,
                        security_type_id,
                        option_type or "NONE",
                    ),
                )

        build_instruments.classify_cusips(self.connection)
        actual = dict(
            self.connection.execute(
                """
                SELECT C.CUSIP, T.SECURITY_TYPE_CODE
                FROM CUSIP C
                JOIN CUSIP_CLASSIFICATION CC USING (CUSIP_ID)
                JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
                """
            )
        )
        methods = dict(
            self.connection.execute(
                """
                SELECT C.CUSIP, CC.CLASSIFICATION_METHOD
                FROM CUSIP C JOIN CUSIP_CLASSIFICATION CC USING (CUSIP_ID)
                """
            )
        )

        self.assertEqual(actual["CALLONLY1"], "OPTION_CALL")
        self.assertEqual(actual["PUTONLY01"], "OPTION_PUT")
        self.assertEqual(actual["MIXEDOPT1"], "OPTION")
        self.assertEqual(actual["BASEPLUS1"], "COMMON_STOCK")
        self.assertEqual(methods["CALLONLY1"], "OPTION_ONLY")
        self.assertEqual(methods["PUTONLY01"], "OPTION_ONLY")
        self.assertEqual(methods["MIXEDOPT1"], "OPTION_ONLY")
        self.assertEqual(methods["BASEPLUS1"], "RULE_VOTE")


if __name__ == "__main__":
    unittest.main()
