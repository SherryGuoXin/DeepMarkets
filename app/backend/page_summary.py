"""Factual page summaries built from the same analytical data as the product UI.

Activity classifications are consumed without reinterpretation.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote


SITE_URL = "https://13fdata.net"
SEC_SOURCE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
DATA_NOTE = (
    "13FData derives position changes from reported holdings between quarters; "
    "these are not observed transactions. Amendments, corporate actions, "
    "identifier changes and reporting delays can affect comparisons. "
    "For informational and analytical purposes only; not investment advice."
)


def _period(label: str) -> str:
    match = re.fullmatch(r"(\d{4})Q([1-4])", label)
    return f"Q{match[2]} {match[1]}" if match else label


def _previous_period(profile: dict[str, Any]) -> str | None:
    """Only describe a comparison when the immediately prior quarter exists."""
    if "previous_reporting_period" in profile:
        previous = profile["previous_reporting_period"]
        return _period(previous) if previous else None
    label = profile["snapshot"].get("quarter_label", "")
    match = re.fullmatch(r"(\d{4})Q([1-4])", label)
    if not match:
        return None
    year, quarter = int(match[1]), int(match[2])
    previous_label = f"{year}Q{quarter - 1}" if quarter > 1 else f"{year - 1}Q4"
    if any(item.get("quarter_label") == previous_label for item in profile.get("history", [])):
        return _period(previous_label)
    return None


def _money(value: int | float) -> str:
    for threshold, suffix in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(value) >= threshold:
            return f"${value / threshold:,.2f} {suffix}"
    return f"${value:,.0f}"


def _activity(profile: dict[str, Any], count_key: str) -> dict[str, int]:
    return {
        item["action"]: int(item[count_key])
        for item in profile.get("activity", [])
        if item.get(count_key) is not None
    }


def _link(label: str, url: str) -> dict[str, str]:
    return {"label": label, "url": url}


def _finish(
    profile: dict[str, Any], *, path: str, name: str, heading: str,
    section_heading: str, summary: str, description: str,
    links: list[dict[str, str]], basis: str, context_note: str | None = None,
    plain_summary: bool = False,
) -> dict[str, Any]:
    status = profile.get("quarter_status")
    partial = (status.get("status") if isinstance(status, dict) else status) == "PARTIAL"
    period = _period(profile["snapshot"]["quarter_label"])
    status_note = (
        f"{period} coverage is partial. Figures and comparisons may change as "
        "additional filings and amendments are processed."
        if partial else None
    )
    if plain_summary:
        status_note = None
    title = f"{heading} | 13FData"
    canonical_url = SITE_URL + path
    if partial:
        description += " Partial coverage."
    dataset_description = " ".join(filter(None, [summary, status_note, basis]))
    structured_data = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": description,
        "url": canonical_url,
        "isPartOf": {"@type": "WebSite", "name": "13FData", "url": SITE_URL},
        "about": {"@type": "Organization", "name": name},
        "mainEntity": {
            "@type": "Dataset",
            "name": f"{name} {period} reported Form 13F holdings analysis",
            "description": dataset_description,
            "url": canonical_url,
            "creator": {"@type": "Organization", "name": "13FData", "url": SITE_URL},
            "isBasedOn": {
                "@type": "Dataset",
                "name": "SEC Form 13F filings",
                "url": SEC_SOURCE,
                "creator": {
                    "@type": "Organization",
                    "name": "U.S. Securities and Exchange Commission",
                    "url": "https://www.sec.gov/",
                },
            },
        },
    }
    return {
        "heading": heading,
        "section_heading": section_heading,
        "summary": summary,
        "links": [] if plain_summary else [
            *links,
            _link("Methodology and data limitations", "/disclaimers"),
            _link("SEC Form 13F source data", SEC_SOURCE),
        ],
        "data_note": None if plain_summary else f"{basis} {DATA_NOTE}",
        "status_note": status_note,
        "context_note": context_note,
        "title": title,
        "description": description,
        "canonical_url": canonical_url,
        "structured_data": structured_data,
    }


def security_page_summary(cusip: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = profile.get("snapshot") or {}
    if not snapshot.get("quarter_label"):
        return None
    name = profile["identity"].get("issuer") or cusip
    period = _period(snapshot["quarter_label"])
    base = next((item for item in profile.get("instrument_breakdown", [])
                 if item.get("option_type") == "NONE"), None)
    if base is None and profile.get("instrument_breakdown"):
        base = {"institution_count": 0, "value_usd": 0}
    if base is None or base.get("institution_count") is None:
        return None
    count = int(base["institution_count"])
    latest_filing_date = profile.get("site_latest_filing_date")
    filed_through = ""
    if latest_filing_date:
        filed = date.fromisoformat(latest_filing_date)
        filed_through = f", filed through {filed:%B} {filed.day}, {filed.year}"
    latest = "latest " if profile.get("is_latest_reporting_period", True) else ""
    sentences = [
        f"For the {latest}{period} SEC Form 13F reporting period{filed_through}, "
        f"{name} ({cusip}) had non-option positions reported by {count:,} "
        "institutional investment managers"
        + (f", totaling approximately {_money(base['value_usd'])}."
           if base.get("value_usd") is not None else ".")
    ]
    previous = _previous_period(profile)
    activity = _activity(profile, "institution_count")
    if previous and any(action in activity for action in ("NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED")):
        sentences.append(
            f"Compared with {previous}, {activity.get('NEW', 0):,} managers "
            f"reported new positions, {activity.get('ADDED', 0):,} increased "
            f"their reported positions, {activity.get('REDUCED', 0):,} reduced "
            f"their reported positions, and {activity.get('EXITED', 0):,} no "
            "longer reported a position."
        )
    comparison_sentences = []
    comparison = profile.get("share_comparison") or {}
    if previous and comparison.get("total_share_change") is not None:
        change = comparison["total_share_change"]
        comparison_sentences.append(
            "The total reported institutional share count changed by "
            f"{change:+,} shares from the previous quarter."
        )
        increased = comparison.get("largest_increase")
        decreased = comparison.get("largest_decrease")
        if increased and decreased:
            comparison_sentences.append(
                f"{increased['institution_name']} (CIK {increased['cik']}) reported "
                "the largest quarter-over-quarter increase in reported shares, "
                f"at approximately {_share_amount(increased['share_change'])}, "
                f"while {decreased['institution_name']} (CIK {decreased['cik']}) "
                "reported the largest decrease, at approximately "
                f"{_share_amount(abs(decreased['share_change']))}."
            )
        elif increased:
            comparison_sentences.append(
                f"{increased['institution_name']} (CIK {increased['cik']}) reported "
                "the largest quarter-over-quarter increase in reported shares, "
                f"at approximately {_share_amount(increased['share_change'])}."
            )
        elif decreased:
            comparison_sentences.append(
                f"{decreased['institution_name']} (CIK {decreased['cik']}) reported "
                "the largest quarter-over-quarter decrease in reported shares, "
                f"at approximately {_share_amount(abs(decreased['share_change']))}."
            )
    paragraphs = [" ".join(sentences)]
    if comparison_sentences:
        paragraphs.append(" ".join(comparison_sentences))
    result = _finish(
        profile, path=f"/securities/{quote(cusip, safe='')}", name=name,
        heading=f"{name} Institutional Ownership & 13F Holders",
        section_heading=f"{name} Institutional Ownership Summary",
        summary=" ".join(paragraphs),
        description=f"{name} ({cusip}): {count:,} managers reported non-option holdings in {period}. Explore 13FData's SEC Form 13F analysis and reported share changes.",
        links=[], basis="", plain_summary=True,
    )
    result["paragraphs"] = paragraphs
    result["title"] = f"{name} ({cusip}) Institutional Ownership & 13F Holders | 13FData"
    result["structured_data"]["name"] = result["title"]
    return result


def _share_amount(value: int | float) -> str:
    for threshold, suffix in ((1_000_000_000, "billion"), (1_000_000, "million")):
        if value >= threshold:
            return f"{value / threshold:,.2f} {suffix} shares"
    return f"{value:,.0f} shares"


def institution_page_summary(cik: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = profile.get("snapshot") or {}
    facts = profile.get("non_option_summary") or {}
    if not snapshot.get("quarter_label") or any(
        facts.get(key) is None for key in ("holding_count", "portfolio_value")
    ):
        return None
    name = profile["identity"].get("institution_name") or cik
    period = _period(snapshot["quarter_label"])
    value = _money(facts["portfolio_value"])
    count = int(facts["holding_count"])
    filed_through = ""
    if profile.get("site_latest_filing_date"):
        filed = date.fromisoformat(profile["site_latest_filing_date"])
        filed_through = f", filed through {filed:%B} {filed.day}, {filed.year}"
    latest = "latest " if profile.get("is_latest_reporting_period", True) else ""
    sentences = [
        f"For the {latest}{period} SEC Form 13F reporting period{filed_through}, "
        f"{name} (CIK {cik}) reported {count:,} non-option "
        f"position{'s' if count != 1 else ''} with a total reported value "
        f"of approximately {value}."
    ]
    previous = _previous_period(profile)
    activity = _activity(facts, "position_count")
    if previous and any(action in activity for action in ("NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED")):
        new, added, reduced, exited = (
            activity.get(action, 0) for action in ("NEW", "ADDED", "REDUCED", "EXITED")
        )
        sentences.append(
            f"Compared with {previous}, the filing included "
            f"{new:,} new reported position{'s' if new != 1 else ''}, "
            f"{added:,} position increase{'s' if added != 1 else ''}, "
            f"{reduced:,} position reduction{'s' if reduced != 1 else ''}, and "
            f"{exited:,} reported exit{'s' if exited != 1 else ''}."
        )
    paragraphs = [" ".join(sentences)]
    highlights = []
    largest = facts.get("largest_position")
    if largest:
        highlights.append(
            f"{name}'s largest reported position was {largest['issuer']}, "
            f"valued at approximately {_money(largest['market_value_usd'])}."
        )
    increased = facts.get("largest_increase") if previous else None
    decreased = facts.get("largest_decrease") if previous else None
    if increased and decreased:
        highlights.append(
            "The largest quarter-over-quarter increase in reported position "
            f"value was {increased['issuer']} at approximately "
            f"{_money(increased['value_change_usd'])}, while {decreased['issuer']} "
            "recorded the largest decrease at approximately "
            f"{_money(abs(decreased['value_change_usd']))}."
        )
    elif increased:
        highlights.append(
            "The largest quarter-over-quarter increase in reported position "
            f"value was {increased['issuer']} at approximately "
            f"{_money(increased['value_change_usd'])}."
        )
    elif decreased:
        highlights.append(
            f"{decreased['issuer']} recorded the largest quarter-over-quarter "
            "decrease in reported position value at approximately "
            f"{_money(abs(decreased['value_change_usd']))}."
        )
    if highlights:
        paragraphs.append(" ".join(highlights))
    people = [person["name"] for person in profile.get("notable_people", [])
              if person.get("name")]
    if people:
        paragraphs.append(
            f"Notable people associated with {name} include {', '.join(people)}."
        )
    result = _finish(
        profile, path=f"/institutions/{quote(cik, safe='')}", name=name,
        heading=f"{name} {period} 13F Holdings & Portfolio",
        section_heading=f"{name} 13F Portfolio Summary",
        summary=" ".join(paragraphs),
        description=f"{name} (CIK {cik}) reported {count:,} non-option positions valued at approximately {value} in {period}. Explore its reported 13F holdings and position changes.",
        links=[], basis="", plain_summary=True,
    )
    result["paragraphs"] = paragraphs
    return result
