from __future__ import annotations

import copy
import html
import unittest

from app.backend.page_summary import institution_page_summary, security_page_summary
from app.backend.seo import SeoPage, render_index


class PageSummaryTests(unittest.TestCase):
    def security(self) -> dict:
        return {
            "identity": {"issuer": "Example & Co"},
            "snapshot": {"quarter_label": "2026Q2"},
            "instrument_breakdown": [{"option_type": "NONE", "institution_count": 17, "value_usd": 1234567}],
            "activity": [{"action": "NEW", "institution_count": 2}],
            "history": [],
            "previous_reporting_period": "2026Q1",
            "site_latest_filing_date": "2026-09-08",
            "is_latest_reporting_period": True,
            "share_comparison": {"total_share_change": 30},
        }

    def test_arbitrary_security_and_daily_only_prior_use_approved_template(self) -> None:
        result = security_page_summary("111111111", self.security())
        self.assertIn("Example & Co (111111111)", result["summary"])
        self.assertIn("Compared with Q1 2026", result["summary"])
        self.assertIn("+30 shares", result["summary"])
        self.assertIn("filed through September 8, 2026", result["summary"])
        self.assertFalse(result["links"])
        self.assertIsNone(result["data_note"])
        self.assertIsNone(result["status_note"])

    def test_historical_and_missing_previous_periods_are_not_mislabeled(self) -> None:
        profile = self.security()
        profile["previous_reporting_period"] = None
        profile["is_latest_reporting_period"] = False
        profile["history"] = [{"quarter_label": "2026Q1"}]
        text = security_page_summary("111111111", profile)["summary"]
        self.assertTrue(text.startswith("For the Q2 2026"))
        self.assertNotIn("Compared with", text)
        self.assertNotIn("share count changed", text)

    def test_option_only_counts_do_not_become_non_option_holdings(self) -> None:
        profile = self.security()
        profile["instrument_breakdown"] = [{"option_type": "CALL", "institution_count": 17, "value_usd": 1234567}]
        profile["activity"] = []
        profile["share_comparison"] = None
        text = security_page_summary("111111111", profile)["summary"]
        self.assertIn("0 institutional investment managers", text)
        self.assertIn("approximately $0", text)
        self.assertNotIn("share count changed", text)

    def test_arbitrary_institution_omits_unavailable_people_and_highlights(self) -> None:
        profile = {
            "identity": {"institution_name": "Example Manager"},
            "snapshot": {"quarter_label": "2026Q2"},
            "non_option_summary": {"holding_count": 3, "portfolio_value": 5000, "activity": []},
            "notable_people": [],
        }
        result = institution_page_summary("0000000001", profile)
        self.assertIn("(CIK 0000000001) reported 3 non-option positions", result["summary"])
        self.assertNotIn("Notable people", result["summary"])
        self.assertNotIn("largest", result["summary"])
        self.assertEqual(len(result["paragraphs"]), 1)
        with_person = copy.deepcopy(profile)
        with_person["notable_people"] = [{"name": "Example Person"}]
        result = institution_page_summary("0000000001", with_person)
        self.assertEqual(result["paragraphs"][-1], "Notable people associated with Example Manager include Example Person.")

    def test_initial_html_escapes_names_and_keeps_visible_summary(self) -> None:
        profile = self.security()
        profile["identity"]["issuer"] = '<script>alert("name")</script>'
        result = security_page_summary("111111111", profile)
        page = SeoPage(result["title"], result["description"], "/securities/111111111", page_summary=result)
        template = '<html><head><!-- ROUTE_SEO_START --><!-- ROUTE_SEO_END --></head><body><div id="root"></div></body></html>'
        rendered = render_index(template, page)
        body = rendered.split('<div id="root">')[1]
        for paragraph in result["paragraphs"]:
            self.assertIn(html.escape(paragraph), body)
        self.assertNotIn('<script>alert("name")</script>', rendered)
        self.assertNotIn("<a ", body)
        self.assertEqual(body.count("<h1>"), 1)


if __name__ == "__main__":
    unittest.main()
