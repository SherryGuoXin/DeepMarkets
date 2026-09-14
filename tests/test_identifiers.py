from __future__ import annotations

import unittest

from app.backend.identifiers import is_valid_cusip, normalize_cusip
from app.backend.seo import seo_for_path


class CusipIdentifierTests(unittest.TestCase):
    def test_normalization_and_checksum(self) -> None:
        self.assertEqual(normalize_cusip(" 67066g104 "), "67066G104")
        self.assertTrue(is_valid_cusip("67066G104"))
        self.assertTrue(is_valid_cusip("037833100"))

    def test_rejects_placeholders_bad_characters_and_bad_checksums(self) -> None:
        self.assertFalse(is_valid_cusip("0        "))
        self.assertFalse(is_valid_cusip("00000None"))
        self.assertFalse(is_valid_cusip("67066G105"))
        self.assertFalse(is_valid_cusip(""))

    def test_invalid_security_path_is_not_indexable(self) -> None:
        page = seo_for_path("/securities/0%20%20%20%20%20%20%20%20")
        self.assertTrue(page.no_index)
        self.assertEqual(page.title, "Page not found | 13fdata.net")


if __name__ == "__main__":
    unittest.main()
