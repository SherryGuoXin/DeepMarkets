# Notable people enrichment

`Notable people` is a small, curated manager-to-person enrichment. It is not a
field in Form 13F and is never inferred from holdings or a 13F signature. Every
published association is supported by a Schedule 13D/G in which the manager
CIK is the filer and the person is explicitly identified as an individual
reporting person.

The reviewed source rows live in `curated/notable_people.csv`. Each association
has a source link, relationship status, review status, review date, and display
order. Only direct SEC.gov Schedule 13D/G filing URLs are accepted by the
loader. Third-party directory links are rejected.

The public institution API returns only the person name, optional role, and
relationship status. Filing URLs and review metadata remain in the curated CSV
and database for internal audit; the page does not expose or link them.

Load or refresh the roster with:

```bash
python3 etl/load_notable_people.py --database form13f.sqlite3
```

The loader validates CIKs, replaces only the named curation set in one
transaction, and removes orphan person rows. Quarterly ETL invokes the same
loader after rebuilding `CIK`. Daily EDGAR ingestion does not touch these
tables.

Candidate discovery and the top-200 target methodology are documented in
[`13DG_RESEARCH.md`](13DG_RESEARCH.md).

To correct an entry, edit the CSV source/status and rerun the loader. To remove
the feature and return to SEC-only data:

```sql
DROP TABLE IF EXISTS CIK_NOTABLE_PERSON;
DROP TABLE IF EXISTS NOTABLE_PERSON;
```

Remove the API/UI references before dropping the tables. No SEC filing,
canonical holding, summary, or daily-update row is changed by this feature.
