#!/usr/bin/env python3
"""Find people in SEC Schedule 13D/G filings for ranked 13F targets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = PROJECT_DIR / "curated" / "13dg_targets"
DEFAULT_OUTPUT = PROJECT_DIR / "curated" / "13dg_research"
DEFAULT_CACHE = PROJECT_DIR / "raw_date" / "13dg_cache"
SCHEDULE_FORMS = {
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
}
CURRENT_FORMS = "SCHEDULE 13D,SCHEDULE 13D/A,SCHEDULE 13G,SCHEDULE 13G/A"
LEGACY_FORMS = "SC 13D,SC 13D/A,SC 13G,SC 13G/A"

FILING_FIELDS = (
    "target_type", "target_rank", "target_id", "target_name", "form",
    "accession_number", "filing_date", "filer_cik", "issuer_cik", "issuer_name", "cusip",
    "reporting_names", "document_url", "search_result_count", "extraction_status",
)
PEOPLE_FIELDS = (
    "target_type", "target_rank", "target_id", "target_name", "person_name",
    "reporting_person_type", "role", "relationship_basis", "form",
    "accession_number", "filing_date", "event_date", "issuer_cik",
    "issuer_name", "cusip", "filer_cik", "shares_beneficially_owned",
    "ownership_percent", "document_url", "extraction_method", "review_status",
)


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(element: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in element.iter() if local_name(item.tag) == name]


def first_text(element: ET.Element, name: str) -> str:
    matches = children(element, name)
    return clean("".join(matches[0].itertext())) if matches else ""


class SecClient:
    def __init__(self, user_agent: str, cache: Path, requests_per_second: float = 5.0):
        if "@" not in user_agent:
            raise ValueError("SEC user agent must include a contact email")
        self.user_agent = user_agent
        self.cache = cache
        self.interval = 1.0 / requests_per_second
        self.last_request = 0.0

    def get(self, url: str, attempts: int = 4, timeout: int = 30) -> bytes:
        digest = hashlib.sha256(url.encode()).hexdigest()
        suffix = ".json" if "json" in url or "search-index" in url else ".document"
        cached = self.cache / f"{digest}{suffix}"
        if cached.exists():
            return cached.read_bytes()
        self.cache.mkdir(parents=True, exist_ok=True)
        if url.startswith("https://www.sec.gov/Archives/"):
            delay = self.interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            completed = subprocess.run(
                [
                    "curl", "--fail", "--silent", "--show-error",
                    "--max-time", str(timeout), "--header",
                    f"User-Agent: {self.user_agent}", url,
                ],
                check=False,
                capture_output=True,
            )
            self.last_request = time.monotonic()
            if completed.returncode != 0:
                raise urllib.error.URLError(
                    completed.stderr.decode("utf-8", errors="replace").strip()
                )
            cached.write_bytes(completed.stdout)
            return completed.stdout
        for attempt in range(attempts):
            delay = self.interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "identity",
                    "Accept": "application/json,text/xml,text/html,*/*",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = response.read()
                self.last_request = time.monotonic()
                cached.write_bytes(body)
                return body
            except urllib.error.HTTPError as error:
                self.last_request = time.monotonic()
                if error.code == 404:
                    raise
                if (
                    error.code not in {403, 429, 500, 502, 503, 504}
                    or attempt == attempts - 1
                ):
                    raise
                time.sleep(2 ** attempt)
            except urllib.error.URLError:
                self.last_request = time.monotonic()
                if attempt == attempts - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError(f"failed to download {url}")

    def json(self, url: str) -> dict[str, object]:
        return json.loads(self.get(url))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def filing_url(cik: str, accession: str, document: str) -> str:
    document = document.rsplit("/", 1)[-1]
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{accession.replace('-', '')}/{document}"
    )


def parse_schedule_xml(body: bytes) -> dict[str, object] | None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    if local_name(root.tag) != "edgarSubmission":
        return None
    issuer_nodes = children(root, "issuerInfo")
    issuer = issuer_nodes[0] if issuer_nodes else root
    signatures: dict[str, str] = {}
    for item in children(root, "signatureInformation"):
        name = first_text(item, "reportingPersonName").casefold()
        title = first_text(item, "title")
        if name and title and title.casefold() != name:
            signatures[name] = title
    people = []
    for item in children(root, "coverPageHeaderReportingPersonDetails"):
        person_type = first_text(item, "typeOfReportingPerson")
        name = first_text(item, "reportingPersonName")
        if person_type != "IN" or not name:
            continue
        people.append(
            {
                "person_name": name,
                "reporting_person_type": person_type,
                "role": signatures.get(name.casefold(), ""),
                "shares_beneficially_owned": first_text(
                    item, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares"
                ),
                "ownership_percent": first_text(item, "classPercent"),
            }
        )
    return {
        "filer_cik": first_text(
            children(root, "filerCredentials")[0], "cik"
        ) if children(root, "filerCredentials") else "",
        "issuer_cik": first_text(issuer, "issuerCik"),
        "issuer_name": first_text(issuer, "issuerName"),
        "cusip": first_text(issuer, "issuerCusipNumber"),
        "event_date": first_text(root, "eventDateRequiresFilingThisStatement"),
        "reporting_names": "; ".join(
            first_text(item, "reportingPersonName")
            for item in children(root, "coverPageHeaderReportingPersonDetails")
            if first_text(item, "reportingPersonName")
        ),
        "people": people,
    }


def form_rows(document: dict[str, object]) -> list[dict[str, object]]:
    keys = (
        "accessionNumber", "filingDate", "form", "primaryDocument",
        "primaryDocDescription",
    )
    present = [key for key in keys if isinstance(document.get(key), list)]
    if not present:
        return []
    length = min(len(document[key]) for key in present)  # type: ignore[arg-type]
    return [
        {key: document[key][index] if key in present else "" for key in keys}  # type: ignore[index]
        for index in range(length)
    ]


def manager_filings(
    client: SecClient, cik: str, limit: int
) -> list[dict[str, object]]:
    submission = client.json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    filings = [
        row for row in form_rows(submission["filings"]["recent"])  # type: ignore[index]
        if row["form"] in SCHEDULE_FORMS
    ]
    if len(filings) >= limit:
        return filings[:limit]
    for historical in submission["filings"].get("files", [])[:10]:  # type: ignore[index,union-attr]
        name = historical.get("name", "")
        if name:
            document = client.json(f"https://data.sec.gov/submissions/{name}")
            filings.extend(
                row for row in form_rows(document)
                if row["form"] in SCHEDULE_FORMS
            )
            if len(filings) >= limit:
                break
    return filings[:limit]


def efts_hits(client: SecClient, cusip: str, size: int) -> tuple[int, list[dict[str, object]]]:
    matches: list[dict[str, object]] = []
    total = 0
    for forms in (CURRENT_FORMS, LEGACY_FORMS):
        parameters = urllib.parse.urlencode(
            {"q": f'"{cusip}"', "forms": forms, "from": 0, "size": size}
        )
        result = client.json(
            f"https://efts.sec.gov/LATEST/search-index?{parameters}"
        )
        total += int(result["hits"]["total"]["value"])  # type: ignore[index]
        matches.extend(result["hits"]["hits"][:size])  # type: ignore[index]
    unique = {str(hit["_id"]): hit for hit in matches}
    ordered = sorted(
        unique.values(),
        key=lambda hit: str(hit["_source"].get("file_date", "")),  # type: ignore[index,union-attr]
        reverse=True,
    )
    return total, ordered


def resolve_hit_document(
    client: SecClient, hit: dict[str, object]
) -> tuple[str, bytes] | None:
    source = hit["_source"]  # type: ignore[index]
    accession, document = str(hit["_id"]).split(":", 1)
    ciks = source.get("ciks", [])  # type: ignore[union-attr]
    for cik in ciks[-1:]:
        url = filing_url(str(cik), accession, document)
        try:
            return url, client.get(url, attempts=1, timeout=3)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None


def write_csv(path: Path, fields: tuple[str, ...], records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def research_managers(
    client: SecClient, targets: list[dict[str, str]], per_target: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    filings_out: list[dict[str, object]] = []
    people_out: list[dict[str, object]] = []
    for position, target in enumerate(targets, start=1):
        try:
            filings = manager_filings(client, target["cik"], per_target)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            print(f"manager {target['cik']} failed: {error}", flush=True)
            continue
        for filing in filings:
            url = filing_url(
                target["cik"], str(filing["accessionNumber"]),
                str(filing["primaryDocument"]),
            )
            try:
                parsed = parse_schedule_xml(
                    client.get(url, attempts=1, timeout=5)
                )
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                parsed = None
            base = {
                "target_type": "MANAGER_CIK", "target_rank": target["rank"],
                "target_id": target["cik"], "target_name": target["institution_name"],
                "form": filing["form"], "accession_number": filing["accessionNumber"],
                "filing_date": filing["filingDate"],
                "filer_cik": parsed["filer_cik"] if parsed else "",
                "issuer_cik": parsed["issuer_cik"] if parsed else "",
                "issuer_name": parsed["issuer_name"] if parsed else "",
                "cusip": parsed["cusip"] if parsed else "", "document_url": url,
                "reporting_names": parsed["reporting_names"] if parsed else "",
                "search_result_count": len(filings),
                "extraction_status": (
                    "XML_PARSED_TARGET_REPORTER"
                    if parsed and parsed["filer_cik"] == target["cik"]
                    else "XML_PARSED_NOT_TARGET_REPORTER"
                    if parsed else "LEGACY_OR_UNPARSED"
                ),
            }
            filings_out.append(base)
            if parsed and parsed["filer_cik"] == target["cik"]:
                for person in parsed["people"]:  # type: ignore[union-attr]
                    people_out.append(
                        {
                            **{key: base[key] for key in (
                                "target_type", "target_rank", "target_id", "target_name",
                                "form", "accession_number", "filing_date", "issuer_cik",
                                "issuer_name", "cusip", "filer_cik", "document_url",
                            )},
                            **person,
                            "event_date": parsed["event_date"],
                            "relationship_basis": "individual reporting person in manager-CIK filing",
                            "extraction_method": "SEC_SCHEDULE_XML",
                            "review_status": "AUTO_EXTRACTED",
                        }
                    )
        if position % 25 == 0:
            print(f"manager targets: {position}/{len(targets)}", flush=True)
    return filings_out, people_out


def research_securities(
    client: SecClient, targets: list[dict[str, str]], per_target: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    filings_out: list[dict[str, object]] = []
    people_out: list[dict[str, object]] = []
    for position, target in enumerate(targets, start=1):
        try:
            total, hits = efts_hits(client, target["cusip"], per_target)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            print(f"security {target['cusip']} failed: {error}", flush=True)
            continue
        for hit in hits:
            source = hit["_source"]
            resolved = resolve_hit_document(client, hit)
            url, body = resolved if resolved else ("", b"")
            parsed = parse_schedule_xml(body) if body else None
            accession = source.get("adsh", str(hit["_id"]).split(":", 1)[0])
            base = {
                "target_type": "SECURITY_CUSIP", "target_rank": target["rank"],
                "target_id": target["cusip"], "target_name": target["issuer"],
                "form": source.get("form", ""), "accession_number": accession,
                "filing_date": source.get("file_date", ""),
                "filer_cik": parsed["filer_cik"] if parsed else "",
                "issuer_cik": parsed["issuer_cik"] if parsed else "",
                "issuer_name": parsed["issuer_name"] if parsed else target["issuer"],
                "cusip": parsed["cusip"] if parsed else target["cusip"],
                "reporting_names": (
                    parsed["reporting_names"] if parsed else
                    "; ".join(source.get("display_names", []))
                ),
                "document_url": url, "search_result_count": total,
                "extraction_status": "XML_PARSED" if parsed else "LEGACY_OR_UNPARSED",
            }
            filings_out.append(base)
            if parsed:
                for person in parsed["people"]:  # type: ignore[union-attr]
                    people_out.append(
                        {
                            **{key: base[key] for key in (
                                "target_type", "target_rank", "target_id", "target_name",
                                "form", "accession_number", "filing_date", "issuer_cik",
                                "issuer_name", "cusip", "filer_cik", "document_url",
                            )},
                            **person,
                            "event_date": parsed["event_date"],
                            "relationship_basis": "individual reporting person for target security",
                            "extraction_method": "SEC_SCHEDULE_XML",
                            "review_status": "AUTO_EXTRACTED",
                        }
                    )
        if position % 25 == 0:
            print(f"security targets: {position}/{len(targets)}", flush=True)
    return filings_out, people_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--per-target", type=int, default=3)
    parser.add_argument(
        "--target-limit", type=int,
        help="process only the first N rows from each target file",
    )
    parser.add_argument(
        "--user-agent", default=os.environ.get("SEC_USER_AGENT", ""),
        help="SEC-compliant user agent containing a contact email",
    )
    arguments = parser.parse_args()
    client = SecClient(arguments.user_agent, arguments.cache)
    managers = read_csv(arguments.targets / "top_200_managers.csv")
    securities = read_csv(arguments.targets / "top_200_securities.csv")
    if arguments.target_limit is not None:
        managers = managers[:arguments.target_limit]
        securities = securities[:arguments.target_limit]
    manager_filings_out, manager_people = research_managers(
        client, managers, arguments.per_target
    )
    security_filings_out, security_people = research_securities(
        client, securities, arguments.per_target
    )
    filings = manager_filings_out + security_filings_out
    people = manager_people + security_people
    write_csv(arguments.output / "filing_matches.csv", FILING_FIELDS, filings)
    write_csv(arguments.output / "people_candidates.csv", PEOPLE_FIELDS, people)
    print(f"Recorded {len(filings)} filing matches and {len(people)} people rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
