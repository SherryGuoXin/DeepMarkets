from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch
from xml.etree import ElementTree as ET

from app.backend import sitemaps


class EntitySitemapTests(unittest.TestCase):
    def test_daily_entities_and_overlaps_have_matching_page_counts(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript("""
                CREATE TABLE QUARTER (QUARTER_ID INTEGER, QUARTER_END_DATE TEXT);
                INSERT INTO QUARTER VALUES (202601,'2026-03-31'),(202602,'2026-06-30');
                CREATE TABLE CIK_QUARTER_SUMMARY (MANAGER_CIK TEXT, QUARTER_ID INTEGER);
                CREATE TABLE DAILY_CIK_QUARTER_SUMMARY (MANAGER_CIK TEXT, QUARTER_ID INTEGER);
                INSERT INTO CIK_QUARTER_SUMMARY VALUES ('0000000001',202601);
                INSERT INTO DAILY_CIK_QUARTER_SUMMARY VALUES ('0000000001',202602),('0000000002',202602);
                CREATE TABLE CUSIP_CURRENT_VARIANT (CUSIP_ID INTEGER, CUSIP TEXT);
                INSERT INTO CUSIP_CURRENT_VARIANT VALUES (1,'111111111');
                CREATE TABLE CUSIP_QUARTER_SUMMARY (CUSIP_ID INTEGER, QUARTER_ID INTEGER);
                INSERT INTO CUSIP_QUARTER_SUMMARY VALUES (1,202601);
                CREATE TABLE DAILY_CUSIP_QUARTER_SUMMARY (CUSIP TEXT, QUARTER_ID INTEGER);
                INSERT INTO DAILY_CUSIP_QUARTER_SUMMARY VALUES ('111111111',202602),('222222222',202602);
            """)

            def rows(sql, params=()):
                return [dict(row) for row in connection.execute(sql, params)]

            def scalar(sql):
                return connection.execute(sql).fetchone()[0]

            with patch.object(sitemaps, "rows", side_effect=rows), patch.object(sitemaps, "scalar", side_effect=scalar), patch.object(sitemaps, "SITEMAP_PAGE_SIZE", 1):
                index = sitemaps.sitemap_index()
                self.assertEqual(len(ET.fromstring(index)), 5)
                self.assertIn("institutions-2.xml", index)
                self.assertIn("securities-2.xml", index)
                self.assertIn("/institutions/0000000002", sitemaps.entity_sitemap("institutions", 2))
                self.assertIn("/securities/222222222", sitemaps.entity_sitemap("securities", 2))
                self.assertIsNone(sitemaps.entity_sitemap("securities", 3))
                self.assertIsNone(sitemaps.entity_sitemap("securities", 0))
                self.assertIsNone(sitemaps.entity_sitemap("unknown", 1))


if __name__ == "__main__":
    unittest.main()
