# 13fdata.net application

Local read-only web application for the canonical Form 13F analytical database.

## Run

From the project root:

```bash
./app/start.sh
```

The script installs missing local dependencies, builds the React application,
and starts the API and site at <http://127.0.0.1:8000>.

For frontend development with hot reload, run the API in one terminal and Vite
in another:

```bash
source .venv/bin/activate
uvicorn app.backend.main:app --reload

cd app/frontend
npm run dev
```

The Vite development site is available at <http://127.0.0.1:5173> and proxies
`/api` requests to the Python API.

## Database

The backend opens `form13f.sqlite3` in SQLite read-only mode. Override its path
when necessary:

```bash
FORM13F_DATABASE=/absolute/path/to/form13f.sqlite3 ./app/start.sh
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.
Every SQL statement behind the application is defined in
`app/backend/queries.py`.

## Routing and search metadata

React routes are declared in `frontend/src/App.jsx`. In a production build,
FastAPI serves the SPA and resolves route-specific metadata in `backend/seo.py`
before returning HTML. It injects the title, description, robots directive,
canonical URL, Open Graph/Twitter fields, JSON-LD and a crawlable summary into
the built `index.html`; `frontend/src/components/RouteSeo.jsx` maintains the
same fields during client-side navigation.

`backend/sitemaps.py` is the production source of `/sitemap.xml`, the static
page sitemap and paginated institution/security sitemaps. `public/robots.txt`
points crawlers to that dynamic sitemap index. Unknown application routes
return HTTP 404 with `noindex`; query parameters are not included in canonical
URLs. HTML is cacheable for five minutes at the origin and sitemap XML for one
hour, although an upstream CDN rule can override those TTLs.

Entity sitemaps read the reconciled `CIK_QUARTER_SUMMARY` and
`CUSIP_QUARTER_SUMMARY` tables; they do not currently include relationship URLs
or entities present only in preliminary daily materializations. The
`public/sitemap.xml` file is a static development fallback and is shadowed by
the dynamic FastAPI route in production.
