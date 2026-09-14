from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch
from xml.etree import ElementTree as ET

from app.backend import sitemaps
from app.backend.identifiers import is_valid_cusip


class EntitySitemapTests(unittest.TestCase):
    def test_daily_entities_and_overlaps_have_matching_page_counts(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript("""
                CREATE TABLE QUARTER (QUARTER_ID INTEGER, QUARTER_END_DATE TEXT);
                INSERT INTO QUARTER VALUES (202601,'2026-03-31'),(202602,'2026-06-30');
                CREATE TABLE LATEST_FILING_FEED (FILING_DATE_ISO TEXT);
                INSERT INTO LATEST_FILING_FEED VALUES ('2026-09-09');
                CREATE TABLE CIK_QUARTER_SUMMARY (MANAGER_CIK TEXT, QUARTER_ID INTEGER);
                CREATE TABLE DAILY_CIK_QUARTER_SUMMARY (MANAGER_CIK TEXT, QUARTER_ID INTEGER);
                INSERT INTO CIK_QUARTER_SUMMARY VALUES ('0000000001',202601);
                INSERT INTO DAILY_CIK_QUARTER_SUMMARY VALUES ('0000000001',202602),('0000000002',202602);
                CREATE TABLE CUSIP_CURRENT_VARIANT (CUSIP_ID INTEGER, CUSIP TEXT);
                INSERT INTO CUSIP_CURRENT_VARIANT VALUES (1,'037833100');
                CREATE TABLE CUSIP_QUARTER_SUMMARY (CUSIP_ID INTEGER, QUARTER_ID INTEGER);
                INSERT INTO CUSIP_QUARTER_SUMMARY VALUES (1,202601);
                CREATE TABLE DAILY_CUSIP_QUARTER_SUMMARY (CUSIP TEXT, QUARTER_ID INTEGER);
                INSERT INTO DAILY_CUSIP_QUARTER_SUMMARY VALUES
                    ('037833100',202602),('67066G104',202602),
                    ('67066g104',202602),('0        ',202602),('67066G105',202602);
            """)
            connection.create_function(
                "CUSIP_IS_VALID", 1, lambda value: int(is_valid_cusip(value)),
                deterministic=True,
            )

            def rows(sql, params=()):
                return [dict(row) for row in connection.execute(sql, params)]

            def scalar(sql):
                return connection.execute(sql).fetchone()[0]

            with patch.object(sitemaps, "rows", side_effect=rows), patch.object(sitemaps, "scalar", side_effect=scalar), patch.object(sitemaps, "SITEMAP_PAGE_SIZE", 1):
                sitemaps.sitemap_index.cache_clear()
                sitemaps.static_sitemap.cache_clear()
                sitemaps.entity_sitemap.cache_clear()
                index = sitemaps.sitemap_index()
                self.assertEqual(len(ET.fromstring(index)), 5)
                self.assertIn("institutions-2.xml", index)
                self.assertIn("securities-2.xml", index)
                self.assertIn("/institutions/0000000002", sitemaps.entity_sitemap("institutions", 2))
                self.assertIn("/securities/67066G104", sitemaps.entity_sitemap("securities", 2))
                self.assertNotIn("67066g104", sitemaps.entity_sitemap("securities", 2))
                self.assertIn("2026-09-09", sitemaps.entity_sitemap("securities", 2))
                self.assertIsNone(sitemaps.entity_sitemap("securities", 3))
                self.assertIsNone(sitemaps.entity_sitemap("securities", 0))
                self.assertIsNone(sitemaps.entity_sitemap("unknown", 1))


if __name__ == "__main__":
    unittest.main()
