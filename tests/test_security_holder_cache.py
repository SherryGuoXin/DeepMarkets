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
                "123456789", 202602, "", "", "value", 1, 25, False
            )
            second = main.cached_security_holder_rows(
                "123456789", 202602, "", "", "value", 1, 25, False
            )

        self.assertEqual(first, second)
        self.assertEqual(query.call_count, 1)


if __name__ == "__main__":
    unittest.main()
