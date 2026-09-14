from __future__ import annotations

import html
import math
from functools import lru_cache
from urllib.parse import quote

from .database import rows, scalar
from .seo import SITE_URL


SITEMAP_PAGE_SIZE = 50_000


def _content_lastmod() -> str | None:
    return scalar("SELECT MAX(FILING_DATE_ISO) FROM LATEST_FILING_FEED")


@lru_cache(maxsize=1)
def sitemap_index() -> str:
    institution_count = int(
        scalar(
            "SELECT COUNT(*) FROM (SELECT MANAGER_CIK FROM CIK_QUARTER_SUMMARY "
            "UNION SELECT MANAGER_CIK FROM DAILY_CIK_QUARTER_SUMMARY)"
        ) or 0
    )
    security_count = int(
        scalar(
            "SELECT COUNT(*) FROM ("
            "SELECT V.CUSIP FROM CUSIP_QUARTER_SUMMARY S "
            "JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID) "
            "WHERE V.CUSIP = UPPER(TRIM(V.CUSIP)) AND CUSIP_IS_VALID(V.CUSIP) "
            "UNION SELECT CUSIP FROM DAILY_CUSIP_QUARTER_SUMMARY "
            "WHERE CUSIP = UPPER(TRIM(CUSIP)) AND CUSIP_IS_VALID(CUSIP))"
        ) or 0
    )
    locations = [f"{SITE_URL}/sitemaps/static.xml"]
    locations.extend(
        f"{SITE_URL}/sitemaps/institutions-{page}.xml"
        for page in range(1, math.ceil(institution_count / SITEMAP_PAGE_SIZE) + 1)
    )
    locations.extend(
        f"{SITE_URL}/sitemaps/securities-{page}.xml"
        for page in range(1, math.ceil(security_count / SITEMAP_PAGE_SIZE) + 1)
    )
    lastmod = _content_lastmod()
    updated = f"<lastmod>{html.escape(lastmod)}</lastmod>" if lastmod else ""
    entries = "\n".join(
        f"  <sitemap><loc>{html.escape(location)}</loc>{updated}</sitemap>"
        for location in locations
    )
    return _xml(
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</sitemapindex>"
    )


@lru_cache(maxsize=1)
def static_sitemap() -> str:
    lastmod = _content_lastmod()
    pages = (
        ("", "weekly", "1.0"),
        ("/institutions", "quarterly", "0.9"),
        ("/latest-filings", "daily", "0.9"),
        ("/securities", "quarterly", "0.9"),
        ("/compare", "quarterly", "0.8"),
        ("/activity", "quarterly", "0.8"),
        ("/disclaimers", "yearly", "0.3"),
    )
    entries = "\n".join(
        _url_entry(f"{SITE_URL}{path}", lastmod, frequency, priority)
        for path, frequency, priority in pages
    )
    return _urlset(entries)


@lru_cache(maxsize=16)
def entity_sitemap(kind: str, page: int) -> str | None:
    if page < 1:
        return None
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    if kind == "institutions":
        data = rows(
            """
            WITH SUMMARY AS (
                SELECT MANAGER_CIK, QUARTER_ID FROM CIK_QUARTER_SUMMARY
                UNION ALL
                SELECT MANAGER_CIK, QUARTER_ID FROM DAILY_CIK_QUARTER_SUMMARY
            )
            SELECT S.MANAGER_CIK AS identifier,
                   MAX(Q.QUARTER_END_DATE) AS lastmod
            FROM SUMMARY S
            JOIN QUARTER Q USING (QUARTER_ID)
            GROUP BY S.MANAGER_CIK
            ORDER BY S.MANAGER_CIK
            LIMIT ? OFFSET ?
            """,
            (SITEMAP_PAGE_SIZE, offset),
        )
        prefix = "/institutions/"
    elif kind == "securities":
        data = rows(
            """
            WITH SUMMARY AS (
                SELECT V.CUSIP, S.QUARTER_ID FROM CUSIP_QUARTER_SUMMARY S
                JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID)
                WHERE V.CUSIP = UPPER(TRIM(V.CUSIP))
                  AND CUSIP_IS_VALID(V.CUSIP)
                UNION ALL
                SELECT CUSIP, QUARTER_ID FROM DAILY_CUSIP_QUARTER_SUMMARY
                WHERE CUSIP = UPPER(TRIM(CUSIP))
                  AND CUSIP_IS_VALID(CUSIP)
            )
            SELECT S.CUSIP AS identifier,
                   MAX(Q.QUARTER_END_DATE) AS lastmod
            FROM SUMMARY S
            JOIN QUARTER Q USING (QUARTER_ID)
            GROUP BY S.CUSIP
            ORDER BY S.CUSIP
            LIMIT ? OFFSET ?
            """,
            (SITEMAP_PAGE_SIZE, offset),
        )
        prefix = "/securities/"
    else:
        return None
    if not data:
        return None
    content_lastmod = _content_lastmod()
    entries = "\n".join(
        _url_entry(
            f"{SITE_URL}{prefix}{quote(item['identifier'], safe='')}",
            max(str(item["lastmod"]), content_lastmod)
            if item["lastmod"] and content_lastmod else item["lastmod"] or content_lastmod,
            "quarterly",
            "0.7",
        )
        for item in data
    )
    return _urlset(entries)


def _url_entry(
    location: str,
    lastmod: str | None,
    change_frequency: str,
    priority: str,
) -> str:
    updated = f"<lastmod>{html.escape(str(lastmod))}</lastmod>" if lastmod else ""
    return (
        f"  <url><loc>{html.escape(location)}</loc>{updated}"
        f"<changefreq>{change_frequency}</changefreq>"
        f"<priority>{priority}</priority></url>"
    )


def _urlset(entries: str) -> str:
    return _xml(
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>"
    )


def _xml(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'
