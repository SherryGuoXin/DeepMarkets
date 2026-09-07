from __future__ import annotations

import unittest
from unittest.mock import patch

from app.backend import main


class SecurityHolderCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        main.cached_security_holder_rows.cache_clear()

    def test_reuses_identical_holder_page_until_restart(self) -> None:
        main.cached_security_holder_rows.cache_clear()
        result = [{"cik": "0000000001", "market_value_usd": 100}]
        with patch.object(main, "rows", return_value=result) as query:
            first = main.cached_security_holder_rows(
                "123456789", 202602, "", "", "value", "desc", 1, 25, False
            )
            second = main.cached_security_holder_rows(
                "123456789", 202602, "", "", "value", "desc", 1, 25, False
            )

        self.assertEqual(first, second)
        self.assertEqual(query.call_count, 1)

    def test_direction_is_applied_and_cached_separately(self) -> None:
        main.cached_security_holder_rows.cache_clear()
        with patch.object(main, "rows", return_value=[]) as query:
            main.cached_security_holder_rows(
                "123456789", 202602, "", "", "value", "desc", 1, 25, False
            )
            main.cached_security_holder_rows(
                "123456789", 202602, "", "", "value", "asc", 1, 25, False
            )

        self.assertEqual(query.call_count, 2)
        self.assertIn("H.MARKET_VALUE_USD DESC", query.call_args_list[0].args[0])
        self.assertIn("H.MARKET_VALUE_USD ASC", query.call_args_list[1].args[0])

    def test_action_filter_codes_are_normalized_and_validated(self) -> None:
        self.assertEqual(main._validate_action("new"), "NEW")
        self.assertEqual(main._validate_action("UNKNOWN"), "UNKNOWN")
        with self.assertRaises(main.HTTPException) as raised:
            main._validate_action("Newly reported")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
