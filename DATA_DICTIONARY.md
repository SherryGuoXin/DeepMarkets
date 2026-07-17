# 13F enrichment tables: data dictionary and lineage

This document describes the four enrichment tables in `form13f.sqlite3`:

- `CIK`
- `CIK_TICKER_EXCHANGE`
- `CUSIP`
- `CUSIP_VARIANT`

It documents the source of every field, how conflicting source values are
handled, and which transformations are applied. The database currently
contains the SEC 2013 Q2 and March–May 2026 Form 13F data sets.

## Source data

### Form 13F data

The base tables come from the SEC quarterly Form 13F TSV files in `raw_date/`
and `raw_date/2013Q2/`. Their original schema is documented in:

- [`raw_date/FORM13F_metadata.json`](raw_date/FORM13F_metadata.json)
- [`raw_date/FORM13F_readme.htm`](raw_date/FORM13F_readme.htm)

The enrichment tables use these original tables:

| Table | Relevant fields |
|---|---|
| `SUBMISSION` | `ACCESSION_NUMBER`, `CIK`, `FILING_DATE`, `PERIODOFREPORT` |
| `COVERPAGE` | Manager name, address, regulatory identifiers, report type |
| `OTHERMANAGER` | Other-manager CIK, name, and regulatory identifiers |
| `OTHERMANAGER2` | Included-manager CIK, name, and regulatory identifiers |
| `INFOTABLE` | CUSIP, issuer name, security class, FIGI, and holding data |

The SEC describes the Form 13F data as “as filed.” Spelling differences,
historical names, inconsistent capitalization, amendments, and filer errors
are therefore retained in the base tables.

### SEC ticker/exchange data

Ticker data comes from:

- SEC URL: <https://www.sec.gov/files/company_tickers_exchange.json>
- Local snapshot: [`raw_date/company_tickers_exchange.json`](raw_date/company_tickers_exchange.json)

The JSON has four fields: `cik`, `name`, `ticker`, and `exchange`. The local
snapshot contains 10,428 listing rows representing 8,021 unique CIKs.

## `CIK`

### Purpose and grain

`CIK` is a manager/company dimension with exactly one row per normalized CIK.
Its primary key is `CIK`.

The CIK population is the union of:

- SEC ticker/exchange JSON CIKs;
- filing-manager CIKs from `SUBMISSION`;
- reporting other-manager CIKs from `OTHERMANAGER`; and
- included other-manager CIKs from `OTHERMANAGER2`.

### Fields

| Field | Type | Source and treatment |
|---|---|---|
| `CIK` | `CHAR(10)` | Primary key. Source CIKs are converted to integers and formatted as ten digits. For example, the unpadded 2013 value `1539994` becomes `0001539994`. The original base-table value is not changed. |
| `SEC_COMPANY_NAME` | `VARCHAR2(200)` | `name` from `company_tickers_exchange.json`. When a CIK has multiple listing rows, the first name in SEC JSON order is retained. `NULL` for CIKs absent from that file. |
| `MANAGER_NAME` | `VARCHAR2(150)` | Preferred source is `COVERPAGE.FILINGMANAGER_NAME` from the selected filing-manager record. If unavailable, it comes from the selected `OTHERMANAGER` or `OTHERMANAGER2` record. If no 13F manager name exists, it falls back to `SEC_COMPANY_NAME`. |
| `TICKER` | `TEXT` | Ordered, comma-separated list of every ticker for the CIK in SEC JSON order. A single-listing CIK contains one ticker. Use `CIK_TICKER_EXCHANGE` when ticker/exchange pairing matters. |
| `EXCHANGE` | `TEXT` | Ordered, comma-separated exchange list aligned positionally with `TICKER`. A source `NULL` exchange becomes an empty list position. Use `CIK_TICKER_EXCHANGE` to distinguish a true `NULL` safely. |
| `FILINGMANAGER_STREET1` | `VARCHAR2(40)` | `COVERPAGE.FILINGMANAGER_STREET1` from the selected filing-manager record. |
| `FILINGMANAGER_STREET2` | `VARCHAR2(40)` | `COVERPAGE.FILINGMANAGER_STREET2` from the selected filing-manager record. Source blanks were imported as SQL `NULL`. |
| `FILINGMANAGER_CITY` | `VARCHAR2(30)` | `COVERPAGE.FILINGMANAGER_CITY` from the selected filing-manager record. |
| `FILINGMANAGER_STATEORCOUNTRY` | `CHAR(2)` | `COVERPAGE.FILINGMANAGER_STATEORCOUNTRY` from the selected filing-manager record. Values use the SEC state/country codes described in the 13F readme. |
| `FILINGMANAGER_ZIPCODE` | `VARCHAR2(10)` | `COVERPAGE.FILINGMANAGER_ZIPCODE` from the selected filing-manager record. Stored as text to retain formatting and leading zeros. |
| `FORM13FFILENUMBER` | `VARCHAR2(17)` | Preferred source is the selected `COVERPAGE` row. If that value is `NULL`, the selected `OTHERMANAGER`/`OTHERMANAGER2` value is used. |
| `CRDNUMBER` | `VARCHAR2(9)` | Preferred source is the selected `COVERPAGE` row, with selected other-manager data used only as a fallback. Stored as text to retain leading zeros. |
| `SECFILENUMBER` | `VARCHAR2(17)` | Preferred source is the selected `COVERPAGE` row, with selected other-manager data used only as a fallback. |
| `LATEST_RELATED_ACCESSION_NUMBER` | `VARCHAR2(25)` | A deterministic representative accession. It starts with the greatest accession number for filings made by the CIK, then is compared lexically with the selected latest other-manager accession. See the chronology limitation below. |
| `LATEST_FILING_DATE` | `DATE` | `SUBMISSION.FILING_DATE` associated with the filing-manager record selected by descending accession number. It remains in the SEC `DD-MON-YYYY` representation. `NULL` when the CIK never filed as a filing manager. |
| `LATEST_PERIOD_OF_REPORT` | `DATE` | `SUBMISSION.PERIODOFREPORT` from the same selected filing-manager record. It remains in `DD-MON-YYYY` format. |
| `SUBMISSION_COUNT` | `NUMBER(10)` | Number of `SUBMISSION`/`COVERPAGE` joined rows for the normalized CIK. Amendments are separate submissions and are included. |
| `OTHER_MANAGER_MENTION_COUNT` | `NUMBER(10)` | Total number of appearances for the normalized CIK across `OTHERMANAGER` and `OTHERMANAGER2`. This is an occurrence count, not a distinct-filing count. |

### CIK conflicts and special treatments

1. **CIK padding differs by quarter.** Some 2013 CIKs contain six or seven
   digits, while current data normally uses ten. All dimension and view CIKs
   are zero-padded to ten digits.

2. **CIK identifies two different populations.** The ticker JSON generally
   describes public issuers, while Form 13F `SUBMISSION.CIK` identifies filing
   managers. Only 196 CIKs in the current database have both a ticker listing
   and a 13F relationship. A filing-manager CIK must not be treated as the
   issuer CIK for securities in that manager’s portfolio.

3. **A CIK can have many securities.** The JSON has 10,428 listings for 8,021
   CIKs; 1,468 CIKs have multiple listings. The `CIK` table aggregates them for
   convenient browsing, while `CIK_TICKER_EXCHANGE` preserves every pair.

4. **Manager identity can vary over time.** The filing-manager record with the
   greatest accession number is preferred. Other-manager data is used only
   when filing-manager data is unavailable or a regulatory identifier is
   missing.

5. **“Latest” accession is not a universal chronological key.** Accession
   numbers begin with the filing entity’s CIK. Lexical comparison is reliable
   for ordering submissions made by the same filing CIK in this data, but it is
   not guaranteed to be chronological when comparing an accession in which the
   CIK was the filer with an accession in which it was merely another manager.
   Use filing dates from the original relationship tables for strict chronology.

6. **Counts include amendments.** No attempt is made to replace an original
   submission with its amendment or deduplicate filings economically.

## `CIK_TICKER_EXCHANGE`

### Purpose and grain

This is the normalized child table for SEC listing data. It contains one row
per `(CIK, TICKER)` pair. Its composite primary key is `(CIK, TICKER)`, and
`CIK` is a foreign key to `CIK.CIK`.

### Fields

| Field | Type | Source and treatment |
|---|---|---|
| `CIK` | `CHAR(10)` | JSON `cik`, normalized to ten digits. Foreign key to `CIK`. |
| `SEC_COMPANY_NAME` | `VARCHAR2(200)` | JSON `name` from the same listing row. No manager-name substitution is applied. |
| `TICKER` | `VARCHAR2(32)` | JSON `ticker`, retained exactly as supplied by the SEC. Examples may include hyphens used for share classes or preferred securities. |
| `EXCHANGE` | `VARCHAR2(32)` | JSON `exchange`, retained exactly. Nullable because 197 rows in the downloaded SEC snapshot have no exchange value. |
| `SIC` | `CHAR(4)` | Current SEC Standard Industrial Classification code from the top-level `sic` field in the entity's Submissions API JSON. Nullable when SEC supplies no SIC. |
| `SIC_DESCRIPTION` | `TEXT` | Current SEC industry description from the top-level `sicDescription` field in the same Submissions API response. |
| `SIC_MAJOR_GROUP_DIVISION` | `TEXT` | Broad 1987 SIC division derived from the first two digits (major group) of `SIC`, using the official U.S. SIC division ranges. Nullable when SIC is missing, malformed, or outside a defined division. |
| `SIC_AS_OF_DATE` | `DATE` | Date of the SEC bulk submissions snapshot used to populate the SIC fields, stored as `YYYY-MM-DD`. |
| `SIC_SOURCE` | `TEXT` | Provenance label `SEC_SUBMISSIONS_API`. The authoritative endpoint pattern is `https://data.sec.gov/submissions/CIK##########.json`. |

### Listing conflicts and special treatments

- Multiple tickers for the same CIK are expected and retained.
- The same ticker may occur for different CIKs; uniqueness is enforced only
  within a CIK.
- The source has no duplicate `(CIK, TICKER)` pairs in the current snapshot.
- A missing exchange remains SQL `NULL`; it is not labeled “unknown” or mapped
  to an invented exchange.
- The JSON order is preserved only in the aggregated fields on `CIK`. SQL row
  order in this child table is undefined unless an `ORDER BY` is used.
- SIC is an entity/CIK attribute and is therefore repeated on every ticker row
  belonging to the same CIK. It is stored here for convenient ticker-level
  queries.
- `SIC_MAJOR_GROUP_DIVISION` is derived rather than supplied by the SEC
  Submissions API. It uses the official 1987 SIC divisions: major groups
  01-09 Agriculture, 10-14 Mining, 15-17 Construction, 20-39 Manufacturing,
  40-49 Transportation/Communications/Utilities, 50-51 Wholesale Trade,
  52-59 Retail Trade, 60-67 Finance/Insurance/Real Estate, 70-89 Services,
  and 91-99 Public Administration.
- SIC reflects current SEC metadata and can change. `SIC_AS_OF_DATE` records
  the source snapshot date; this table does not retain historical SIC changes.

## `CUSIP`

### Purpose and grain

`CUSIP` is a stable security-key dimension with one row per nine-character
CUSIP found in `INFOTABLE`. Its primary key is the integer `CUSIP_ID`; the
natural `CUSIP` identifier remains unique and required.

All 38,916 distinct source CUSIPs are exactly nine characters. No CUSIP
padding, case conversion, or check-digit repair is applied.

### Fields

| Field | Type | Source and treatment |
|---|---|---|
| `CUSIP_ID` | `INTEGER` | Surrogate primary key generated by SQLite. Existing IDs are preserved during enrichment refreshes; IDs are assigned only to newly observed CUSIPs. Use this compact key for joins. |
| `CUSIP` | `CHAR(9)` | Natural identifier from `INFOTABLE.CUSIP`. Retained exactly as filed and protected by a `UNIQUE NOT NULL` constraint. |

### CUSIP conflicts and special treatments

The current data has substantial as-filed variation:

- 16,637 CUSIPs have more than one issuer-name spelling;
- 22,522 have more than one reported title of class; and
- 6,550 have more than one non-null FIGI.

These differences can represent spelling/capitalization differences,
historical issuer changes, security-class descriptions, reporting errors, or
other changes. They are not automatically “corrected.”

Issuer name, title of class, FIGI, counts, value, share amount, voting
authority, put/call, and discretion are not stored on the stable `CUSIP`
dimension. They can change with time, describe a particular as-filed
observation, or describe an individual manager position. Identity history is
stored in `CUSIP_VARIANT`; holding details remain available through
`CUSIP_13F_HOLDING`.

In particular, values are not summed across the full database: SEC Form 13F
market value was historically reported in thousands, while filings starting
in 2023 report value rounded to the nearest dollar. A cross-period total would
therefore mix units unless explicitly normalized by the analyst.

## `CUSIP_VARIANT`

### Purpose and grain

This table preserves every distinct as-filed CUSIP identity combination for
each `COVERPAGE.REPORTCALENDARORQUARTER`. Its surrogate primary key is
`CUSIP_VARIANT_ID`, and its logical grain is:

`(CUSIP_ID, REPORTCALENDARORQUARTER, NAMEOFISSUER, TITLEOFCLASS, FIGI)`

It has a foreign key to `CUSIP.CUSIP_ID`. A unique expression index enforces
the logical key and treats `FIGI IS NULL` like an empty FIGI for uniqueness.
The current database contains 561,825 quarter-specific variant rows.

### Fields

| Field | Type | Source and treatment |
|---|---|---|
| `CUSIP_VARIANT_ID` | `INTEGER` | Surrogate primary key generated by SQLite. Existing IDs remain stable across refreshes when the logical variant still exists. |
| `CUSIP_ID` | `INTEGER` | Foreign key to `CUSIP.CUSIP_ID`. The natural CUSIP is resolved from `INFOTABLE.CUSIP`. |
| `REPORTCALENDARORQUARTER` | `DATE` | `COVERPAGE.REPORTCALENDARORQUARTER`, joined from each `INFOTABLE.ACCESSION_NUMBER`. Retained in SEC `DD-MON-YYYY` format. |
| `NAMEOFISSUER` | `VARCHAR2(200)` | A distinct as-filed `INFOTABLE.NAMEOFISSUER` value for the CUSIP. |
| `TITLEOFCLASS` | `VARCHAR2(150)` | A distinct as-filed `INFOTABLE.TITLEOFCLASS` value paired with the issuer name and FIGI. |
| `FIGI` | `VARCHAR2(12)` | The as-filed `INFOTABLE.FIGI` paired with the identity variant. Nullable. |
| `OCCURRENCE_COUNT` | `NUMBER(16)` | Number of `INFOTABLE` rows with this exact identity combination in this report quarter. This is observation metadata used to select a representative current variant; it is not an intrinsic CUSIP property and is refreshed when source data changes. |

Blank TSV fields were converted to SQL `NULL` during the raw import. The
unique index uses `COALESCE(FIGI, '')`, preventing multiple otherwise-identical
variants that differ only because one has a null/empty FIGI representation.

The refresh process uses upserts rather than deleting and recreating the
dimension. Consequently, `CUSIP_ID` and `CUSIP_VARIANT_ID` remain stable for
unchanged logical rows when another quarter is appended. Variants removed by a
refreshed SEC source file are removed from the history table.

## Related views

### `CIK_13F_RELATIONSHIP`

Connects normalized CIKs to every related 13F accession and labels the role as:

- `FILING_MANAGER`;
- `OTHER_MANAGER`; or
- `INCLUDED_OTHER_MANAGER`.

This view is preferable to duplicating all one-to-many relationship rows in
the `CIK` dimension.

### `CUSIP_CURRENT_VARIANT`

Returns exactly one inferred current identity for each `CUSIP_ID`. It exposes:

- `CUSIP_ID`;
- the selected `CUSIP_VARIANT_ID` as `CURRENT_CUSIP_VARIANT_ID`;
- natural `CUSIP`;
- `CURRENT_NAMEOFISSUER`;
- `CURRENT_TITLEOFCLASS`;
- `CURRENT_FIGI`;
- `REPORTCALENDARORQUARTER`; and
- the selected variant's `OCCURRENCE_COUNT`.

The view does not invent a third surrogate key. Its row key is `CUSIP_ID`, and
`CURRENT_CUSIP_VARIANT_ID` points directly to the selected history row.

“Current” is inferred rather than asserted by the SEC. Selection uses the most
recent report quarter, then the greatest occurrence count in that quarter.
Remaining ties are resolved deterministically by issuer name, title of class,
FIGI, and variant ID. This matters because many managers can report different
names or security-class descriptions for the same CUSIP in the same quarter.

### `CUSIP_13F_HOLDING`

Exposes every original `INFOTABLE` holding together with `CUSIP_ID`, the exact
quarter-specific `CUSIP_VARIANT_ID`, normalized filing-manager CIK, manager
name, filing date, submission type, period of report, report type, and Form 13F
file number. It contains 3,910,600 rows in the current database, and every row
currently resolves to both surrogate keys.

The manager name is selected as `CIK.MANAGER_NAME`, falling back to
`COVERPAGE.FILINGMANAGER_NAME` if the CIK dimension does not contain one.

## Rebuilding the enrichment tables

After importing or appending another Form 13F quarter, refresh both dimensions:

```bash
python3 enrich_cik.py
python3 enrich_cusip.py
```

`enrich_cik.py` reloads the local SEC JSON snapshot; download a fresh copy
first if current ticker/exchange information is required. Both scripts populate
their tables transactionally and run SQLite integrity checks before committing.
