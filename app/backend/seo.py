from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from . import queries
from .database import row


SITE_NAME = "13fdata.net"
SITE_URL = "https://13fdata.net"
SEO_BLOCK = re.compile(
    r"<!-- ROUTE_SEO_START -->.*?<!-- ROUTE_SEO_END -->",
    re.DOTALL,
)
ROOT_ELEMENT = re.compile(r'<div id="root"></div>')


@dataclass(frozen=True)
class SeoPage:
    title: str
    description: str
    canonical_path: str
    keywords: tuple[str, ...] = field(default_factory=tuple)
    no_index: bool = False
    page_type: str = "WebPage"
    entity_name: str | None = None
    page_summary: dict[str, object] | None = None

    @property
    def canonical_url(self) -> str:
        return f"{SITE_URL}{self.canonical_path}"


STATIC_PAGES = {
    "": SeoPage(
        "SEC Form 13F Institutional Holdings & Ownership | 13fdata.net",
        "Explore SEC Form 13F filings, institutional holdings, reported portfolio values, securities ownership and quarter-to-quarter position changes.",
        "",
        ("13F data", "institutional ownership", "SEC filings database"),
    ),
    "institutions": SeoPage(
        "Institutional Investors & SEC 13F Holdings | 13fdata.net",
        "Rank and filter institutional investment managers by SEC Form 13F portfolio value, holdings, buying, selling, new positions and exits.",
        "/institutions",
        ("institution rankings", "13F investment managers", "institution portfolios"),
    ),
    "latest-filings": SeoPage(
        "Latest SEC Form 13F Filings | 13fdata.net",
        "See the most recently filed institutional Form 13F reports, including filing date, report period, reported assets and holding count.",
        "/latest-filings",
        ("latest 13F filings", "recent institutional filings", "SEC 13F updates"),
    ),
    "securities": SeoPage(
        "Securities Held by Institutions in SEC 13F Filings | 13fdata.net",
        "Find securities reported in SEC Form 13F filings and compare institutional value, investors, ownership changes, new positions and exits.",
        "/securities",
        ("CUSIP holdings", "institutional securities", "security ownership"),
    ),
    "compare": SeoPage(
        "Compare SEC Form 13F Holdings by Quarter | 13fdata.net",
        "Compare institutional portfolios and security ownership between SEC Form 13F reporting quarters, including reported value and position changes.",
        "/compare",
        ("13F quarter comparison", "portfolio changes", "ownership history"),
    ),
    "activity": SeoPage(
        "New, Added, Reduced & Exited 13F Positions | 13fdata.net",
        "Explore new, added, reduced and exited positions reported by institutional investment managers in SEC Form 13F filings.",
        "/activity",
        ("new institutional positions", "13F exits", "institutional buying and selling"),
    ),
    "disclaimers": SeoPage(
        "Website Disclaimer | 13fdata.net",
        "Read the 13fdata.net legal disclaimer, SEC Form 13F data limitations, methodology risks, warranty exclusions and terms of informational use.",
        "/disclaimers",
        ("13F data disclaimer", "SEC filing limitations"),
    ),
}


def seo_for_path(full_path: str) -> SeoPage:
    normalized = full_path.strip("/")
    if normalized in STATIC_PAGES:
        return STATIC_PAGES[normalized]

    parts = [unquote(part) for part in normalized.split("/") if part]
    if len(parts) == 2 and parts[0] in {"institutions", "securities"}:
        # Lazy import keeps the API/profile builders independent of routing SEO.
        # Initial HTML and the client consume precisely the same profile summary.
        from fastapi import HTTPException
        from .main import institution_profile, security_profile

        try:
            profile = (institution_profile(parts[1]) if parts[0] == "institutions"
                       else security_profile(parts[1]))
        except HTTPException as error:
            if error.status_code != 404:
                raise
        else:
            summary = profile.get("page_summary")
            if summary:
                return SeoPage(
                    summary["title"], summary["description"],
                    f"/{parts[0]}/{quote(parts[1], safe='')}",
                    entity_name=profile["identity"].get("institution_name")
                    or profile["identity"].get("issuer"),
                    page_summary=summary,
                )

    if len(parts) == 2 and parts[0] == "institutions":
        cik = parts[1]
        identity = row(queries.INSTITUTION_IDENTITY, (cik, cik, cik))
        if identity:
            name = identity["institution_name"]
            path = f"/institutions/{quote(cik, safe='')}"
            return SeoPage(
                f"{name} 13F Holdings & Portfolio | {SITE_NAME}",
                f"Review {name} SEC Form 13F holdings, reported portfolio value, securities and quarterly position changes. CIK {cik}.",
                path,
                (name, f"CIK {cik}", "institutional holdings"),
                entity_name=name,
            )

    if len(parts) == 2 and parts[0] == "securities":
        cusip = parts[1]
        identity = row(queries.SECURITY_IDENTITY, (cusip,)) or row(
            queries.DAILY_SECURITY_IDENTITY, (cusip,)
        )
        if identity:
            issuer = identity["issuer"] or cusip
            security_class = identity["title_of_class"] or "security"
            path = f"/securities/{quote(cusip, safe='')}"
            return SeoPage(
                f"{issuer} Institutional Ownership & 13F Holders | {SITE_NAME}",
                f"Review SEC Form 13F institutional ownership, reported holding value and quarterly holder changes for {issuer} {security_class}, CUSIP {cusip}.",
                path,
                (issuer, f"CUSIP {cusip}", "institutional ownership"),
                entity_name=issuer,
            )

    if len(parts) == 3 and parts[0] == "relationships":
        cik, cusip = parts[1], parts[2]
        identity = row(queries.RELATIONSHIP_IDENTITY, (cik, cusip))
        if identity:
            institution = identity["institution_name"]
            issuer = identity["issuer"]
            path = (
                f"/relationships/{quote(cik, safe='')}/{quote(cusip, safe='')}"
            )
            return SeoPage(
                f"{institution} – {issuer} 13F Holding History | {SITE_NAME}",
                f"Track the SEC Form 13F holding relationship between {institution} and {issuer}, including reported quantity, value and quarterly changes.",
                path,
                (institution, issuer, f"CIK {cik}", f"CUSIP {cusip}"),
                entity_name=f"{institution} – {issuer}",
            )

    canonical_path = f"/{'/'.join(quote(part, safe='') for part in parts)}"
    return SeoPage(
        f"Page not found | {SITE_NAME}",
        "The requested 13fdata.net page could not be found.",
        canonical_path,
        no_index=True,
    )


def render_index(template: str, seo: SeoPage) -> str:
    route_payload = json.dumps(
        {
            "title": seo.title,
            "description": seo.description,
            "canonicalUrl": seo.canonical_url,
            "keywords": list(seo.keywords),
            "noIndex": seo.no_index,
            "pageType": seo.page_type,
            "entityName": seo.entity_name,
            "structuredData": _structured_data(seo),
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    structured_data = json.dumps(_structured_data(seo), ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    title = html.escape(seo.title)
    description = html.escape(seo.description, quote=True)
    keywords = html.escape(
        ", ".join(
            (
                "SEC Form 13F",
                "13F filings",
                "institutional holdings",
                "institutional investors",
                *seo.keywords,
            )
        ),
        quote=True,
    )
    canonical = html.escape(seo.canonical_url, quote=True)
    robots = "noindex, nofollow" if seo.no_index else "index, follow"
    block = f"""<!-- ROUTE_SEO_START -->
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <meta name="keywords" content="{keywords}" />
    <meta name="robots" content="{robots}" />
    <link rel="canonical" href="{canonical}" />
    <meta property="og:site_name" content="{SITE_NAME}" />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{description}" />
    <meta property="og:url" content="{canonical}" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="{description}" />
    <script id="server-route-seo" type="application/json">{route_payload}</script>
    <script id="route-seo-schema" type="application/ld+json">{structured_data}</script>
    <!-- ROUTE_SEO_END -->"""
    if not SEO_BLOCK.search(template):
        raise RuntimeError("Frontend index is missing the route SEO markers")
    rendered = SEO_BLOCK.sub(lambda _: block, template, count=1)
    heading = html.escape(seo.entity_name or seo.title.split(" | ", 1)[0])
    summary = (
        '<div id="root"><main class="server-route-summary">'
        f"<h1>{heading}</h1><p>{description}</p>"
        '<nav aria-label="Primary">'
        '<a href="/institutions">Institutions</a> '
        '<a href="/securities">Securities</a> '
        '<a href="/compare">Quarter comparison</a>'
        "</nav></main></div>"
    )
    if seo.page_summary:
        content = seo.page_summary
        links = " ".join(
            f'<a href="{html.escape(link["url"], quote=True)}">'
            f'{html.escape(link["label"])}</a>'
            for link in content["links"]
        )
        notes = "".join(
            f'<p class="server-summary-{key}">{html.escape(content[key])}</p>'
            for key in ("status_note", "context_note", "data_note")
            if content.get(key)
        )
        paragraphs = "".join(
            f'<p>{html.escape(paragraph)}</p>'
            for paragraph in content.get("paragraphs", [content["summary"]])
        )
        related_links = (
            f'<nav aria-label="Related data and sources">{links}</nav>'
            if links else ""
        )
        summary = (
            '<div id="root"><main class="server-route-summary"><article>'
            f'<header><h1>{html.escape(content["heading"])}</h1></header>'
            '<section aria-labelledby="server-summary-heading">'
            f'<h2 id="server-summary-heading">{html.escape(content["section_heading"])}</h2>'
            f'{paragraphs}{notes}{related_links}'
            '</section></article></main></div>'
        )
    if not ROOT_ELEMENT.search(rendered):
        raise RuntimeError("Frontend index is missing the root element")
    return ROOT_ELEMENT.sub(lambda _: summary, rendered, count=1)


def _structured_data(seo: SeoPage) -> dict[str, object]:
    if seo.page_summary:
        return seo.page_summary["structured_data"]
    result: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": seo.page_type,
        "name": seo.title,
        "description": seo.description,
        "url": seo.canonical_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": SITE_URL,
        },
        "about": {
            "@type": "Dataset",
            "name": "SEC Form 13F institutional holdings",
            "description": (
                "Institutional holdings, reported values, quantities and "
                "quarter-over-quarter changes derived from public SEC Form 13F filings."
            ),
            "creator": {
                "@type": "Organization",
                "name": "U.S. Securities and Exchange Commission",
                "url": "https://www.sec.gov/",
            },
        },
    }
    return result
