# 13fdata.net API

The FastAPI backend is read-only. It opens the generated SQLite database with
`mode=ro` and exposes the calculations needed by the React application.

All component SQL is centralized in `backend/queries.py`.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Database availability |
| `GET /api/meta/quarters` | Available report-quarter selector |
| `GET /api/overview` | Market-level totals and top entities |
| `GET /api/search?q=` | Global institution/security search |
| `GET /api/institutions` | Institution rankings, search and pagination |
| `GET /api/institutions/{cik}` | Identity, snapshot, activity, allocation and history |
| `GET /api/institutions/{cik}/holdings` | Filterable quarterly holdings |
| `GET /api/securities` | Security rankings, search and pagination |
| `GET /api/securities/{cusip}` | Identity, ownership snapshot, activity and history |
| `GET /api/securities/{cusip}/holders` | Filterable institution holder table |
| `GET /api/relationships/{cik}/{cusip}` | Relationship snapshot, lifetime statistics and history |

Interactive request and response documentation is served at `/docs`.

Institution and security directory endpoints support server-side column
sorting with `sort_by` and `direction`. Their Filters panels send numeric range
constraints before pagination; dollar inputs are expressed in millions and
weight inputs are percentages. Security lists also support an exact controlled
security-type filter.

## Calculation rules

- Current positions use `CIK_INSTRUMENT_QUARTER`.
- Manager and security totals use `CIK_QUARTER_SUMMARY` and
  `CUSIP_QUARTER_SUMMARY`.
- `NEW`, `ADDED`, `REDUCED`, `EXITED`, and `UNCHANGED` use
  `CIK_INSTRUMENT_CHANGE`. Actions are based on reported amount changes.
- Dollar changes are disclosed separately and can move in the opposite
  direction because reported values also reflect market-price movement.
- Missing adjacent manager quarters do not create inferred exits.
- Confidential-omission comparisons remain explicitly non-comparable.
- Turnover is a value-change proxy:
  `0.5 × gross absolute comparable value change / portfolio value`.
- The diversification score displayed by the first application release is
  `1 − top-10 portfolio weight`.
- CUSIP ownership aggregates may include economically overlapping shared
  discretion, consistent with the as-filed SEC reports.

## Deliberately unavailable fields

The current database does not contain an authoritative CUSIP-to-public-company
mapping. Therefore held-security ticker, issuer sector, issuer industry and
market capitalization are returned as unavailable.

`CIK_TICKER_EXCHANGE` and its SIC fields describe SEC filing entities. Joining
those values to held CUSIPs would create false issuer metadata, so the backend
does not do it.
