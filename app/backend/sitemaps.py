from __future__ import annotations

import html
import math
from urllib.parse import quote

from .database import rows, scalar
from .seo import SITE_URL


SITEMAP_PAGE_SIZE = 50_000


def sitemap_index() -> str:
    institution_count = int(
        scalar("SELECT COUNT(DISTINCT MANAGER_CIK) FROM CIK_QUARTER_SUMMARY") or 0
    )
    security_count = int(
        scalar("SELECT COUNT(DISTINCT CUSIP_ID) FROM CUSIP_QUARTER_SUMMARY") or 0
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
    entries = "\n".join(
        f"  <sitemap><loc>{html.escape(location)}</loc></sitemap>"
        for location in locations
    )
    return _xml(
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</sitemapindex>"
    )


def static_sitemap() -> str:
    lastmod = scalar("SELECT MAX(QUARTER_END_DATE) FROM QUARTER")
    pages = (
        ("", "weekly", "1.0"),
        ("/institutions", "quarterly", "0.9"),
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


def entity_sitemap(kind: str, page: int) -> str | None:
    if page < 1:
        return None
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    if kind == "institutions":
        data = rows(
            """
            SELECT S.MANAGER_CIK AS identifier,
                   MAX(Q.QUARTER_END_DATE) AS lastmod
            FROM CIK_QUARTER_SUMMARY S
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
            SELECT V.CUSIP AS identifier,
                   MAX(Q.QUARTER_END_DATE) AS lastmod
            FROM CUSIP_QUARTER_SUMMARY S
            JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID)
            JOIN QUARTER Q USING (QUARTER_ID)
            GROUP BY S.CUSIP_ID
            ORDER BY S.CUSIP_ID
            LIMIT ? OFFSET ?
            """,
            (SITEMAP_PAGE_SIZE, offset),
        )
        prefix = "/securities/"
    else:
        return None
    if not data:
        return None
    entries = "\n".join(
        _url_entry(
            f"{SITE_URL}{prefix}{quote(item['identifier'], safe='')}",
            item["lastmod"],
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
