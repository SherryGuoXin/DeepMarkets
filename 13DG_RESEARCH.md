# Targeted Schedule 13D/G people research

This project does not ingest the complete Schedule 13D/G corpus. It searches a
bounded set of 200 leading 13F managers and 200 leading reported securities.

## Target lists

Run `python3 etl/build_13dg_targets.py`. The two outputs under
`curated/13dg_targets/` rank managers by reported 13F portfolio value and
securities by aggregate reported 13F value. Each row records the selected
quarter and completeness status. The current lists use preliminary 2026 Q2
data through August 18, 2026 and are explicitly marked `PARTIAL`.

## SEC research

Run:

```bash
SEC_USER_AGENT='13fdata.net contact@example.com' \
python3 etl/research_13dg_people.py
```

The script uses SEC Submissions JSON for manager CIKs, SEC EDGAR Full-Text
Search for security CUSIPs, and direct SEC Archives documents. Requests are
rate-limited and cached under ignored `raw_date/13dg_cache/`.

`curated/13dg_research/people_candidates.csv` records individual reporting
persons extracted from modern Schedule XML, with target, form, accession,
filing/event dates, issuer, CUSIP, shares, ownership percentage, and direct SEC
document URL. It currently contains 55 filing-level rows: 33 manager-target
rows and 22 security-target rows.

For manager labels, an issuer-side filing is not enough. The Schedule header
filer CIK must equal the target 13F manager CIK, and the person must have SEC
reporting-person type `IN`. After deduplication to the latest supporting filing,
this produced 13 published people across 10 of the top 200 managers. Security
relationships remain research candidates and are not presented as manager
decision-makers.

Legacy HTML filings are retained as `LEGACY_OR_UNPARSED`; missing structured
fields are not guessed. Automatically extracted candidates remain separate
from `curated/notable_people.csv` until reviewed.
