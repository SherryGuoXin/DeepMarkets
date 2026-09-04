#!/usr/bin/env python3
"""Export ranked 13F managers and securities for targeted 13D/G research."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_DIR / "curated" / "13dg_targets"

MANAGER_FIELDS = (
    "rank", "cik", "institution_name", "portfolio_value_usd",
    "holding_count", "instrument_count", "quarter_id", "quarter_label",
    "quarter_status", "latest_filing_date", "ranking_basis",
)
SECURITY_FIELDS = (
    "rank", "cusip", "issuer", "title_of_class", "security_type",
    "total_value_usd", "manager_count", "largest_manager_cik", "quarter_id",
    "quarter_label", "quarter_status", "latest_filing_date", "ranking_basis",
)


def selected_quarter(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT Q.QUARTER_ID, Q.QUARTER_LABEL,
               COALESCE(S.STATUS, 'COMPLETE') AS STATUS,
               S.LATEST_FILING_DATE
        FROM QUARTER Q
        LEFT JOIN DAILY_CIK_QUARTER_STATUS S USING (QUARTER_ID)
        WHERE Q.QUARTER_ID = (
            SELECT MAX(QUARTER_ID) FROM (
                SELECT QUARTER_ID FROM CIK_QUARTER_SUMMARY
                UNION ALL
                SELECT QUARTER_ID FROM DAILY_CIK_QUARTER_SUMMARY
            )
        )
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("no analytical quarter is available")
    return dict(row)


def ranked_managers(
    connection: sqlite3.Connection, quarter: dict[str, object], limit: int
) -> list[dict[str, object]]:
    daily = quarter["STATUS"] == "PARTIAL"
    table = "DAILY_CIK_QUARTER_SUMMARY" if daily else "CIK_QUARTER_SUMMARY"
    records = connection.execute(
        f"""
        SELECT S.MANAGER_CIK AS cik,
               COALESCE(NULLIF(C.MANAGER_NAME, ''),
                        NULLIF(C.SEC_COMPANY_NAME, ''), S.MANAGER_CIK)
                   AS institution_name,
               S.PORTFOLIO_VALUE_USD AS portfolio_value_usd,
               S.CUSIP_COUNT AS holding_count,
               S.INSTRUMENT_COUNT AS instrument_count
        FROM {table} S
        LEFT JOIN CIK C ON C.CIK = S.MANAGER_CIK
        WHERE S.QUARTER_ID = ?
        ORDER BY S.PORTFOLIO_VALUE_USD DESC, S.MANAGER_CIK
        LIMIT ?
        """,
        (quarter["QUARTER_ID"], limit),
    ).fetchall()
    return [
        {
            "rank": rank,
            **dict(record),
            "quarter_id": quarter["QUARTER_ID"],
            "quarter_label": quarter["QUARTER_LABEL"],
            "quarter_status": quarter["STATUS"],
            "latest_filing_date": quarter["LATEST_FILING_DATE"] or "",
            "ranking_basis": "reported_13f_portfolio_value_usd",
        }
        for rank, record in enumerate(records, start=1)
    ]


def ranked_securities(
    connection: sqlite3.Connection, quarter: dict[str, object], limit: int
) -> list[dict[str, object]]:
    if quarter["STATUS"] == "PARTIAL":
        sql = """
        SELECT S.CUSIP AS cusip, S.ISSUER AS issuer,
               S.TITLE_OF_CLASS AS title_of_class,
               S.SECURITY_TYPE AS security_type,
               S.TOTAL_VALUE_USD AS total_value_usd,
               S.MANAGER_COUNT AS manager_count,
               S.LARGEST_MANAGER_CIK AS largest_manager_cik
        FROM DAILY_CUSIP_QUARTER_SUMMARY S
        WHERE S.QUARTER_ID = ?
        ORDER BY S.TOTAL_VALUE_USD DESC, S.CUSIP
        LIMIT ?
        """
    else:
        sql = """
        SELECT V.CUSIP AS cusip, V.CURRENT_NAMEOFISSUER AS issuer,
               V.CURRENT_TITLEOFCLASS AS title_of_class,
               T.SECURITY_TYPE_CODE AS security_type,
               S.TOTAL_VALUE_USD AS total_value_usd,
               S.MANAGER_COUNT AS manager_count,
               S.LARGEST_MANAGER_CIK AS largest_manager_cik
        FROM CUSIP_QUARTER_SUMMARY S
        JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID)
        LEFT JOIN CUSIP_CLASSIFICATION C USING (CUSIP_ID)
        LEFT JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
        WHERE S.QUARTER_ID = ?
        ORDER BY S.TOTAL_VALUE_USD DESC, V.CUSIP
        LIMIT ?
        """
    records = connection.execute(
        sql, (quarter["QUARTER_ID"], limit)
    ).fetchall()
    return [
        {
            "rank": rank,
            **dict(record),
            "quarter_id": quarter["QUARTER_ID"],
            "quarter_label": quarter["QUARTER_LABEL"],
            "quarter_status": quarter["STATUS"],
            "latest_filing_date": quarter["LATEST_FILING_DATE"] or "",
            "ranking_basis": "aggregate_reported_13f_value_usd",
        }
        for rank, record in enumerate(records, start=1)
    ]


def write_csv(path: Path, fields: tuple[str, ...], records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def build(database: Path, output: Path, limit: int = 200) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        quarter = selected_quarter(connection)
        managers = ranked_managers(connection, quarter, limit)
        securities = ranked_securities(connection, quarter, limit)
    finally:
        connection.close()
    write_csv(output / "top_200_managers.csv", MANAGER_FIELDS, managers)
    write_csv(output / "top_200_securities.csv", SECURITY_FIELDS, securities)
    return {"quarter": quarter, "managers": len(managers), "securities": len(securities)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=200)
    arguments = parser.parse_args()
    if arguments.limit < 1:
        parser.error("--limit must be positive")
    result = build(arguments.database, arguments.output, arguments.limit)
    quarter = result["quarter"]
    print(
        f"Exported {result['managers']} managers and {result['securities']} "
        f"securities for {quarter['QUARTER_LABEL']} ({quarter['STATUS']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
