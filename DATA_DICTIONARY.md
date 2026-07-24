# 13F enrichment tables: data dictionary and lineage

This document describes the enrichment and canonical analytics layers in
`form13f.sqlite3`, including:

- `CIK`
- `CIK_TICKER_EXCHANGE`
- `CUSIP`
- `CUSIP_VARIANT`
- ETL batch provenance
- normalized filing quarters and dates
- amendment-resolved canonical filings and holdings

It documents the source of every field, how conflicting source values are
handled, and which transformations are applied. The database currently
contains the SEC 2013 Q2, 2013 Q3, and March–May 2026 Form 13F data sets.

## Source data

### Form 13F data

The base tables come from the SEC quarterly Form 13F TSV files in `raw_date/`
and quarter-specific subdirectories. Their original schema is documented in:

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

All 60,038 distinct source CUSIPs are exactly nine characters. No CUSIP
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
The current database contains 885,316 quarter-specific variant rows.

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

Materializes exactly one inferred current identity for each `CUSIP_ID`. It is
refreshed by `etl/enrich_cusip.py` after variant history is updated, so
application queries do not rerank the complete history on every request. It
exposes:

- `CUSIP_ID`;
- the selected `CUSIP_VARIANT_ID` as `CURRENT_CUSIP_VARIANT_ID`;
- natural `CUSIP`;
- `CURRENT_NAMEOFISSUER`;
- `CURRENT_TITLEOFCLASS`;
- `CURRENT_FIGI`;
- `REPORTCALENDARORQUARTER`; and
- the selected variant's `OCCURRENCE_COUNT`.

The table does not invent a third surrogate key. Its primary key is `CUSIP_ID`,
and `CURRENT_CUSIP_VARIANT_ID` points directly to the selected history row.

“Current” is inferred rather than asserted by the SEC. Selection uses the most
recent report quarter, then the greatest occurrence count in that quarter.
Remaining ties are resolved deterministically by issuer name, title of class,
FIGI, and variant ID. This matters because many managers can report different
names or security-class descriptions for the same CUSIP in the same quarter.

### `CUSIP_13F_HOLDING`

Exposes every original `INFOTABLE` holding together with `CUSIP_ID`, the exact
quarter-specific `CUSIP_VARIANT_ID`, normalized filing-manager CIK, manager
name, filing date, submission type, period of report, report type, and Form 13F
file number. It contains 120,182,194 rows in the current database, and every row
currently resolves to both surrogate keys.

The manager name is selected as `CIK.MANAGER_NAME`, falling back to
`COVERPAGE.FILINGMANAGER_NAME` if the CIK dimension does not contain one.

## Rebuilding the enrichment tables

The preferred command extracts, appends, and refreshes both dimensions:

```bash
python3 etl/run_etl.py raw_date/YYYYqN_form13f.zip
```

For manual maintenance after importing or appending another quarter:

```bash
python3 etl/enrich_cik.py
python3 etl/enrich_cusip.py
```

`etl/enrich_cik.py` reloads the local SEC JSON snapshot; download a fresh copy
first if current ticker/exchange information is required. The programs populate
their tables transactionally and run SQLite integrity checks before committing.

## Import provenance and canonical filing layer

### `ETL_BATCH`, `ETL_BATCH_TABLE_COUNT`, and `ETL_BATCH_ACCESSION`

`ETL_BATCH` contains one row per source ZIP, identified by a unique SHA-256.
It records the source filename, optional data-set quarter, append versus
existing-data registration, timestamps, status, and any error. Table-level
source and database counts are stored in `ETL_BATCH_TABLE_COUNT`.
`ETL_BATCH_ACCESSION` relates every imported accession to exactly one batch
without adding non-SEC columns to the original raw tables.

### `QUARTER`

`QUARTER` provides sortable integer keys such as `201302`, labels such as
`2013Q2`, ISO quarter-end dates, and the immediately preceding quarter key.
The key represents `COVERPAGE.REPORTCALENDARORQUARTER`, not the quarter in
which the source ZIP was published.

### `NORMALIZED_FILING`

This table contains one row per raw `SUBMISSION` with a ten-digit manager CIK,
ISO filing/report dates, report-quarter key, normalized amendment indicators,
confidential-omission indicator, information-table presence, and ETL batch
lineage. Original SEC date text remains unchanged in the raw tables.

### `CANONICAL_FILING` and `CANONICAL_FILING_COMPONENT`

`CANONICAL_FILING` has one row per filing-manager CIK and report quarter.
`CANONICAL_FILING_COMPONENT` classifies each holdings submission as:

- `BASE`: an original holdings report;
- `RESTATEMENT`: replaces all earlier effective components;
- `ADDITION`: a new-holdings amendment added to the current base/restatement;
- `UNKNOWN`: an amendment whose type cannot be resolved automatically; or
- `EXCLUDE`: a reviewed manual exclusion.

Groups containing unknown amendment types are `REVIEW_REQUIRED`. Additions
without an available original/restatement are `INCOMPLETE_HISTORY`. Only
`RESOLVED` groups are marked analytics-ready. `FILING_OVERRIDE` allows a
reviewed accession to be reassigned to `BASE`, `RESTATEMENT`, `ADDITION`, or
`EXCLUDE` without modifying the raw filing.

### `CANONICAL_HOLDING_LINE` and `ANALYTICS_HOLDING_LINE`

`CANONICAL_HOLDING_LINE` exposes every holding from the effective filing
components and retains the original `RAW_REPORTED_VALUE`. It supplies:

```text
VALUE_MULTIPLIER = 1000 when FILING_DATE_ISO < 2023-01-03
VALUE_MULTIPLIER = 1    otherwise
VALUE_USD        = RAW_REPORTED_VALUE × VALUE_MULTIPLIER
```

This implements the SEC value-unit change based on filing date, including
later amendments for old report quarters. `ANALYTICS_HOLDING_LINE` filters the
canonical view to amendment groups that are fully resolved. Confidential
omission remains explicitly flagged even when the filing sequence is resolved.

### `FILING_VALUE_RECONCILIATION`

This view compares the sum of raw values in each effective information table
with `SUMMARYPAGE.TABLEVALUETOTAL`. It labels exact matches, one-unit rounding
differences, zero summaries, approximate factor-of-1,000 discrepancies,
missing summaries, and other mismatches. The pipeline does not silently repair
these as-filed discrepancies. The status is also exposed as
`CANONICAL_HOLDING_LINE.VALUE_RECONCILIATION_STATUS` for filtering and later
reviewed overrides.

## Security classification and instruments

### `SECURITY_TYPE`

Controlled taxonomy used by the analytical layer:

| Code | Meaning | Included in initial core holdings |
|---|---|---|
| `COMMON_STOCK` | Common equity | Yes |
| `ETF` | Exchange-traded fund | Yes |
| `ADR` | Depositary receipt | No |
| `PREFERRED_STOCK` | Preferred equity | No |
| `OPTION_CALL` | Call option | No |
| `OPTION_PUT` | Put option | No |
| `DEBT_BOND` | Debt or principal amount | No |
| `CONVERTIBLE` | Convertible security | No |
| `FUND_OTHER` | Other reported fund | No |
| `UNKNOWN` | Insufficient classification evidence | No |

The core flag controls product filtering; all types remain available in the
database.

### `SECURITY_CLASS_RULE` and `CUSIP_SECURITY_TYPE_OVERRIDE`

Rules are ordered, inspectable mappings over normalized `TITLEOFCLASS` or
`NAMEOFISSUER` text. System rules intentionally recognize only explicit or
high-confidence terminology. A reviewed CUSIP override takes precedence over
all rules and records its source, reason, and review timestamp.

### `CUSIP_CLASSIFICATION`

Contains one current classification per `CUSIP_ID`. Each historical
`CUSIP_VARIANT` is evaluated against the rules and weighted by
`OCCURRENCE_COUNT`. The security type receiving the most matched occurrences
wins, with deterministic tie-breaking. The table records total, matched, and
winning occurrences plus `CLASSIFICATION_CONFIDENCE`, calculated as winning
occurrences divided by all occurrences. A CUSIP with no matched rule remains
`UNKNOWN`; uncertainty is not silently converted to common stock.

This classification is a current analytical attribute. The project does not
retain historical classification changes.

### `INSTRUMENT`

Stable surrogate key at the logical grain:

```text
CUSIP_ID
SECURITY_TYPE_ID
OPTION_TYPE
AMOUNT_TYPE
```

`PUTCALL` takes precedence over the base CUSIP classification. A non-option
`PRN` amount becomes `DEBT_BOND`. Consequently, common shares, calls, puts, and
principal amounts using the same CUSIP never share an instrument key or have
their reported amounts summed together.

## Quarterly CIK–instrument facts

### `CIK_INSTRUMENT`

Stable relationship key for one filing-manager CIK and one instrument. It
records the first and latest observed report-quarter keys. Existing IDs are
preserved across refreshes.

### `CIK_INSTRUMENT_QUARTER`

One row per CIK/instrument relationship and report quarter, built only from
`ANALYTICS_HOLDING_LINE`. It contains normalized `VALUE_USD`, reported amount,
portfolio weight, source-row and effective-accession counts, shared-discretion
and confidential-omission flags, and the propagated value-quality status.

Multiple canonical holding lines are combined only after manager, quarter,
CUSIP, security type, option type, and amount type resolve to the same
instrument.

### `CIK_INSTRUMENT_CHANGE`

One row per stable CIK/instrument relationship and adjacent report-quarter
pair. It records prior/current normalized values and reported amounts,
absolute and percentage changes, and an inferred action: `NEW`, `ADDED`,
`REDUCED`, `EXITED`, `UNCHANGED`, or `UNKNOWN`.

Rows are generated only when the manager has analytics-ready summaries in both
adjacent quarters. A missing manager filing therefore does not create a false
exit. If either effective filing reports a confidential omission, the row is
retained with `ACTION = 'UNKNOWN'`, `IS_COMPARABLE = 0`, and an explicit
reason. Value-quality status is propagated independently from amount-based
action classification.

### `CIK_CUSIP_QUARTER`

Convenience view rolling one manager's separate instruments back to a CUSIP
and report quarter. Values may be summed, but reported amounts are intentionally
not exposed because common, option, and principal quantities are not
interchangeable.

## Quarterly summaries

### `CIK_QUARTER_SUMMARY`

One row per filing-manager CIK and analytics-ready report quarter. It contains
portfolio reported value, instrument and CUSIP counts, common/ETF/call/put and
unknown value breakdowns, largest position, largest/top-ten weights, and
quality flags.

### `CUSIP_QUARTER_SUMMARY`

One row per CUSIP and report quarter. It contains manager count, total reported
value and type breakdowns, largest reporting manager, manager concentration
HHI, and shared-discretion/confidential/value-quality flags. Totals represent
as-filed manager reports and can include economically overlapping shared
discretion; the flag allows downstream filtering and disclosure.
