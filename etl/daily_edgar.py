#!/usr/bin/env python3
"""Incrementally import new Form 13F filings from the SEC EDGAR archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from . import (
        build_canonical_filings,
        build_daily_cik,
        build_latest_filings,
        enrich_cik,
    )
except ImportError:
    import build_canonical_filings
    import build_daily_cik
    import build_latest_filings
    import enrich_cik


PROJECT_DIR = Path(__file__).resolve().parent.parent
SEC_BASE_URL = "https://www.sec.gov"
FORM_TYPES = {"13F-HR", "13F-HR/A"}

DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS DAILY_EDGAR_RUN (
    DAILY_EDGAR_RUN_ID INTEGER PRIMARY KEY,
    INDEX_URL TEXT NOT NULL,
    STATUS TEXT NOT NULL
        CHECK (STATUS IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')),
    STARTED_AT TEXT NOT NULL,
    COMPLETED_AT TEXT,
    DISCOVERED_COUNT INTEGER NOT NULL DEFAULT 0,
    IMPORTED_COUNT INTEGER NOT NULL DEFAULT 0,
    SKIPPED_COUNT INTEGER NOT NULL DEFAULT 0,
    FAILED_COUNT INTEGER NOT NULL DEFAULT 0,
    ERROR_MESSAGE TEXT
);

CREATE TABLE IF NOT EXISTS DAILY_EDGAR_ACCESSION (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    DAILY_EDGAR_RUN_ID INTEGER NOT NULL,
    DIRECTORY_URL TEXT NOT NULL,
    PRIMARY_DOCUMENT_URL TEXT NOT NULL,
    INFORMATION_TABLE_URL TEXT,
    PRIMARY_DOCUMENT_SHA256 CHAR(64) NOT NULL,
    INFORMATION_TABLE_SHA256 CHAR(64),
    FETCHED_AT TEXT NOT NULL,
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES SUBMISSION (ACCESSION_NUMBER),
    FOREIGN KEY (DAILY_EDGAR_RUN_ID)
        REFERENCES DAILY_EDGAR_RUN (DAILY_EDGAR_RUN_ID)
);

CREATE TABLE IF NOT EXISTS DAILY_EDGAR_PUBLICATION (
    ACCESSION_NUMBER VARCHAR2(25) PRIMARY KEY,
    PUBLISHED_AT TEXT NOT NULL,
    FOREIGN KEY (ACCESSION_NUMBER)
        REFERENCES DAILY_EDGAR_ACCESSION (ACCESSION_NUMBER) ON DELETE CASCADE
);
"""


@dataclass(frozen=True)
class Filing:
    accession: str
    cik: str
    company_name: str
    form_type: str
    filing_date: str
    filename: str

    @property
    def directory_url(self) -> str:
        return (
            f"{SEC_BASE_URL}/Archives/edgar/data/{int(self.cik)}/"
            f"{self.accession.replace('-', '')}"
        )


class SecClient:
    def __init__(self, user_agent: str, requests_per_second: float = 8.0):
        if "@" not in user_agent:
            raise ValueError("SEC user agent must include a contact email address")
        self.user_agent = user_agent
        self.minimum_interval = 1.0 / requests_per_second
        self.last_request = 0.0

    def get(self, url: str, retries: int = 5) -> bytes:
        for attempt in range(retries):
            delay = self.minimum_interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read()
                self.last_request = time.monotonic()
                return body
            except urllib.error.HTTPError as error:
                self.last_request = time.monotonic()
                if error.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                    raise
            except urllib.error.URLError:
                self.last_request = time.monotonic()
                if attempt == retries - 1:
                    raise
            time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError(f"failed to download {url}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def quarter_for(day: date) -> int:
    return (day.month - 1) // 3 + 1


def quarterly_index_url(year: int, quarter: int) -> str:
    return f"{SEC_BASE_URL}/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx"


def discover_filings(index: bytes) -> list[Filing]:
    filings: list[Filing] = []
    for raw_line in index.decode("latin-1").splitlines():
        fields = raw_line.split("|")
        if len(fields) != 5 or fields[2].upper() not in FORM_TYPES:
            continue
        cik, company_name, form_type, filing_date, filename = fields
        accession = Path(filename).stem
        filings.append(
            Filing(
                accession=accession,
                cik=cik.zfill(10),
                company_name=company_name,
                form_type=form_type.upper(),
                filing_date=filing_date,
                filename=filename,
            )
        )
    return sorted(
        filings,
        key=lambda filing: (filing.filing_date, filing.accession),
        reverse=True,
    )


def strip_namespaces(root: ET.Element) -> ET.Element:
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def xml_root(data: bytes) -> ET.Element:
    return strip_namespaces(ET.fromstring(data))


def text(node: ET.Element | None, path: str, default: str | None = None) -> str | None:
    if node is None:
        return default
    found = node.find(path)
    if found is None or found.text is None:
        return default
    value = found.text.strip()
    return value if value else default


def required(node: ET.Element | None, path: str) -> str:
    value = text(node, path)
    if value is None:
        raise ValueError(f"required XML field is missing: {path}")
    return value


def sec_date(value: str | None) -> str | None:
    if not value:
        return None
    for pattern in ("%m-%d-%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, pattern).strftime("%d-%b-%Y").upper()
        except ValueError:
            pass
    raise ValueError(f"unsupported SEC date: {value!r}")


def yes_no(value: str | None) -> str | None:
    if value is None:
        return None
    return "Y" if value.strip().lower() in ("true", "1", "y", "yes") else "N"


def integer(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value.replace(",", ""))


def amendment_type(cover: ET.Element | None) -> str | None:
    """Read the SEC's current nested field while retaining legacy compatibility."""
    return text(cover, "amendmentInfo/amendmentType") or text(
        cover, "amendmentType"
    )


def filing_xml(client: SecClient, filing: Filing) -> tuple[str, bytes, str | None, bytes | None]:
    listing_url = f"{filing.directory_url}/index.json"
    listing = json.loads(client.get(listing_url))
    names = [
        item["name"]
        for item in listing["directory"]["item"]
        if item["name"].lower().endswith(".xml")
    ]
    if not names:
        raise ValueError(f"no XML documents listed for {filing.accession}")

    documents: dict[str, bytes] = {}

    def document(name: str) -> bytes:
        if name not in documents:
            documents[name] = client.get(f"{filing.directory_url}/{name}")
        return documents[name]

    primary_name = next((name for name in names if "primary" in name.lower()), None)
    info_name = next(
        (name for name in names if "info" in name.lower() and "table" in name.lower()),
        None,
    )
    for name in names:
        if primary_name and info_name:
            break
        try:
            root_name = xml_root(document(name)).tag.lower()
        except ET.ParseError:
            continue
        if root_name == "edgarsubmission" and primary_name is None:
            primary_name = name
        elif root_name == "informationtable" and info_name is None:
            info_name = name
    if primary_name is None:
        raise ValueError(f"primary XML document not found for {filing.accession}")

    primary_url = f"{filing.directory_url}/{primary_name}"
    info_url = f"{filing.directory_url}/{info_name}" if info_name else None
    return (
        primary_url,
        document(primary_name),
        info_url,
        document(info_name) if info_name else None,
    )


def parsed_rows(
    filing: Filing,
    primary_data: bytes,
    info_data: bytes | None,
) -> dict[str, list[tuple[object, ...]]]:
    root = xml_root(primary_data)
    cover = root.find("./formData/coverPage")
    signature = root.find("./formData/signatureBlock")
    summary = root.find("./formData/summaryPage")
    report_date = sec_date(required(cover, "reportCalendarOrQuarter"))
    period_of_report = sec_date(
        text(root, "./headerData/filerInfo/periodOfReport")
        or required(cover, "reportCalendarOrQuarter")
    )
    manager = cover.find("filingManager") if cover is not None else None
    address = manager.find("address") if manager is not None else None

    rows: dict[str, list[tuple[object, ...]]] = {
        "SUBMISSION": [(
            filing.accession,
            sec_date(filing.filing_date),
            filing.form_type,
            filing.cik,
            period_of_report,
        )],
        "COVERPAGE": [(
            filing.accession,
            report_date,
            yes_no(text(cover, "isAmendment")),
            integer(text(cover, "amendmentNo")),
            amendment_type(cover),
            yes_no(text(cover, "confDeniedExpired")),
            sec_date(text(cover, "dateDeniedExpired")),
            sec_date(text(cover, "dateReported")),
            text(cover, "reasonForNonConfidentiality"),
            required(manager, "name"),
            text(address, "street1"),
            text(address, "street2"),
            text(address, "city"),
            text(address, "stateOrCountry"),
            text(address, "zipCode"),
            required(cover, "reportType"),
            text(cover, "form13FFileNumber"),
            text(cover, "crdNumber"),
            text(cover, "secFileNumber"),
            yes_no(text(cover, "provideInfoForInstruction5")) or "N",
            text(cover, "additionalInformation"),
        )],
        "OTHERMANAGER": [],
        "SIGNATURE": [],
        "SUMMARYPAGE": [],
        "OTHERMANAGER2": [],
        "INFOTABLE": [],
    }

    if signature is not None:
        rows["SIGNATURE"].append((
            filing.accession,
            required(signature, "name"),
            required(signature, "title"),
            text(signature, "phone"),
            required(signature, "signature"),
            required(signature, "city"),
            required(signature, "stateOrCountry"),
            sec_date(required(signature, "signatureDate")),
        ))

    if summary is not None:
        rows["SUMMARYPAGE"].append((
            filing.accession,
            integer(text(summary, "otherIncludedManagersCount")),
            integer(text(summary, "tableEntryTotal")),
            integer(text(summary, "tableValueTotal")),
            yes_no(text(summary, "isConfidentialOmitted")),
        ))

    for index, other in enumerate(
        root.findall("./headerData/filerInfo/otherManagersInfo/otherManager"),
        start=1,
    ):
        rows["OTHERMANAGER"].append((
            filing.accession,
            index,
            text(other, "cik"),
            text(other, "form13FFileNumber"),
            text(other, "crdNumber"),
            text(other, "secFileNumber"),
            required(other, "name"),
        ))

    if summary is not None:
        for other in summary.findall("./otherManagers2Info/otherManager2"):
            details = other.find("otherManager")
            if details is None:
                details = other
            rows["OTHERMANAGER2"].append((
                filing.accession,
                integer(required(other, "sequenceNumber")),
                text(details, "cik"),
                text(details, "form13FFileNumber"),
                text(details, "crdNumber"),
                text(details, "secFileNumber"),
                required(details, "name"),
            ))

    if info_data:
        info_root = xml_root(info_data)
        for index, holding in enumerate(info_root.findall(".//infoTable"), start=1):
            amount = holding.find("shrsOrPrnAmt")
            authority = holding.find("votingAuthority")
            rows["INFOTABLE"].append((
                filing.accession,
                index,
                text(holding, "nameOfIssuer", ""),
                required(holding, "titleOfClass"),
                required(holding, "cusip").upper().zfill(9),
                text(holding, "figi"),
                integer(required(holding, "value")),
                integer(required(amount, "sshPrnamt")),
                required(amount, "sshPrnamtType"),
                text(holding, "putCall"),
                required(holding, "investmentDiscretion"),
                text(holding, "otherManager"),
                integer(required(authority, "Sole")),
                integer(required(authority, "Shared")),
                integer(required(authority, "None")),
            ))
    return rows


INSERT_SQL = {
    table: f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in range(count))})'
    for table, count in {
        "SUBMISSION": 5,
        "COVERPAGE": 21,
        "OTHERMANAGER": 7,
        "SIGNATURE": 8,
        "SUMMARYPAGE": 5,
        "OTHERMANAGER2": 7,
        "INFOTABLE": 15,
    }.items()
}


def ensure_schema(connection: sqlite3.Connection) -> None:
    required_tables = {
        "SUBMISSION", "COVERPAGE", "OTHERMANAGER", "SIGNATURE",
        "SUMMARYPAGE", "OTHERMANAGER2", "INFOTABLE",
    }
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        )
    }
    missing = required_tables - tables
    if missing:
        raise ValueError("database is missing raw tables: " + ", ".join(sorted(missing)))
    connection.executescript(DAILY_SCHEMA)
    connection.executescript(build_daily_cik.SCHEMA)
    build_daily_cik.ensure_status_columns(connection)
    build_latest_filings.ensure_schema(connection)
    # Existing installations predate publication checkpoints. Mark rows only
    # when their institution analytics are present or the exact accession was
    # loaded by a bulk batch. Quarter-level coverage alone is insufficient:
    # a late filing can reopen a previously reconciled quarter.
    connection.execute(
        """
        INSERT OR IGNORE INTO DAILY_EDGAR_PUBLICATION
            (ACCESSION_NUMBER, PUBLISHED_AT)
        SELECT D.ACCESSION_NUMBER, COALESCE(S.UPDATED_AT, D.FETCHED_AT)
        FROM DAILY_EDGAR_ACCESSION D
        JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
        LEFT JOIN DAILY_CIK_QUARTER_SUMMARY S
          ON S.MANAGER_CIK = N.MANAGER_CIK
         AND S.QUARTER_ID = N.QUARTER_ID
        WHERE S.MANAGER_CIK IS NOT NULL
           OR EXISTS (
                SELECT 1 FROM ETL_BATCH_ACCESSION B
                WHERE B.ACCESSION_NUMBER = D.ACCESSION_NUMBER
           )
        """
    )
    connection.commit()


def publish_accessions(database: Path, accessions: set[str]) -> dict[str, int]:
    """Publish committed raw filings without rebuilding global analytics."""
    selected = set(accessions)
    if not selected:
        return {"filings": 0, "institutions": 0}
    canonical = build_canonical_filings.build_incremental(database, selected)
    connection = sqlite3.connect(database)
    try:
        placeholders = ",".join("?" for _ in selected)
        manager_quarters = {
            (str(row[0]), int(row[1]))
            for row in connection.execute(
                f"""
                SELECT DISTINCT MANAGER_CIK, QUARTER_ID
                FROM NORMALIZED_FILING
                WHERE ACCESSION_NUMBER IN ({placeholders})
                  AND QUARTER_ID IS NOT NULL
                """,
                sorted(selected),
            )
        }
        # An amended quarter changes the baseline used to classify the next
        # quarter. Rebuild that dependent manager-quarter when it exists.
        dependent_quarters: set[tuple[str, int]] = set()
        for manager_cik, report_quarter in manager_quarters:
            dependent_quarters.update(
                (str(row[0]), int(row[1]))
                for row in connection.execute(
                    """
                    SELECT F.MANAGER_CIK, F.QUARTER_ID
                    FROM QUARTER Q
                    JOIN CANONICAL_FILING F ON F.QUARTER_ID = Q.QUARTER_ID
                    WHERE Q.PREVIOUS_QUARTER_ID = ?
                      AND F.MANAGER_CIK = ?
                      AND F.IS_ANALYTICS_READY = 1
                    """,
                    (report_quarter, manager_cik),
                )
            )
        manager_quarters.update(dependent_quarters)
    finally:
        connection.close()
    enrich_cik.populate_managers(
        database, {manager_cik for manager_cik, _ in manager_quarters}
    )
    daily = build_daily_cik.build_incremental(database, manager_quarters)
    build_latest_filings.refresh_manager_quarters(database, manager_quarters)
    connection = sqlite3.connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT INTO DAILY_EDGAR_PUBLICATION (ACCESSION_NUMBER, PUBLISHED_AT)
            VALUES (?, ?)
            ON CONFLICT (ACCESSION_NUMBER) DO UPDATE SET
                PUBLISHED_AT = excluded.PUBLISHED_AT
            """,
            ((accession, utc_now()) for accession in sorted(selected)),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "filings": canonical["normalized_filings"],
        "institutions": daily["institutions"],
    }


def repair_missing_amendment_types(
    database: Path, user_agent: str
) -> dict[str, int]:
    """Backfill amendment types missed by the former flat-path XML parser."""
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    candidates = connection.execute(
        """
        SELECT N.ACCESSION_NUMBER, D.PRIMARY_DOCUMENT_URL, P.AMENDMENTTYPE
        FROM NORMALIZED_FILING N
        JOIN DAILY_EDGAR_ACCESSION D USING (ACCESSION_NUMBER)
        JOIN COVERPAGE P USING (ACCESSION_NUMBER)
        LEFT JOIN DAILY_EDGAR_PUBLICATION U USING (ACCESSION_NUMBER)
        WHERE N.IS_AMENDMENT = 1 AND (
              COALESCE(TRIM(N.AMENDMENT_TYPE), '') = ''
              OR U.ACCESSION_NUMBER IS NULL
          )
        ORDER BY N.ACCESSION_NUMBER
        """
    ).fetchall()
    client = SecClient(user_agent)
    repaired: set[str] = set()
    failures: list[str] = []
    try:
        for candidate in candidates:
            accession = str(candidate["ACCESSION_NUMBER"])
            value = candidate["AMENDMENTTYPE"]
            try:
                if not value:
                    root = xml_root(client.get(candidate["PRIMARY_DOCUMENT_URL"]))
                    value = amendment_type(root.find("./formData/coverPage"))
                normalized = str(value or "").strip().upper()
                if normalized not in {"RESTATEMENT", "NEW HOLDINGS"}:
                    raise ValueError(f"unsupported amendment type: {value!r}")
                connection.execute(
                    "UPDATE COVERPAGE SET AMENDMENTTYPE = ? WHERE ACCESSION_NUMBER = ?",
                    (normalized, accession),
                )
                # Publication is the repair checkpoint. If the process is
                # interrupted during materialization, the next daily run or
                # repair invocation will safely republish this accession.
                connection.execute(
                    "DELETE FROM DAILY_EDGAR_PUBLICATION WHERE ACCESSION_NUMBER = ?",
                    (accession,),
                )
                connection.commit()
                repaired.add(accession)
            except Exception as error:
                connection.rollback()
                failures.append(f"{accession}: {error}")
                print(f"Failed to repair {accession}: {error}", file=sys.stderr, flush=True)
    finally:
        connection.close()

    published = publish_accessions(database, repaired) if repaired else {
        "filings": 0,
        "institutions": 0,
    }
    return {
        "candidates": len(candidates),
        "repaired": len(repaired),
        "failed": len(failures),
        "institutions": published["institutions"],
    }


def import_filing(
    connection: sqlite3.Connection,
    run_id: int,
    filing: Filing,
    primary_url: str,
    primary_data: bytes,
    info_url: str | None,
    info_data: bytes | None,
) -> bool:
    if connection.execute(
        "SELECT 1 FROM SUBMISSION WHERE ACCESSION_NUMBER = ?", (filing.accession,)
    ).fetchone():
        return False
    rows = parsed_rows(filing, primary_data, info_data)
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table, table_rows in rows.items():
            connection.executemany(INSERT_SQL[table], table_rows)
        connection.execute(
            """
            INSERT INTO DAILY_EDGAR_ACCESSION VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filing.accession,
                run_id,
                filing.directory_url,
                primary_url,
                info_url,
                hashlib.sha256(primary_data).hexdigest(),
                hashlib.sha256(info_data).hexdigest() if info_data else None,
                utc_now(),
            ),
        )
        build_latest_filings.refresh_daily_accession(connection, filing.accession)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return True


def run_daily(
    database: Path,
    user_agent: str,
    year: int,
    quarter: int,
    skip_derived: bool,
    listings: Path,
    sic_cache: Path,
    publish_batch_size: int = 100,
) -> dict[str, int]:
    index_url = quarterly_index_url(year, quarter)
    client = SecClient(user_agent)
    filings = discover_filings(client.get(index_url))
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    cursor = connection.execute(
        """
        INSERT INTO DAILY_EDGAR_RUN (INDEX_URL, STATUS, STARTED_AT, DISCOVERED_COUNT)
        VALUES (?, 'RUNNING', ?, ?)
        """,
        (index_url, utc_now(), len(filings)),
    )
    run_id = int(cursor.lastrowid)
    connection.commit()
    existing = {
        row[0]
        for row in connection.execute("SELECT ACCESSION_NUMBER FROM SUBMISSION")
    }
    pending = [filing for filing in filings if filing.accession not in existing]
    imported = 0
    failures: list[str] = []
    unpublished = {
        row[0]
        for row in connection.execute(
            """
            SELECT D.ACCESSION_NUMBER
            FROM DAILY_EDGAR_ACCESSION D
            LEFT JOIN DAILY_EDGAR_PUBLICATION P USING (ACCESSION_NUMBER)
            WHERE P.ACCESSION_NUMBER IS NULL
            """
        )
    }
    try:
        for filing in pending:
            try:
                primary_url, primary_data, info_url, info_data = filing_xml(client, filing)
                if import_filing(
                    connection, run_id, filing, primary_url, primary_data, info_url, info_data
                ):
                    imported += 1
                    unpublished.add(filing.accession)
                    print(f"Imported {filing.accession} {filing.company_name}", flush=True)
            except Exception as error:
                failures.append(f"{filing.accession}: {error}")
                print(f"Failed {filing.accession}: {error}", file=sys.stderr, flush=True)
            connection.execute(
                """
                UPDATE DAILY_EDGAR_RUN
                SET IMPORTED_COUNT = ?, SKIPPED_COUNT = ?, FAILED_COUNT = ?,
                    ERROR_MESSAGE = ?
                WHERE DAILY_EDGAR_RUN_ID = ?
                """,
                (
                    imported, len(filings) - len(pending), len(failures),
                    "\n".join(failures) or None, run_id,
                ),
            )
            connection.commit()
            if not skip_derived and len(unpublished) >= publish_batch_size:
                batch = set(sorted(unpublished)[:publish_batch_size])
                published = publish_accessions(database, batch)
                unpublished.difference_update(batch)
                print(
                    f"Published {published['filings']:,} filings for "
                    f"{published['institutions']:,} affected institutions",
                    flush=True,
                )
        while not skip_derived and unpublished:
            batch = set(sorted(unpublished)[:publish_batch_size])
            published = publish_accessions(database, batch)
            unpublished.difference_update(batch)
            print(
                f"Published {published['filings']:,} filings for "
                f"{published['institutions']:,} affected institutions",
                flush=True,
            )
        status = classify_run_status(
            len(filings), len(pending), imported, len(failures)
        )
        connection.execute(
            """
            UPDATE DAILY_EDGAR_RUN
            SET STATUS = ?, COMPLETED_AT = ?, IMPORTED_COUNT = ?,
                SKIPPED_COUNT = ?, FAILED_COUNT = ?, ERROR_MESSAGE = ?
            WHERE DAILY_EDGAR_RUN_ID = ?
            """,
            (
                status,
                utc_now(),
                imported,
                len(filings) - len(pending),
                len(failures),
                "\n".join(failures) or None,
                run_id,
            ),
        )
        connection.commit()
    except Exception as error:
        failures.append(f"publisher: {error}")
        connection.execute(
            """
            UPDATE DAILY_EDGAR_RUN
            SET STATUS = ?, COMPLETED_AT = ?, IMPORTED_COUNT = ?,
                SKIPPED_COUNT = ?, FAILED_COUNT = ?, ERROR_MESSAGE = ?
            WHERE DAILY_EDGAR_RUN_ID = ?
            """,
            (
                "PARTIAL" if imported else "FAILED", utc_now(), imported,
                len(filings) - len(pending), len(failures),
                "\n".join(failures), run_id,
            ),
        )
        connection.commit()
        raise
    finally:
        connection.close()

    return {
        "discovered": len(filings),
        "pending": len(pending),
        "imported": imported,
        "failed": len(failures),
    }


def classify_run_status(
    discovered: int, pending: int, imported: int, failed: int
) -> str:
    if not failed:
        return "COMPLETED"
    covered = discovered - pending + imported
    return "PARTIAL" if covered else "FAILED"


def rollback_daily(database: Path) -> int:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    accessions = [
        row[0]
        for row in connection.execute(
            "SELECT ACCESSION_NUMBER FROM DAILY_EDGAR_ACCESSION"
        )
    ]
    if not accessions:
        for table in (
            "DAILY_CIK_HOLDING",
            "DAILY_CIK_QUARTER_ACTIVITY",
            "DAILY_CIK_QUARTER_SUMMARY",
            "DAILY_CUSIP_OPTION_SUMMARY",
            "DAILY_CUSIP_QUARTER_ACTIVITY",
            "DAILY_CUSIP_QUARTER_SUMMARY",
            "DAILY_CUSIP_IDENTITY",
            "DAILY_CIK_QUARTER_STATUS",
            "DAILY_EDGAR_PUBLICATION",
            "DAILY_EDGAR_ACCESSION",
            "DAILY_EDGAR_RUN",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.commit()
        connection.close()
        return 0

    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("DELETE FROM LATEST_FILING_FEED")
        for table in (
            "DAILY_CIK_HOLDING",
            "DAILY_CIK_QUARTER_ACTIVITY",
            "DAILY_CIK_QUARTER_SUMMARY",
            "DAILY_CUSIP_OPTION_SUMMARY",
            "DAILY_CUSIP_QUARTER_ACTIVITY",
            "DAILY_CUSIP_QUARTER_SUMMARY",
            "DAILY_CUSIP_IDENTITY",
            "DAILY_CIK_QUARTER_STATUS",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute("DELETE FROM CANONICAL_FILING_COMPONENT")
        connection.execute("DELETE FROM CANONICAL_FILING")
        placeholders = ",".join("?" for _ in accessions)
        for table in (
            "FILING_VALUE_SCALE", "FILING_VALUE_SCALE_OVERRIDE",
            "FILING_OVERRIDE", "NORMALIZED_FILING",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE ACCESSION_NUMBER IN ({placeholders})",
                accessions,
            )
        connection.execute("DELETE FROM DAILY_EDGAR_ACCESSION")
        for table in (
            "INFOTABLE", "OTHERMANAGER2", "SUMMARYPAGE", "SIGNATURE",
            "OTHERMANAGER", "COVERPAGE", "SUBMISSION",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE ACCESSION_NUMBER IN ({placeholders})",
                accessions,
            )
        connection.execute("DROP TABLE DAILY_EDGAR_PUBLICATION")
        connection.execute("DROP TABLE DAILY_EDGAR_ACCESSION")
        connection.execute("DROP TABLE DAILY_EDGAR_RUN")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(accessions)


def main() -> int:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3")
    parser.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT"))
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--quarter", type=int, choices=(1, 2, 3, 4), default=quarter_for(today))
    parser.add_argument("--skip-derived", action="store_true")
    parser.add_argument(
        "--publish-batch-size",
        type=int,
        default=100,
        help="publish affected institution analytics after this many imports",
    )
    parser.add_argument("--listings", type=Path, default=PROJECT_DIR / "raw_date/company_tickers_exchange.json")
    parser.add_argument("--sic-cache", type=Path, default=PROJECT_DIR / "raw_date/company_sic.json")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="remove all daily-imported raw rows and the daily provenance schema",
    )
    parser.add_argument(
        "--repair-amendment-types",
        action="store_true",
        help="repair previously imported amendments and rebuild affected analytics",
    )
    arguments = parser.parse_args()
    database = arguments.database.expanduser().resolve()
    try:
        if arguments.rollback:
            removed = rollback_daily(database)
            print(f"Removed {removed:,} daily EDGAR accessions")
            print("Run etl/bulk_etl.py to refill bulk coverage and rebuild derived data")
            return 0
        if not arguments.user_agent:
            parser.error("--user-agent or SEC_USER_AGENT is required")
        if arguments.repair_amendment_types:
            counts = repair_missing_amendment_types(database, arguments.user_agent)
            print(
                "Daily amendment repair: "
                + ", ".join(f"{key}={value:,}" for key, value in counts.items())
            )
            return 1 if counts["failed"] else 0
        if arguments.publish_batch_size < 1:
            parser.error("--publish-batch-size must be at least 1")
        counts = run_daily(
            database,
            arguments.user_agent,
            arguments.year,
            arguments.quarter,
            arguments.skip_derived,
            arguments.listings.expanduser().resolve(),
            arguments.sic_cache.expanduser().resolve(),
            arguments.publish_batch_size,
        )
        print(
            "Daily EDGAR update: "
            + ", ".join(f"{key}={value:,}" for key, value in counts.items())
        )
        # Individual malformed filings are recorded as a PARTIAL run and retried
        # later. Fail the process only when no discovered filing is covered at
        # all; fatal workflow errors are raised and handled below.
        covered = counts["discovered"] - counts["pending"] + counts["imported"]
        return 1 if counts["failed"] and not covered else 0
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
