# SEO handoff — 2026-09-07

## Baseline

- The production application release is `657698f`; the GitHub branch may have a
  later documentation-only handoff commit.
- Production is healthy; the weekday 10:00 PM Toronto update and 7:00 AM retry
  remain enabled. A code release must not run the importer or rebuild the DB.
- The production database is newer than the local database. Do not use local
  row counts or freshness dates as production SEO copy.

## Decisions relevant to copy

- Describe records as SEC-reported, not verified trades, purchases, sales, or
  issuer fundamentals. The application preserves filer anomalies as submitted.
- Quarter-wide daily views update as filings arrive. Use the dated wording
  “Reconciled with all SEC filings published through …; data may be incomplete
  and may be updated by future filings.” Do not use complete/partial badges.
- Securities remain exact-CUSIP records; probable successor identifiers are
  not merged. Calls and puts are separate instrument variants.
- Notable people are curated from SEC Schedule 13D/G evidence. Evidence URLs
  stay internal and pages fall back to the 13F file number.

## Current unfinished work

- SEO review and improvements are intentionally left for the next chat.
- Local data still contains at least one stale pre-repair analytical row that
  is absent from production; code is synchronized, data snapshots are not.
- Reinterpreting SEC rows with zero value or zero quantity is deferred by
  decision and is not an SEO task.

No implementation files are currently being edited. The latest committed UI
work touched `SecurityPage.jsx`, `UI.jsx`, `styles.css`, `backend/main.py`, and
`backend/queries.py`; avoid mixing unrelated changes into those controls.

## Routing and indexing implementation

- Client routes: `app/frontend/src/App.jsx`.
- Server-rendered metadata and canonical resolution: `app/backend/seo.py`.
- Client-navigation metadata mirror: `app/frontend/src/components/RouteSeo.jsx`.
- Dynamic sitemap index and institution/security shards:
  `app/backend/sitemaps.py`; relationship and daily-only entities are currently
  omitted. `app/frontend/public/sitemap.xml` is only a development fallback.
- Crawler source: `app/frontend/public/robots.txt`. Cloudflare may prepend its
  own crawler/content-signal directives in production.
- Canonicals exclude query parameters. Unknown server routes return HTTP 404
  with `noindex`; the React wildcard redirect applies after client startup.
- Server HTML includes title, description, robots, canonical, Open Graph,
  Twitter metadata, crawlable fallback content, and WebPage/Dataset JSON-LD.
  Keep server and client metadata behavior aligned.

## Deployment notes

Commit and push first, run `deploy/build_release.sh`, and use the immutable
release-switch procedure in `deploy/DEPLOYMENT.md`. Stop Nginx during the
symlink switch, health-check the app privately, then restore traffic and the
daily timer. Do not run `deploy/install.sh` for code-only releases. Cloudflare
can retain route HTML beyond the origin's five-minute TTL, so purge route HTML
after SEO changes and verify the public response, canonical, robots, sitemap,
and JSON-LD—not only repository files.
