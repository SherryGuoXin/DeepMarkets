#!/usr/bin/env python3
"""Classify CUSIPs, build stable instruments, and materialize quarterly facts."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from .build_canonical_filings import execute_statements
except ImportError:  # Allow direct execution: python3 etl/build_instruments.py
    from build_canonical_filings import execute_statements


PROJECT_DIR = Path(__file__).resolve().parent.parent

SECURITY_TYPES = (
    (1, "COMMON_STOCK", "Common Stock", 1),
    (2, "ETF", "Exchange-Traded Fund", 1),
    (3, "ADR", "Depositary Receipt", 0),
    (4, "PREFERRED_STOCK", "Preferred Stock", 0),
    (5, "OPTION_CALL", "Call Option", 0),
    (6, "OPTION_PUT", "Put Option", 0),
    (7, "DEBT_BOND", "Debt or Principal Amount", 0),
    (8, "CONVERTIBLE", "Convertible Security", 0),
    (9, "FUND_OTHER", "Other Fund", 0),
    (99, "UNKNOWN", "Unknown", 0),
)

# Rules are intentionally conservative. Lower priority values run first.
SYSTEM_RULES = (
    (
        1,
        10,
        "TITLEOFCLASS",
        "REGEX",
        r"\b(ADR|ADS|DEPOSITARY|DEPOSITORY|N Y REGISTRY)\b",
        3,
        "Depositary-receipt terminology",
    ),
    (
        2,
        20,
        "TITLEOFCLASS",
        "REGEX",
        r"\b(PFD|PREFERRED|PREF SH|PREFERENCE)\b",
        4,
        "Preferred-security terminology",
    ),
    (
        3,
        30,
        "TITLEOFCLASS",
        "REGEX",
        r"\b(CONV|CONVERTIBLE|CVT)\b",
        8,
        "Convertible-security terminology",
    ),
    (
        4,
        40,
        "TITLEOFCLASS",
        "REGEX",
        r"\bETF\b|EXCHANGE[\s-]?TRADED|UIT EXCHANGE",
        2,
        "Explicit exchange-traded-fund terminology",
    ),
    (
        5,
        50,
        "NAMEOFISSUER",
        "REGEX",
        r"^(ISHARES|SPDR|PROSHARES|DIREXION|GLOBAL X|ARK ETF|"
        r"FIRST TR EXCHANGE|INVESCO EXCH|WISDOMTREE)",
        2,
        "Conservative ETF issuer-family rule",
    ),
    (
        6,
        60,
        "TITLEOFCLASS",
        "REGEX",
        r"^(FUND|CEF|MF CLOSED AND MF OPEN)$",
        9,
        "Explicit non-ETF fund terminology",
    ),
    (
        7,
        100,
        "TITLEOFCLASS",
        "REGEX",
        r"^(COM|COMMON|COMMON STOCKS?|COMMON SHARES?|COM NEW|CMN|STOCK|"
        r"COM CL [A-Z]|CL [A-Z] COM|CLASS [A-Z] COM|COM SHS|COM STK|"
        r"COMM STK|COMMON / ORDINARY STOCK|ORD|ORD SHS|ORDINARY SHARES|"
        r"COMMON EQUITY SHARES|EQUITY|EQUITIES|CS|SC|"
        r"CL [A-Z]( NEW)?|CAP STK CL [A-Z]|COM SER [A-Z]|REIT)$",
        1,
        "Common-equity terminology",
    ),
)

INSTRUMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS SECURITY_TYPE (
    SECURITY_TYPE_ID INTEGER PRIMARY KEY,
    SECURITY_TYPE_CODE TEXT NOT NULL UNIQUE,
    SECURITY_TYPE_NAME TEXT NOT NULL,
    INCLUDE_IN_CORE_HOLDINGS INTEGER NOT NULL
        CHECK (INCLUDE_IN_CORE_HOLDINGS IN (0, 1))
);

CREATE TABLE IF NOT EXISTS SECURITY_CLASS_RULE (
    RULE_ID INTEGER PRIMARY KEY,
    PRIORITY INTEGER NOT NULL,
    FIELD_NAME TEXT NOT NULL
        CHECK (FIELD_NAME IN ('TITLEOFCLASS', 'NAMEOFISSUER')),
    MATCH_TYPE TEXT NOT NULL
        CHECK (MATCH_TYPE IN ('EXACT', 'CONTAINS', 'REGEX')),
    MATCH_PATTERN TEXT NOT NULL,
    SECURITY_TYPE_ID INTEGER NOT NULL,
    SOURCE TEXT NOT NULL,
    DESCRIPTION TEXT,
    IS_ACTIVE INTEGER NOT NULL DEFAULT 1 CHECK (IS_ACTIVE IN (0, 1)),
    FOREIGN KEY (SECURITY_TYPE_ID)
        REFERENCES SECURITY_TYPE (SECURITY_TYPE_ID)
);

CREATE INDEX IF NOT EXISTS SECURITY_CLASS_RULE_PRIORITY_IDX
    ON SECURITY_CLASS_RULE (IS_ACTIVE, PRIORITY, RULE_ID);

CREATE TABLE IF NOT EXISTS CUSIP_SECURITY_TYPE_OVERRIDE (
    CUSIP_ID INTEGER PRIMARY KEY,
    SECURITY_TYPE_ID INTEGER NOT NULL,
    REASON TEXT NOT NULL,
    SOURCE TEXT NOT NULL,
    REVIEWED_AT TEXT NOT NULL,
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (SECURITY_TYPE_ID)
        REFERENCES SECURITY_TYPE (SECURITY_TYPE_ID)
);

CREATE TABLE IF NOT EXISTS CUSIP_CLASSIFICATION (
    CUSIP_ID INTEGER PRIMARY KEY,
    SECURITY_TYPE_ID INTEGER NOT NULL,
    CLASSIFICATION_METHOD TEXT NOT NULL
        CHECK (
            CLASSIFICATION_METHOD IN (
                'CUSIP_OVERRIDE', 'RULE_VOTE', 'UNKNOWN'
            )
        ),
    SELECTED_RULE_ID INTEGER,
    TOTAL_OCCURRENCE_COUNT INTEGER NOT NULL,
    MATCHED_OCCURRENCE_COUNT INTEGER NOT NULL,
    WINNING_OCCURRENCE_COUNT INTEGER NOT NULL,
    CLASSIFICATION_CONFIDENCE REAL NOT NULL,
    CLASSIFIED_AT TEXT NOT NULL,
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (SECURITY_TYPE_ID)
        REFERENCES SECURITY_TYPE (SECURITY_TYPE_ID),
    FOREIGN KEY (SELECTED_RULE_ID)
        REFERENCES SECURITY_CLASS_RULE (RULE_ID)
);

CREATE TABLE IF NOT EXISTS INSTRUMENT (
    INSTRUMENT_ID INTEGER PRIMARY KEY,
    CUSIP_ID INTEGER NOT NULL,
    SECURITY_TYPE_ID INTEGER NOT NULL,
    OPTION_TYPE TEXT NOT NULL
        CHECK (OPTION_TYPE IN ('NONE', 'CALL', 'PUT')),
    AMOUNT_TYPE TEXT NOT NULL
        CHECK (AMOUNT_TYPE IN ('SH', 'PRN', 'OTHER')),
    CLASSIFICATION_METHOD TEXT NOT NULL,
    IS_ACTIVE INTEGER NOT NULL DEFAULT 1 CHECK (IS_ACTIVE IN (0, 1)),
    UNIQUE (CUSIP_ID, SECURITY_TYPE_ID, OPTION_TYPE, AMOUNT_TYPE),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (SECURITY_TYPE_ID)
        REFERENCES SECURITY_TYPE (SECURITY_TYPE_ID)
);

CREATE INDEX IF NOT EXISTS INSTRUMENT_CUSIP_IDX
    ON INSTRUMENT (CUSIP_ID);

CREATE TABLE IF NOT EXISTS CIK_INSTRUMENT (
    CIK_INSTRUMENT_ID INTEGER PRIMARY KEY,
    MANAGER_CIK CHAR(10) NOT NULL,
    INSTRUMENT_ID INTEGER NOT NULL,
    FIRST_OBSERVED_QUARTER_ID INTEGER NOT NULL,
    LATEST_OBSERVED_QUARTER_ID INTEGER NOT NULL,
    IS_ACTIVE INTEGER NOT NULL DEFAULT 1 CHECK (IS_ACTIVE IN (0, 1)),
    UNIQUE (MANAGER_CIK, INSTRUMENT_ID),
    FOREIGN KEY (INSTRUMENT_ID)
        REFERENCES INSTRUMENT (INSTRUMENT_ID),
    FOREIGN KEY (FIRST_OBSERVED_QUARTER_ID)
        REFERENCES QUARTER (QUARTER_ID),
    FOREIGN KEY (LATEST_OBSERVED_QUARTER_ID)
        REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_MANAGER_IDX
    ON CIK_INSTRUMENT (MANAGER_CIK);

CREATE TABLE IF NOT EXISTS CIK_INSTRUMENT_QUARTER (
    CIK_INSTRUMENT_QUARTER_ID INTEGER PRIMARY KEY,
    CIK_INSTRUMENT_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    VALUE_USD INTEGER NOT NULL,
    REPORTED_AMOUNT INTEGER NOT NULL,
    AMOUNT_TYPE TEXT NOT NULL,
    PORTFOLIO_WEIGHT REAL,
    SOURCE_ROW_COUNT INTEGER NOT NULL,
    EFFECTIVE_ACCESSION_COUNT INTEGER NOT NULL,
    HAS_SHARED_DISCRETION INTEGER NOT NULL
        CHECK (HAS_SHARED_DISCRETION IN (0, 1)),
    HAS_CONFIDENTIAL_OMISSION INTEGER NOT NULL
        CHECK (HAS_CONFIDENTIAL_OMISSION IN (0, 1)),
    VALUE_QUALITY_STATUS TEXT NOT NULL
        CHECK (
            VALUE_QUALITY_STATUS IN (
                'OK', 'ROUNDING_DIFFERENCE', 'ISSUE'
            )
        ),
    UNIQUE (CIK_INSTRUMENT_ID, QUARTER_ID),
    FOREIGN KEY (CIK_INSTRUMENT_ID)
        REFERENCES CIK_INSTRUMENT (CIK_INSTRUMENT_ID) ON DELETE CASCADE,
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_QUARTER_PERIOD_IDX
    ON CIK_INSTRUMENT_QUARTER (QUARTER_ID);

CREATE TABLE IF NOT EXISTS CIK_INSTRUMENT_CHANGE (
    CIK_INSTRUMENT_CHANGE_ID INTEGER PRIMARY KEY,
    CIK_INSTRUMENT_ID INTEGER NOT NULL,
    FROM_QUARTER_ID INTEGER NOT NULL,
    TO_QUARTER_ID INTEGER NOT NULL,
    PRIOR_VALUE_USD INTEGER,
    CURRENT_VALUE_USD INTEGER,
    VALUE_CHANGE_USD INTEGER,
    PRIOR_REPORTED_AMOUNT INTEGER,
    CURRENT_REPORTED_AMOUNT INTEGER,
    AMOUNT_CHANGE INTEGER,
    AMOUNT_CHANGE_PERCENT REAL,
    ACTION TEXT NOT NULL
        CHECK (
            ACTION IN (
                'NEW', 'ADDED', 'REDUCED', 'EXITED',
                'UNCHANGED', 'UNKNOWN'
            )
        ),
    IS_COMPARABLE INTEGER NOT NULL CHECK (IS_COMPARABLE IN (0, 1)),
    NONCOMPARABLE_REASON TEXT,
    VALUE_QUALITY_STATUS TEXT NOT NULL,
    UNIQUE (CIK_INSTRUMENT_ID, FROM_QUARTER_ID, TO_QUARTER_ID),
    FOREIGN KEY (CIK_INSTRUMENT_ID)
        REFERENCES CIK_INSTRUMENT (CIK_INSTRUMENT_ID) ON DELETE CASCADE,
    FOREIGN KEY (FROM_QUARTER_ID) REFERENCES QUARTER (QUARTER_ID),
    FOREIGN KEY (TO_QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_CHANGE_TO_PERIOD_IDX
    ON CIK_INSTRUMENT_CHANGE (TO_QUARTER_ID, ACTION);

CREATE TABLE IF NOT EXISTS CIK_QUARTER_SUMMARY (
    CIK_QUARTER_SUMMARY_ID INTEGER PRIMARY KEY,
    MANAGER_CIK CHAR(10) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    PORTFOLIO_VALUE_USD INTEGER NOT NULL,
    INSTRUMENT_COUNT INTEGER NOT NULL,
    CUSIP_COUNT INTEGER NOT NULL,
    COMMON_STOCK_VALUE_USD INTEGER NOT NULL,
    ETF_VALUE_USD INTEGER NOT NULL,
    CALL_VALUE_USD INTEGER NOT NULL,
    PUT_VALUE_USD INTEGER NOT NULL,
    UNKNOWN_VALUE_USD INTEGER NOT NULL,
    LARGEST_INSTRUMENT_ID INTEGER,
    LARGEST_POSITION_VALUE_USD INTEGER,
    LARGEST_POSITION_WEIGHT REAL,
    TOP_10_WEIGHT REAL,
    HAS_SHARED_DISCRETION INTEGER NOT NULL,
    HAS_CONFIDENTIAL_OMISSION INTEGER NOT NULL,
    VALUE_QUALITY_STATUS TEXT NOT NULL,
    UNIQUE (MANAGER_CIK, QUARTER_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID),
    FOREIGN KEY (LARGEST_INSTRUMENT_ID)
        REFERENCES INSTRUMENT (INSTRUMENT_ID)
);

CREATE TABLE IF NOT EXISTS CUSIP_QUARTER_SUMMARY (
    CUSIP_QUARTER_SUMMARY_ID INTEGER PRIMARY KEY,
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    MANAGER_COUNT INTEGER NOT NULL,
    TOTAL_VALUE_USD INTEGER NOT NULL,
    COMMON_STOCK_VALUE_USD INTEGER NOT NULL,
    ETF_VALUE_USD INTEGER NOT NULL,
    CALL_VALUE_USD INTEGER NOT NULL,
    PUT_VALUE_USD INTEGER NOT NULL,
    UNKNOWN_VALUE_USD INTEGER NOT NULL,
    LARGEST_MANAGER_CIK CHAR(10),
    LARGEST_MANAGER_VALUE_USD INTEGER,
    MANAGER_CONCENTRATION_HHI REAL,
    HAS_SHARED_DISCRETION INTEGER NOT NULL,
    HAS_CONFIDENTIAL_OMISSION INTEGER NOT NULL,
    VALUE_QUALITY_STATUS TEXT NOT NULL,
    UNIQUE (CUSIP_ID, QUARTER_ID),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_QUARTER_SUMMARY_PERIOD_VALUE_IDX
    ON CIK_QUARTER_SUMMARY (QUARTER_ID, PORTFOLIO_VALUE_USD DESC);

CREATE INDEX IF NOT EXISTS CUSIP_QUARTER_SUMMARY_PERIOD_VALUE_IDX
    ON CUSIP_QUARTER_SUMMARY (QUARTER_ID, TOTAL_VALUE_USD DESC);

CREATE TABLE IF NOT EXISTS CIK_QUARTER_ACTIVITY (
    MANAGER_CIK CHAR(10) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    NEW_COUNT INTEGER NOT NULL,
    ADDED_COUNT INTEGER NOT NULL,
    REDUCED_COUNT INTEGER NOT NULL,
    EXITED_COUNT INTEGER NOT NULL,
    GROSS_BUY_VALUE_USD INTEGER NOT NULL,
    GROSS_SELL_VALUE_USD INTEGER NOT NULL,
    GROSS_VALUE_CHANGE_USD INTEGER NOT NULL,
    NET_VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (MANAGER_CIK, QUARTER_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_QUARTER_ACTIVITY_PERIOD_NET_IDX
    ON CIK_QUARTER_ACTIVITY (QUARTER_ID, NET_VALUE_CHANGE_USD DESC);

CREATE INDEX IF NOT EXISTS CIK_QUARTER_ACTIVITY_PERIOD_BUY_IDX
    ON CIK_QUARTER_ACTIVITY (QUARTER_ID, GROSS_BUY_VALUE_USD DESC);

CREATE INDEX IF NOT EXISTS CIK_QUARTER_ACTIVITY_PERIOD_SELL_IDX
    ON CIK_QUARTER_ACTIVITY (QUARTER_ID, GROSS_SELL_VALUE_USD DESC);

CREATE TABLE IF NOT EXISTS CIK_QUARTER_ACTION_ACTIVITY (
    MANAGER_CIK CHAR(10) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    ACTION TEXT NOT NULL,
    POSITION_COUNT INTEGER NOT NULL,
    POSITION_VALUE_USD INTEGER NOT NULL,
    AMOUNT_CHANGE INTEGER NOT NULL,
    VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (MANAGER_CIK, QUARTER_ID, ACTION),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CIK_QUARTER_ACTION_ACTIVITY_PERIOD_IDX
    ON CIK_QUARTER_ACTION_ACTIVITY (QUARTER_ID, ACTION);

CREATE TABLE IF NOT EXISTS CUSIP_QUARTER_ACTIVITY (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    NEW_INVESTOR_COUNT INTEGER NOT NULL,
    EXITED_INVESTOR_COUNT INTEGER NOT NULL,
    ADDED_HOLDER_COUNT INTEGER NOT NULL,
    REDUCED_HOLDER_COUNT INTEGER NOT NULL,
    NET_VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CUSIP_QUARTER_ACTIVITY_PERIOD_NET_IDX
    ON CUSIP_QUARTER_ACTIVITY (QUARTER_ID, NET_VALUE_CHANGE_USD DESC);

CREATE INDEX IF NOT EXISTS CUSIP_QUARTER_ACTIVITY_PERIOD_NEW_IDX
    ON CUSIP_QUARTER_ACTIVITY (QUARTER_ID, NEW_INVESTOR_COUNT DESC);

CREATE INDEX IF NOT EXISTS CUSIP_QUARTER_ACTIVITY_PERIOD_EXIT_IDX
    ON CUSIP_QUARTER_ACTIVITY (QUARTER_ID, EXITED_INVESTOR_COUNT DESC);

CREATE TABLE IF NOT EXISTS CUSIP_QUARTER_ACTION_ACTIVITY (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    ACTION TEXT NOT NULL,
    INSTITUTION_COUNT INTEGER NOT NULL,
    VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID, ACTION),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CUSIP_QUARTER_ACTION_ACTIVITY_PERIOD_IDX
    ON CUSIP_QUARTER_ACTION_ACTIVITY (QUARTER_ID, ACTION);

CREATE TABLE IF NOT EXISTS CUSIP_INSTRUMENT_QUARTER_SUMMARY (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    OPTION_TYPE TEXT NOT NULL
        CHECK (OPTION_TYPE IN ('NONE', 'CALL', 'PUT')),
    INSTITUTION_COUNT INTEGER NOT NULL,
    TOTAL_VALUE_USD INTEGER NOT NULL,
    REPORTED_AMOUNT INTEGER NOT NULL,
    AVERAGE_POSITION_VALUE_USD REAL,
    MANAGER_CONCENTRATION_HHI REAL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID, OPTION_TYPE),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CUSIP_INSTRUMENT_QUARTER_SUMMARY_PERIOD_IDX
    ON CUSIP_INSTRUMENT_QUARTER_SUMMARY (
        QUARTER_ID, OPTION_TYPE, TOTAL_VALUE_USD DESC
    );

CREATE TABLE IF NOT EXISTS CUSIP_BASE_QUARTER_ACTION_ACTIVITY (
    CUSIP_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    ACTION TEXT NOT NULL,
    INSTITUTION_COUNT INTEGER NOT NULL,
    VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (CUSIP_ID, QUARTER_ID, ACTION),
    FOREIGN KEY (CUSIP_ID) REFERENCES CUSIP (CUSIP_ID),
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS CUSIP_BASE_QUARTER_ACTION_PERIOD_IDX
    ON CUSIP_BASE_QUARTER_ACTION_ACTIVITY (QUARTER_ID, ACTION);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_MANAGER_INSTRUMENT_IDX
    ON CIK_INSTRUMENT (MANAGER_CIK, INSTRUMENT_ID, CIK_INSTRUMENT_ID);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_INSTRUMENT_MANAGER_IDX
    ON CIK_INSTRUMENT (INSTRUMENT_ID, MANAGER_CIK, CIK_INSTRUMENT_ID);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_QUARTER_PERIOD_REL_VALUE_IDX
    ON CIK_INSTRUMENT_QUARTER (
        QUARTER_ID, CIK_INSTRUMENT_ID, VALUE_USD DESC
    );

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_CHANGE_TO_REL_ACTION_IDX
    ON CIK_INSTRUMENT_CHANGE (TO_QUARTER_ID, CIK_INSTRUMENT_ID, ACTION);

CREATE INDEX IF NOT EXISTS CIK_INSTRUMENT_CHANGE_REL_TO_ACTION_IDX
    ON CIK_INSTRUMENT_CHANGE (CIK_INSTRUMENT_ID, TO_QUARTER_ID, ACTION);
"""

FACT_VIEWS = """
DROP VIEW IF EXISTS CIK_CUSIP_QUARTER;

CREATE VIEW CIK_CUSIP_QUARTER AS
SELECT
    R.MANAGER_CIK,
    I.CUSIP_ID,
    F.QUARTER_ID,
    SUM(F.VALUE_USD) AS VALUE_USD,
    COUNT(DISTINCT R.INSTRUMENT_ID) AS INSTRUMENT_COUNT,
    MAX(F.HAS_SHARED_DISCRETION) AS HAS_SHARED_DISCRETION,
    MAX(F.HAS_CONFIDENTIAL_OMISSION) AS HAS_CONFIDENTIAL_OMISSION,
    CASE MAX(
        CASE F.VALUE_QUALITY_STATUS
            WHEN 'ISSUE' THEN 2
            WHEN 'ROUNDING_DIFFERENCE' THEN 1
            ELSE 0
        END
    )
        WHEN 2 THEN 'ISSUE'
        WHEN 1 THEN 'ROUNDING_DIFFERENCE'
        ELSE 'OK'
    END AS VALUE_QUALITY_STATUS
FROM CIK_INSTRUMENT_QUARTER F
JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
JOIN INSTRUMENT I USING (INSTRUMENT_ID)
GROUP BY R.MANAGER_CIK, I.CUSIP_ID, F.QUARTER_ID;
"""


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").upper().split())


def seed_reference_data(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """
        INSERT INTO SECURITY_TYPE (
            SECURITY_TYPE_ID,
            SECURITY_TYPE_CODE,
            SECURITY_TYPE_NAME,
            INCLUDE_IN_CORE_HOLDINGS
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT (SECURITY_TYPE_ID) DO UPDATE SET
            SECURITY_TYPE_CODE = excluded.SECURITY_TYPE_CODE,
            SECURITY_TYPE_NAME = excluded.SECURITY_TYPE_NAME,
            INCLUDE_IN_CORE_HOLDINGS = excluded.INCLUDE_IN_CORE_HOLDINGS
        """,
        SECURITY_TYPES,
    )
    connection.executemany(
        """
        INSERT INTO SECURITY_CLASS_RULE (
            RULE_ID,
            PRIORITY,
            FIELD_NAME,
            MATCH_TYPE,
            MATCH_PATTERN,
            SECURITY_TYPE_ID,
            SOURCE,
            DESCRIPTION,
            IS_ACTIVE
        )
        VALUES (?, ?, ?, ?, ?, ?, 'SYSTEM', ?, 1)
        ON CONFLICT (RULE_ID) DO UPDATE SET
            PRIORITY = excluded.PRIORITY,
            FIELD_NAME = excluded.FIELD_NAME,
            MATCH_TYPE = excluded.MATCH_TYPE,
            MATCH_PATTERN = excluded.MATCH_PATTERN,
            SECURITY_TYPE_ID = excluded.SECURITY_TYPE_ID,
            SOURCE = excluded.SOURCE,
            DESCRIPTION = excluded.DESCRIPTION,
            IS_ACTIVE = 1
        """,
        SYSTEM_RULES,
    )


def load_rules(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rules = []
    for row in connection.execute(
        """
        SELECT
            RULE_ID,
            PRIORITY,
            FIELD_NAME,
            MATCH_TYPE,
            MATCH_PATTERN,
            SECURITY_TYPE_ID
        FROM SECURITY_CLASS_RULE
        WHERE IS_ACTIVE = 1
        ORDER BY PRIORITY, RULE_ID
        """
    ):
        rules.append(
            {
                "id": row[0],
                "priority": row[1],
                "field": row[2],
                "match_type": row[3],
                "pattern": row[4],
                "type_id": row[5],
                "regex": (
                    re.compile(row[4], re.IGNORECASE)
                    if row[3] == "REGEX"
                    else None
                ),
            }
        )
    return rules


def matching_rule(
    title: str, issuer: str, rules: list[dict[str, object]]
) -> dict[str, object] | None:
    values = {"TITLEOFCLASS": title, "NAMEOFISSUER": issuer}
    for rule in rules:
        value = values[str(rule["field"])]
        match_type = rule["match_type"]
        pattern = str(rule["pattern"])
        if match_type == "EXACT" and value == normalize_text(pattern):
            return rule
        if match_type == "CONTAINS" and normalize_text(pattern) in value:
            return rule
        if match_type == "REGEX" and rule["regex"].search(value):
            return rule
    return None


def classify_cusips(connection: sqlite3.Connection) -> dict[str, int]:
    rules = load_rules(connection)
    overrides = {
        row[0]: row[1]
        for row in connection.execute(
            """
            SELECT CUSIP_ID, SECURITY_TYPE_ID
            FROM CUSIP_SECURITY_TYPE_OVERRIDE
            """
        )
    }
    variants: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute(
        """
        SELECT
            CUSIP_ID,
            NAMEOFISSUER,
            TITLEOFCLASS,
            OCCURRENCE_COUNT
        FROM CUSIP_VARIANT
        """
    ):
        variants[int(row[0])].append(row)

    classified_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[object, ...]] = []
    method_counts: dict[str, int] = defaultdict(int)
    for cusip_id in (
        row[0] for row in connection.execute("SELECT CUSIP_ID FROM CUSIP")
    ):
        observations = variants.get(int(cusip_id), [])
        total = sum(int(row[3]) for row in observations)
        votes: dict[int, int] = defaultdict(int)
        rule_votes: dict[tuple[int, int], int] = defaultdict(int)
        for observation in observations:
            count = int(observation[3])
            rule = matching_rule(
                normalize_text(observation[2]),
                normalize_text(observation[1]),
                rules,
            )
            if rule:
                type_id = int(rule["type_id"])
                rule_id = int(rule["id"])
                votes[type_id] += count
                rule_votes[(type_id, rule_id)] += count

        if int(cusip_id) in overrides:
            selected_type = overrides[int(cusip_id)]
            method = "CUSIP_OVERRIDE"
            selected_rule = None
            winning = total
            matched = total
        elif votes:
            selected_type, winning = min(
                votes.items(), key=lambda item: (-item[1], item[0])
            )
            method = "RULE_VOTE"
            selected_rule = min(
                (
                    (rule_id, count)
                    for (type_id, rule_id), count in rule_votes.items()
                    if type_id == selected_type
                ),
                key=lambda item: (-item[1], item[0]),
            )[0]
            matched = sum(votes.values())
        else:
            selected_type = 99
            method = "UNKNOWN"
            selected_rule = None
            winning = 0
            matched = 0

        confidence = (winning / total) if total else 0.0
        rows.append(
            (
                cusip_id,
                selected_type,
                method,
                selected_rule,
                total,
                matched,
                winning,
                confidence,
                classified_at,
            )
        )
        method_counts[method] += 1

    connection.executemany(
        """
        INSERT INTO CUSIP_CLASSIFICATION (
            CUSIP_ID,
            SECURITY_TYPE_ID,
            CLASSIFICATION_METHOD,
            SELECTED_RULE_ID,
            TOTAL_OCCURRENCE_COUNT,
            MATCHED_OCCURRENCE_COUNT,
            WINNING_OCCURRENCE_COUNT,
            CLASSIFICATION_CONFIDENCE,
            CLASSIFIED_AT
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (CUSIP_ID) DO UPDATE SET
            SECURITY_TYPE_ID = excluded.SECURITY_TYPE_ID,
            CLASSIFICATION_METHOD = excluded.CLASSIFICATION_METHOD,
            SELECTED_RULE_ID = excluded.SELECTED_RULE_ID,
            TOTAL_OCCURRENCE_COUNT = excluded.TOTAL_OCCURRENCE_COUNT,
            MATCHED_OCCURRENCE_COUNT = excluded.MATCHED_OCCURRENCE_COUNT,
            WINNING_OCCURRENCE_COUNT = excluded.WINNING_OCCURRENCE_COUNT,
            CLASSIFICATION_CONFIDENCE = excluded.CLASSIFICATION_CONFIDENCE,
            CLASSIFIED_AT = excluded.CLASSIFIED_AT
        """,
        rows,
    )
    connection.execute(
        """
        DELETE FROM CUSIP_CLASSIFICATION
        WHERE CUSIP_ID NOT IN (SELECT CUSIP_ID FROM CUSIP)
        """
    )
    return dict(method_counts)


def sync_instruments(connection: sqlite3.Connection) -> None:
    desired = connection.execute(
        """
        SELECT DISTINCT
            H.CUSIP_ID,
            CASE
                WHEN UPPER(COALESCE(H.PUTCALL, '')) = 'CALL' THEN 5
                WHEN UPPER(COALESCE(H.PUTCALL, '')) = 'PUT' THEN 6
                WHEN UPPER(COALESCE(H.SSHPRNAMTTYPE, '')) = 'PRN' THEN 7
                ELSE C.SECURITY_TYPE_ID
            END AS SECURITY_TYPE_ID,
            CASE UPPER(COALESCE(H.PUTCALL, ''))
                WHEN 'CALL' THEN 'CALL'
                WHEN 'PUT' THEN 'PUT'
                ELSE 'NONE'
            END AS OPTION_TYPE,
            CASE UPPER(COALESCE(H.SSHPRNAMTTYPE, ''))
                WHEN 'SH' THEN 'SH'
                WHEN 'PRN' THEN 'PRN'
                ELSE 'OTHER'
            END AS AMOUNT_TYPE,
            CASE
                WHEN H.PUTCALL IS NOT NULL THEN 'PUTCALL'
                WHEN UPPER(COALESCE(H.SSHPRNAMTTYPE, '')) = 'PRN'
                    THEN 'AMOUNT_TYPE'
                ELSE C.CLASSIFICATION_METHOD
            END AS CLASSIFICATION_METHOD
        FROM ANALYTICS_HOLDING_LINE H
        JOIN CUSIP_CLASSIFICATION C USING (CUSIP_ID)
        """
    ).fetchall()
    connection.execute("UPDATE INSTRUMENT SET IS_ACTIVE = 0")
    connection.executemany(
        """
        INSERT INTO INSTRUMENT (
            CUSIP_ID,
            SECURITY_TYPE_ID,
            OPTION_TYPE,
            AMOUNT_TYPE,
            CLASSIFICATION_METHOD,
            IS_ACTIVE
        )
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT (
            CUSIP_ID, SECURITY_TYPE_ID, OPTION_TYPE, AMOUNT_TYPE
        ) DO UPDATE SET
            CLASSIFICATION_METHOD = excluded.CLASSIFICATION_METHOD,
            IS_ACTIVE = 1
        """,
        desired,
    )


def build_position_stage(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS temp.POSITION_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE POSITION_STAGE AS
        WITH CLASSIFIED AS (
            SELECT
                H.*,
                CASE
                    WHEN UPPER(COALESCE(H.PUTCALL, '')) = 'CALL' THEN 5
                    WHEN UPPER(COALESCE(H.PUTCALL, '')) = 'PUT' THEN 6
                    WHEN UPPER(COALESCE(H.SSHPRNAMTTYPE, '')) = 'PRN' THEN 7
                    ELSE C.SECURITY_TYPE_ID
                END AS SECURITY_TYPE_ID,
                CASE UPPER(COALESCE(H.PUTCALL, ''))
                    WHEN 'CALL' THEN 'CALL'
                    WHEN 'PUT' THEN 'PUT'
                    ELSE 'NONE'
                END AS OPTION_TYPE,
                CASE UPPER(COALESCE(H.SSHPRNAMTTYPE, ''))
                    WHEN 'SH' THEN 'SH'
                    WHEN 'PRN' THEN 'PRN'
                    ELSE 'OTHER'
                END AS AMOUNT_TYPE
            FROM ANALYTICS_HOLDING_LINE H
            JOIN CUSIP_CLASSIFICATION C USING (CUSIP_ID)
        ),
        AGGREGATED AS (
            SELECT
                C.MANAGER_CIK,
                I.INSTRUMENT_ID,
                I.CUSIP_ID,
                I.SECURITY_TYPE_ID,
                C.QUARTER_ID,
                SUM(C.VALUE_USD) AS VALUE_USD,
                SUM(C.SSHPRNAMT) AS REPORTED_AMOUNT,
                C.AMOUNT_TYPE,
                COUNT(*) AS SOURCE_ROW_COUNT,
                COUNT(DISTINCT C.ACCESSION_NUMBER)
                    AS EFFECTIVE_ACCESSION_COUNT,
                MAX(
                    C.OTHERMANAGER IS NOT NULL
                    OR UPPER(COALESCE(C.INVESTMENTDISCRETION, ''))
                       <> 'SOLE'
                ) AS HAS_SHARED_DISCRETION,
                MAX(C.HAS_CONFIDENTIAL_OMISSION)
                    AS HAS_CONFIDENTIAL_OMISSION,
                MAX(
                    CASE C.VALUE_RECONCILIATION_STATUS
                        WHEN 'MATCH' THEN 0
                        WHEN 'ROUNDING_DIFFERENCE' THEN 1
                        ELSE 2
                    END
                ) AS VALUE_QUALITY_LEVEL
            FROM CLASSIFIED C
            JOIN INSTRUMENT I
              ON I.CUSIP_ID = C.CUSIP_ID
             AND I.SECURITY_TYPE_ID = C.SECURITY_TYPE_ID
             AND I.OPTION_TYPE = C.OPTION_TYPE
             AND I.AMOUNT_TYPE = C.AMOUNT_TYPE
            GROUP BY
                C.MANAGER_CIK,
                I.INSTRUMENT_ID,
                I.CUSIP_ID,
                I.SECURITY_TYPE_ID,
                C.QUARTER_ID,
                C.AMOUNT_TYPE
        )
        SELECT
            A.*,
            CASE
                WHEN SUM(A.VALUE_USD) OVER (
                    PARTITION BY A.MANAGER_CIK, A.QUARTER_ID
                ) = 0 THEN NULL
                ELSE 1.0 * A.VALUE_USD / SUM(A.VALUE_USD) OVER (
                    PARTITION BY A.MANAGER_CIK, A.QUARTER_ID
                )
            END AS PORTFOLIO_WEIGHT,
            CASE A.VALUE_QUALITY_LEVEL
                WHEN 0 THEN 'OK'
                WHEN 1 THEN 'ROUNDING_DIFFERENCE'
                ELSE 'ISSUE'
            END AS VALUE_QUALITY_STATUS
        FROM AGGREGATED A
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX temp.POSITION_STAGE_UQ
        ON POSITION_STAGE (MANAGER_CIK, INSTRUMENT_ID, QUARTER_ID)
        """
    )


def sync_relationships_and_facts(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE CIK_INSTRUMENT SET IS_ACTIVE = 0")
    connection.execute(
        """
        INSERT INTO CIK_INSTRUMENT (
            MANAGER_CIK,
            INSTRUMENT_ID,
            FIRST_OBSERVED_QUARTER_ID,
            LATEST_OBSERVED_QUARTER_ID,
            IS_ACTIVE
        )
        SELECT
            MANAGER_CIK,
            INSTRUMENT_ID,
            MIN(QUARTER_ID),
            MAX(QUARTER_ID),
            1
        FROM POSITION_STAGE
        WHERE 1 = 1
        GROUP BY MANAGER_CIK, INSTRUMENT_ID
        ON CONFLICT (MANAGER_CIK, INSTRUMENT_ID) DO UPDATE SET
            FIRST_OBSERVED_QUARTER_ID =
                excluded.FIRST_OBSERVED_QUARTER_ID,
            LATEST_OBSERVED_QUARTER_ID =
                excluded.LATEST_OBSERVED_QUARTER_ID,
            IS_ACTIVE = 1
        """
    )
    connection.execute(
        """
        INSERT INTO CIK_INSTRUMENT_QUARTER (
            CIK_INSTRUMENT_ID,
            QUARTER_ID,
            VALUE_USD,
            REPORTED_AMOUNT,
            AMOUNT_TYPE,
            PORTFOLIO_WEIGHT,
            SOURCE_ROW_COUNT,
            EFFECTIVE_ACCESSION_COUNT,
            HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS
        )
        SELECT
            R.CIK_INSTRUMENT_ID,
            S.QUARTER_ID,
            S.VALUE_USD,
            S.REPORTED_AMOUNT,
            S.AMOUNT_TYPE,
            S.PORTFOLIO_WEIGHT,
            S.SOURCE_ROW_COUNT,
            S.EFFECTIVE_ACCESSION_COUNT,
            S.HAS_SHARED_DISCRETION,
            S.HAS_CONFIDENTIAL_OMISSION,
            S.VALUE_QUALITY_STATUS
        FROM POSITION_STAGE S
        JOIN CIK_INSTRUMENT R
          ON R.MANAGER_CIK = S.MANAGER_CIK
         AND R.INSTRUMENT_ID = S.INSTRUMENT_ID
        WHERE 1 = 1
        ON CONFLICT (CIK_INSTRUMENT_ID, QUARTER_ID) DO UPDATE SET
            VALUE_USD = excluded.VALUE_USD,
            REPORTED_AMOUNT = excluded.REPORTED_AMOUNT,
            AMOUNT_TYPE = excluded.AMOUNT_TYPE,
            PORTFOLIO_WEIGHT = excluded.PORTFOLIO_WEIGHT,
            SOURCE_ROW_COUNT = excluded.SOURCE_ROW_COUNT,
            EFFECTIVE_ACCESSION_COUNT =
                excluded.EFFECTIVE_ACCESSION_COUNT,
            HAS_SHARED_DISCRETION = excluded.HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION =
                excluded.HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS = excluded.VALUE_QUALITY_STATUS
        """
    )
    connection.execute(
        """
        DELETE FROM CIK_INSTRUMENT_QUARTER
        WHERE NOT EXISTS (
            SELECT 1
            FROM POSITION_STAGE S
            JOIN CIK_INSTRUMENT R
              ON R.MANAGER_CIK = S.MANAGER_CIK
             AND R.INSTRUMENT_ID = S.INSTRUMENT_ID
            WHERE R.CIK_INSTRUMENT_ID =
                      CIK_INSTRUMENT_QUARTER.CIK_INSTRUMENT_ID
              AND S.QUARTER_ID = CIK_INSTRUMENT_QUARTER.QUARTER_ID
        )
        """
    )


def build_change_stage(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS temp.CHANGE_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE CHANGE_STAGE AS
        WITH MANAGER_PERIOD_PAIR AS (
            SELECT
                C.MANAGER_CIK,
                Q.PREVIOUS_QUARTER_ID AS FROM_QUARTER_ID,
                C.QUARTER_ID AS TO_QUARTER_ID,
                MAX(
                    C.HAS_CONFIDENTIAL_OMISSION,
                    P.HAS_CONFIDENTIAL_OMISSION
                ) AS HAS_CONFIDENTIAL_OMISSION
            FROM CIK_QUARTER_SUMMARY C
            JOIN QUARTER Q USING (QUARTER_ID)
            JOIN CIK_QUARTER_SUMMARY P
              ON P.MANAGER_CIK = C.MANAGER_CIK
             AND P.QUARTER_ID = Q.PREVIOUS_QUARTER_ID
        ),
        PAIR_INSTRUMENT AS (
            SELECT
                M.MANAGER_CIK,
                M.FROM_QUARTER_ID,
                M.TO_QUARTER_ID,
                M.HAS_CONFIDENTIAL_OMISSION,
                R.CIK_INSTRUMENT_ID
            FROM MANAGER_PERIOD_PAIR M
            JOIN CIK_INSTRUMENT R
              ON R.MANAGER_CIK = M.MANAGER_CIK
            JOIN CIK_INSTRUMENT_QUARTER F
              ON F.CIK_INSTRUMENT_ID = R.CIK_INSTRUMENT_ID
             AND F.QUARTER_ID = M.FROM_QUARTER_ID
            UNION
            SELECT
                M.MANAGER_CIK,
                M.FROM_QUARTER_ID,
                M.TO_QUARTER_ID,
                M.HAS_CONFIDENTIAL_OMISSION,
                R.CIK_INSTRUMENT_ID
            FROM MANAGER_PERIOD_PAIR M
            JOIN CIK_INSTRUMENT R
              ON R.MANAGER_CIK = M.MANAGER_CIK
            JOIN CIK_INSTRUMENT_QUARTER F
              ON F.CIK_INSTRUMENT_ID = R.CIK_INSTRUMENT_ID
             AND F.QUARTER_ID = M.TO_QUARTER_ID
        )
        SELECT
            K.CIK_INSTRUMENT_ID,
            K.FROM_QUARTER_ID,
            K.TO_QUARTER_ID,
            P.VALUE_USD AS PRIOR_VALUE_USD,
            C.VALUE_USD AS CURRENT_VALUE_USD,
            COALESCE(C.VALUE_USD, 0) - COALESCE(P.VALUE_USD, 0)
                AS VALUE_CHANGE_USD,
            P.REPORTED_AMOUNT AS PRIOR_REPORTED_AMOUNT,
            C.REPORTED_AMOUNT AS CURRENT_REPORTED_AMOUNT,
            COALESCE(C.REPORTED_AMOUNT, 0) - COALESCE(P.REPORTED_AMOUNT, 0)
                AS AMOUNT_CHANGE,
            CASE
                WHEN P.REPORTED_AMOUNT IS NULL OR P.REPORTED_AMOUNT = 0
                    THEN NULL
                ELSE 1.0 * (
                    COALESCE(C.REPORTED_AMOUNT, 0) - P.REPORTED_AMOUNT
                ) / P.REPORTED_AMOUNT
            END AS AMOUNT_CHANGE_PERCENT,
            CASE
                WHEN K.HAS_CONFIDENTIAL_OMISSION = 1 THEN 'UNKNOWN'
                WHEN P.CIK_INSTRUMENT_QUARTER_ID IS NULL THEN 'NEW'
                WHEN C.CIK_INSTRUMENT_QUARTER_ID IS NULL THEN 'EXITED'
                WHEN C.REPORTED_AMOUNT > P.REPORTED_AMOUNT THEN 'ADDED'
                WHEN C.REPORTED_AMOUNT < P.REPORTED_AMOUNT THEN 'REDUCED'
                ELSE 'UNCHANGED'
            END AS ACTION,
            CASE WHEN K.HAS_CONFIDENTIAL_OMISSION = 1 THEN 0 ELSE 1 END
                AS IS_COMPARABLE,
            CASE
                WHEN K.HAS_CONFIDENTIAL_OMISSION = 1
                    THEN 'CONFIDENTIAL_OMISSION'
                ELSE NULL
            END AS NONCOMPARABLE_REASON,
            CASE MAX(
                CASE COALESCE(P.VALUE_QUALITY_STATUS, 'OK')
                    WHEN 'ISSUE' THEN 2
                    WHEN 'ROUNDING_DIFFERENCE' THEN 1
                    ELSE 0
                END,
                CASE COALESCE(C.VALUE_QUALITY_STATUS, 'OK')
                    WHEN 'ISSUE' THEN 2
                    WHEN 'ROUNDING_DIFFERENCE' THEN 1
                    ELSE 0
                END
            )
                WHEN 2 THEN 'ISSUE'
                WHEN 1 THEN 'ROUNDING_DIFFERENCE'
                ELSE 'OK'
            END AS VALUE_QUALITY_STATUS
        FROM PAIR_INSTRUMENT K
        LEFT JOIN CIK_INSTRUMENT_QUARTER P
          ON P.CIK_INSTRUMENT_ID = K.CIK_INSTRUMENT_ID
         AND P.QUARTER_ID = K.FROM_QUARTER_ID
        LEFT JOIN CIK_INSTRUMENT_QUARTER C
          ON C.CIK_INSTRUMENT_ID = K.CIK_INSTRUMENT_ID
         AND C.QUARTER_ID = K.TO_QUARTER_ID
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX temp.CHANGE_STAGE_UQ
        ON CHANGE_STAGE (
            CIK_INSTRUMENT_ID, FROM_QUARTER_ID, TO_QUARTER_ID
        )
        """
    )


def sync_changes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO CIK_INSTRUMENT_CHANGE (
            CIK_INSTRUMENT_ID,
            FROM_QUARTER_ID,
            TO_QUARTER_ID,
            PRIOR_VALUE_USD,
            CURRENT_VALUE_USD,
            VALUE_CHANGE_USD,
            PRIOR_REPORTED_AMOUNT,
            CURRENT_REPORTED_AMOUNT,
            AMOUNT_CHANGE,
            AMOUNT_CHANGE_PERCENT,
            ACTION,
            IS_COMPARABLE,
            NONCOMPARABLE_REASON,
            VALUE_QUALITY_STATUS
        )
        SELECT * FROM CHANGE_STAGE
        WHERE 1 = 1
        ON CONFLICT (
            CIK_INSTRUMENT_ID, FROM_QUARTER_ID, TO_QUARTER_ID
        ) DO UPDATE SET
            PRIOR_VALUE_USD = excluded.PRIOR_VALUE_USD,
            CURRENT_VALUE_USD = excluded.CURRENT_VALUE_USD,
            VALUE_CHANGE_USD = excluded.VALUE_CHANGE_USD,
            PRIOR_REPORTED_AMOUNT = excluded.PRIOR_REPORTED_AMOUNT,
            CURRENT_REPORTED_AMOUNT = excluded.CURRENT_REPORTED_AMOUNT,
            AMOUNT_CHANGE = excluded.AMOUNT_CHANGE,
            AMOUNT_CHANGE_PERCENT = excluded.AMOUNT_CHANGE_PERCENT,
            ACTION = excluded.ACTION,
            IS_COMPARABLE = excluded.IS_COMPARABLE,
            NONCOMPARABLE_REASON = excluded.NONCOMPARABLE_REASON,
            VALUE_QUALITY_STATUS = excluded.VALUE_QUALITY_STATUS
        """
    )
    connection.execute(
        """
        DELETE FROM CIK_INSTRUMENT_CHANGE
        WHERE NOT EXISTS (
            SELECT 1 FROM CHANGE_STAGE S
            WHERE S.CIK_INSTRUMENT_ID =
                      CIK_INSTRUMENT_CHANGE.CIK_INSTRUMENT_ID
              AND S.FROM_QUARTER_ID =
                      CIK_INSTRUMENT_CHANGE.FROM_QUARTER_ID
              AND S.TO_QUARTER_ID =
                      CIK_INSTRUMENT_CHANGE.TO_QUARTER_ID
        )
        """
    )


def sync_api_activity_summaries(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM CIK_QUARTER_ACTIVITY")
    connection.execute(
        """
        INSERT INTO CIK_QUARTER_ACTIVITY (
            MANAGER_CIK,
            QUARTER_ID,
            NEW_COUNT,
            ADDED_COUNT,
            REDUCED_COUNT,
            EXITED_COUNT,
            GROSS_BUY_VALUE_USD,
            GROSS_SELL_VALUE_USD,
            GROSS_VALUE_CHANGE_USD,
            NET_VALUE_CHANGE_USD
        )
        SELECT
            R.MANAGER_CIK,
            X.TO_QUARTER_ID,
            COUNT(*) FILTER (WHERE X.ACTION = 'NEW') AS NEW_COUNT,
            COUNT(*) FILTER (WHERE X.ACTION = 'ADDED') AS ADDED_COUNT,
            COUNT(*) FILTER (WHERE X.ACTION = 'REDUCED') AS REDUCED_COUNT,
            COUNT(*) FILTER (WHERE X.ACTION = 'EXITED') AS EXITED_COUNT,
            SUM(CASE
                WHEN X.ACTION IN ('NEW', 'ADDED')
                    THEN COALESCE(X.VALUE_CHANGE_USD, X.CURRENT_VALUE_USD, 0)
                ELSE 0
            END) AS GROSS_BUY_VALUE_USD,
            SUM(CASE
                WHEN X.ACTION IN ('REDUCED', 'EXITED')
                    THEN ABS(COALESCE(X.VALUE_CHANGE_USD, X.PRIOR_VALUE_USD, 0))
                ELSE 0
            END) AS GROSS_SELL_VALUE_USD,
            SUM(CASE WHEN X.IS_COMPARABLE = 1
                THEN ABS(COALESCE(X.VALUE_CHANGE_USD, 0)) ELSE 0 END)
                AS GROSS_VALUE_CHANGE_USD,
            SUM(CASE WHEN X.IS_COMPARABLE = 1
                THEN COALESCE(X.VALUE_CHANGE_USD, 0) ELSE 0 END)
                AS NET_VALUE_CHANGE_USD
        FROM CIK_INSTRUMENT_CHANGE X
        JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
        GROUP BY R.MANAGER_CIK, X.TO_QUARTER_ID
        """
    )

    connection.execute("DELETE FROM CIK_QUARTER_ACTION_ACTIVITY")
    connection.execute(
        """
        INSERT INTO CIK_QUARTER_ACTION_ACTIVITY (
            MANAGER_CIK,
            QUARTER_ID,
            ACTION,
            POSITION_COUNT,
            POSITION_VALUE_USD,
            AMOUNT_CHANGE,
            VALUE_CHANGE_USD
        )
        SELECT
            R.MANAGER_CIK,
            X.TO_QUARTER_ID,
            X.ACTION,
            COUNT(*) AS POSITION_COUNT,
            SUM(COALESCE(X.CURRENT_VALUE_USD, X.PRIOR_VALUE_USD, 0))
                AS POSITION_VALUE_USD,
            SUM(COALESCE(X.AMOUNT_CHANGE, 0)) AS AMOUNT_CHANGE,
            SUM(COALESCE(X.VALUE_CHANGE_USD, 0)) AS VALUE_CHANGE_USD
        FROM CIK_INSTRUMENT_CHANGE X
        JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
        GROUP BY R.MANAGER_CIK, X.TO_QUARTER_ID, X.ACTION
        """
    )

    connection.execute("DELETE FROM CUSIP_QUARTER_ACTIVITY")
    connection.execute(
        """
        INSERT INTO CUSIP_QUARTER_ACTIVITY (
            CUSIP_ID,
            QUARTER_ID,
            NEW_INVESTOR_COUNT,
            EXITED_INVESTOR_COUNT,
            ADDED_HOLDER_COUNT,
            REDUCED_HOLDER_COUNT,
            NET_VALUE_CHANGE_USD
        )
        SELECT
            I.CUSIP_ID,
            X.TO_QUARTER_ID,
            COUNT(DISTINCT CASE WHEN X.ACTION = 'NEW'
                THEN R.MANAGER_CIK END) AS NEW_INVESTOR_COUNT,
            COUNT(DISTINCT CASE WHEN X.ACTION = 'EXITED'
                THEN R.MANAGER_CIK END) AS EXITED_INVESTOR_COUNT,
            COUNT(DISTINCT CASE WHEN X.ACTION = 'ADDED'
                THEN R.MANAGER_CIK END) AS ADDED_HOLDER_COUNT,
            COUNT(DISTINCT CASE WHEN X.ACTION = 'REDUCED'
                THEN R.MANAGER_CIK END) AS REDUCED_HOLDER_COUNT,
            SUM(CASE WHEN X.IS_COMPARABLE = 1
                THEN COALESCE(X.VALUE_CHANGE_USD, 0) ELSE 0 END)
                AS NET_VALUE_CHANGE_USD
        FROM CIK_INSTRUMENT_CHANGE X
        JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
        JOIN INSTRUMENT I USING (INSTRUMENT_ID)
        GROUP BY I.CUSIP_ID, X.TO_QUARTER_ID
        """
    )

    connection.execute("DELETE FROM CUSIP_QUARTER_ACTION_ACTIVITY")
    connection.execute(
        """
        INSERT INTO CUSIP_QUARTER_ACTION_ACTIVITY (
            CUSIP_ID,
            QUARTER_ID,
            ACTION,
            INSTITUTION_COUNT,
            VALUE_CHANGE_USD
        )
        SELECT
            I.CUSIP_ID,
            X.TO_QUARTER_ID,
            X.ACTION,
            COUNT(DISTINCT R.MANAGER_CIK) AS INSTITUTION_COUNT,
            SUM(COALESCE(X.VALUE_CHANGE_USD, 0)) AS VALUE_CHANGE_USD
        FROM CIK_INSTRUMENT_CHANGE X
        JOIN CIK_INSTRUMENT R USING (CIK_INSTRUMENT_ID)
        JOIN INSTRUMENT I USING (INSTRUMENT_ID)
        GROUP BY I.CUSIP_ID, X.TO_QUARTER_ID, X.ACTION
        """
    )

def build_manager_summary_stage(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS temp.CIK_SUMMARY_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE CIK_SUMMARY_STAGE AS
        WITH RANKED AS (
            SELECT
                S.*,
                ROW_NUMBER() OVER (
                    PARTITION BY S.MANAGER_CIK, S.QUARTER_ID
                    ORDER BY S.VALUE_USD DESC, S.INSTRUMENT_ID
                ) AS VALUE_RANK
            FROM POSITION_STAGE S
        )
        SELECT
            MANAGER_CIK,
            QUARTER_ID,
            SUM(VALUE_USD) AS PORTFOLIO_VALUE_USD,
            COUNT(*) AS INSTRUMENT_COUNT,
            COUNT(DISTINCT CUSIP_ID) AS CUSIP_COUNT,
            SUM(CASE WHEN SECURITY_TYPE_ID = 1 THEN VALUE_USD ELSE 0 END)
                AS COMMON_STOCK_VALUE_USD,
            SUM(CASE WHEN SECURITY_TYPE_ID = 2 THEN VALUE_USD ELSE 0 END)
                AS ETF_VALUE_USD,
            SUM(CASE WHEN SECURITY_TYPE_ID = 5 THEN VALUE_USD ELSE 0 END)
                AS CALL_VALUE_USD,
            SUM(CASE WHEN SECURITY_TYPE_ID = 6 THEN VALUE_USD ELSE 0 END)
                AS PUT_VALUE_USD,
            SUM(CASE WHEN SECURITY_TYPE_ID = 99 THEN VALUE_USD ELSE 0 END)
                AS UNKNOWN_VALUE_USD,
            MAX(CASE WHEN VALUE_RANK = 1 THEN INSTRUMENT_ID END)
                AS LARGEST_INSTRUMENT_ID,
            MAX(CASE WHEN VALUE_RANK = 1 THEN VALUE_USD END)
                AS LARGEST_POSITION_VALUE_USD,
            MAX(CASE WHEN VALUE_RANK = 1 THEN PORTFOLIO_WEIGHT END)
                AS LARGEST_POSITION_WEIGHT,
            SUM(CASE WHEN VALUE_RANK <= 10 THEN PORTFOLIO_WEIGHT ELSE 0 END)
                AS TOP_10_WEIGHT,
            MAX(HAS_SHARED_DISCRETION) AS HAS_SHARED_DISCRETION,
            MAX(HAS_CONFIDENTIAL_OMISSION) AS HAS_CONFIDENTIAL_OMISSION,
            CASE MAX(VALUE_QUALITY_LEVEL)
                WHEN 0 THEN 'OK'
                WHEN 1 THEN 'ROUNDING_DIFFERENCE'
                ELSE 'ISSUE'
            END AS VALUE_QUALITY_STATUS
        FROM RANKED
        GROUP BY MANAGER_CIK, QUARTER_ID
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX temp.CIK_SUMMARY_STAGE_UQ
        ON CIK_SUMMARY_STAGE (MANAGER_CIK, QUARTER_ID)
        """
    )


def sync_manager_summaries(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO CIK_QUARTER_SUMMARY (
            MANAGER_CIK,
            QUARTER_ID,
            PORTFOLIO_VALUE_USD,
            INSTRUMENT_COUNT,
            CUSIP_COUNT,
            COMMON_STOCK_VALUE_USD,
            ETF_VALUE_USD,
            CALL_VALUE_USD,
            PUT_VALUE_USD,
            UNKNOWN_VALUE_USD,
            LARGEST_INSTRUMENT_ID,
            LARGEST_POSITION_VALUE_USD,
            LARGEST_POSITION_WEIGHT,
            TOP_10_WEIGHT,
            HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS
        )
        SELECT * FROM CIK_SUMMARY_STAGE
        WHERE 1 = 1
        ON CONFLICT (MANAGER_CIK, QUARTER_ID) DO UPDATE SET
            PORTFOLIO_VALUE_USD = excluded.PORTFOLIO_VALUE_USD,
            INSTRUMENT_COUNT = excluded.INSTRUMENT_COUNT,
            CUSIP_COUNT = excluded.CUSIP_COUNT,
            COMMON_STOCK_VALUE_USD = excluded.COMMON_STOCK_VALUE_USD,
            ETF_VALUE_USD = excluded.ETF_VALUE_USD,
            CALL_VALUE_USD = excluded.CALL_VALUE_USD,
            PUT_VALUE_USD = excluded.PUT_VALUE_USD,
            UNKNOWN_VALUE_USD = excluded.UNKNOWN_VALUE_USD,
            LARGEST_INSTRUMENT_ID = excluded.LARGEST_INSTRUMENT_ID,
            LARGEST_POSITION_VALUE_USD =
                excluded.LARGEST_POSITION_VALUE_USD,
            LARGEST_POSITION_WEIGHT = excluded.LARGEST_POSITION_WEIGHT,
            TOP_10_WEIGHT = excluded.TOP_10_WEIGHT,
            HAS_SHARED_DISCRETION = excluded.HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION =
                excluded.HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS = excluded.VALUE_QUALITY_STATUS
        """
    )
    connection.execute(
        """
        DELETE FROM CIK_QUARTER_SUMMARY
        WHERE NOT EXISTS (
            SELECT 1 FROM CIK_SUMMARY_STAGE S
            WHERE S.MANAGER_CIK = CIK_QUARTER_SUMMARY.MANAGER_CIK
              AND S.QUARTER_ID = CIK_QUARTER_SUMMARY.QUARTER_ID
        )
        """
    )


def build_cusip_summary_stage(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS temp.CUSIP_SUMMARY_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE CUSIP_SUMMARY_STAGE AS
        WITH MANAGER_CUSIP AS (
            SELECT
                CUSIP_ID,
                QUARTER_ID,
                MANAGER_CIK,
                SUM(VALUE_USD) AS MANAGER_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE_ID = 1 THEN VALUE_USD ELSE 0 END)
                    AS COMMON_STOCK_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE_ID = 2 THEN VALUE_USD ELSE 0 END)
                    AS ETF_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE_ID = 5 THEN VALUE_USD ELSE 0 END)
                    AS CALL_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE_ID = 6 THEN VALUE_USD ELSE 0 END)
                    AS PUT_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE_ID = 99 THEN VALUE_USD ELSE 0 END)
                    AS UNKNOWN_VALUE_USD,
                MAX(HAS_SHARED_DISCRETION) AS HAS_SHARED_DISCRETION,
                MAX(HAS_CONFIDENTIAL_OMISSION) AS HAS_CONFIDENTIAL_OMISSION,
                MAX(VALUE_QUALITY_LEVEL) AS VALUE_QUALITY_LEVEL
            FROM POSITION_STAGE
            GROUP BY CUSIP_ID, QUARTER_ID, MANAGER_CIK
        ),
        RANKED AS (
            SELECT
                M.*,
                SUM(MANAGER_VALUE_USD) OVER (
                    PARTITION BY CUSIP_ID, QUARTER_ID
                ) AS TOTAL_VALUE_USD,
                ROW_NUMBER() OVER (
                    PARTITION BY CUSIP_ID, QUARTER_ID
                    ORDER BY MANAGER_VALUE_USD DESC, MANAGER_CIK
                ) AS MANAGER_RANK
            FROM MANAGER_CUSIP M
        )
        SELECT
            CUSIP_ID,
            QUARTER_ID,
            COUNT(*) AS MANAGER_COUNT,
            MAX(TOTAL_VALUE_USD) AS TOTAL_VALUE_USD,
            SUM(COMMON_STOCK_VALUE_USD) AS COMMON_STOCK_VALUE_USD,
            SUM(ETF_VALUE_USD) AS ETF_VALUE_USD,
            SUM(CALL_VALUE_USD) AS CALL_VALUE_USD,
            SUM(PUT_VALUE_USD) AS PUT_VALUE_USD,
            SUM(UNKNOWN_VALUE_USD) AS UNKNOWN_VALUE_USD,
            MAX(CASE WHEN MANAGER_RANK = 1 THEN MANAGER_CIK END)
                AS LARGEST_MANAGER_CIK,
            MAX(CASE WHEN MANAGER_RANK = 1 THEN MANAGER_VALUE_USD END)
                AS LARGEST_MANAGER_VALUE_USD,
            CASE
                WHEN MAX(TOTAL_VALUE_USD) = 0 THEN NULL
                ELSE SUM(
                    (1.0 * MANAGER_VALUE_USD / TOTAL_VALUE_USD)
                    * (1.0 * MANAGER_VALUE_USD / TOTAL_VALUE_USD)
                )
            END AS MANAGER_CONCENTRATION_HHI,
            MAX(HAS_SHARED_DISCRETION) AS HAS_SHARED_DISCRETION,
            MAX(HAS_CONFIDENTIAL_OMISSION) AS HAS_CONFIDENTIAL_OMISSION,
            CASE MAX(VALUE_QUALITY_LEVEL)
                WHEN 0 THEN 'OK'
                WHEN 1 THEN 'ROUNDING_DIFFERENCE'
                ELSE 'ISSUE'
            END AS VALUE_QUALITY_STATUS
        FROM RANKED
        GROUP BY CUSIP_ID, QUARTER_ID
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX temp.CUSIP_SUMMARY_STAGE_UQ
        ON CUSIP_SUMMARY_STAGE (CUSIP_ID, QUARTER_ID)
        """
    )


def sync_cusip_summaries(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO CUSIP_QUARTER_SUMMARY (
            CUSIP_ID,
            QUARTER_ID,
            MANAGER_COUNT,
            TOTAL_VALUE_USD,
            COMMON_STOCK_VALUE_USD,
            ETF_VALUE_USD,
            CALL_VALUE_USD,
            PUT_VALUE_USD,
            UNKNOWN_VALUE_USD,
            LARGEST_MANAGER_CIK,
            LARGEST_MANAGER_VALUE_USD,
            MANAGER_CONCENTRATION_HHI,
            HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS
        )
        SELECT * FROM CUSIP_SUMMARY_STAGE
        WHERE 1 = 1
        ON CONFLICT (CUSIP_ID, QUARTER_ID) DO UPDATE SET
            MANAGER_COUNT = excluded.MANAGER_COUNT,
            TOTAL_VALUE_USD = excluded.TOTAL_VALUE_USD,
            COMMON_STOCK_VALUE_USD = excluded.COMMON_STOCK_VALUE_USD,
            ETF_VALUE_USD = excluded.ETF_VALUE_USD,
            CALL_VALUE_USD = excluded.CALL_VALUE_USD,
            PUT_VALUE_USD = excluded.PUT_VALUE_USD,
            UNKNOWN_VALUE_USD = excluded.UNKNOWN_VALUE_USD,
            LARGEST_MANAGER_CIK = excluded.LARGEST_MANAGER_CIK,
            LARGEST_MANAGER_VALUE_USD =
                excluded.LARGEST_MANAGER_VALUE_USD,
            MANAGER_CONCENTRATION_HHI =
                excluded.MANAGER_CONCENTRATION_HHI,
            HAS_SHARED_DISCRETION = excluded.HAS_SHARED_DISCRETION,
            HAS_CONFIDENTIAL_OMISSION =
                excluded.HAS_CONFIDENTIAL_OMISSION,
            VALUE_QUALITY_STATUS = excluded.VALUE_QUALITY_STATUS
        """
    )
    connection.execute(
        """
        DELETE FROM CUSIP_QUARTER_SUMMARY
        WHERE NOT EXISTS (
            SELECT 1 FROM CUSIP_SUMMARY_STAGE S
            WHERE S.CUSIP_ID = CUSIP_QUARTER_SUMMARY.CUSIP_ID
              AND S.QUARTER_ID = CUSIP_QUARTER_SUMMARY.QUARTER_ID
        )
        """
    )


def build(database: Path) -> dict[str, int]:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA cache_size = -262144")
    try:
        connection.execute("BEGIN IMMEDIATE")
        execute_statements(connection, INSTRUMENT_SCHEMA)
        seed_reference_data(connection)
        method_counts = classify_cusips(connection)
        sync_instruments(connection)
        build_position_stage(connection)
        sync_relationships_and_facts(connection)
        build_manager_summary_stage(connection)
        sync_manager_summaries(connection)
        build_cusip_summary_stage(connection)
        sync_cusip_summaries(connection)
        build_change_stage(connection)
        sync_changes(connection)
        sync_api_activity_summaries(connection)
        try:
            from .build_security_instrument_summaries import (
                refresh_in_transaction,
            )
        except ImportError:
            from build_security_instrument_summaries import (
                refresh_in_transaction,
            )
        refresh_in_transaction(connection)
        execute_statements(connection, FACT_VIEWS)

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                f"SQLite foreign-key check failed: {foreign_key_errors[:5]}"
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        counts = {
            "classified_cusips": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_CLASSIFICATION"
            ).fetchone()[0],
            "unknown_cusips": method_counts.get("UNKNOWN", 0),
            "instruments": connection.execute(
                "SELECT COUNT(*) FROM INSTRUMENT WHERE IS_ACTIVE = 1"
            ).fetchone()[0],
            "relationships": connection.execute(
                "SELECT COUNT(*) FROM CIK_INSTRUMENT WHERE IS_ACTIVE = 1"
            ).fetchone()[0],
            "quarterly_positions": connection.execute(
                "SELECT COUNT(*) FROM CIK_INSTRUMENT_QUARTER"
            ).fetchone()[0],
            "manager_summaries": connection.execute(
                "SELECT COUNT(*) FROM CIK_QUARTER_SUMMARY"
            ).fetchone()[0],
            "cusip_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_QUARTER_SUMMARY"
            ).fetchone()[0],
            "quarterly_changes": connection.execute(
                "SELECT COUNT(*) FROM CIK_INSTRUMENT_CHANGE"
            ).fetchone()[0],
            "manager_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CIK_QUARTER_ACTIVITY"
            ).fetchone()[0],
            "cusip_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_QUARTER_ACTIVITY"
            ).fetchone()[0],
            "manager_action_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CIK_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
            "cusip_action_activity_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
            "cusip_instrument_type_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_INSTRUMENT_QUARTER_SUMMARY"
            ).fetchone()[0],
            "cusip_base_action_summaries": connection.execute(
                "SELECT COUNT(*) FROM CUSIP_BASE_QUARTER_ACTION_ACTIVITY"
            ).fetchone()[0],
        }
        connection.commit()
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=PROJECT_DIR / "form13f.sqlite3"
    )
    arguments = parser.parse_args()
    try:
        counts = build(arguments.database.expanduser().resolve())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Classified CUSIPs: {counts['classified_cusips']:,}")
    print(f"CUSIPs remaining unknown: {counts['unknown_cusips']:,}")
    print(f"Active instruments: {counts['instruments']:,}")
    print(f"Active CIK/instrument relationships: {counts['relationships']:,}")
    print(f"Quarterly positions: {counts['quarterly_positions']:,}")
    print(f"CIK quarterly summaries: {counts['manager_summaries']:,}")
    print(f"CUSIP quarterly summaries: {counts['cusip_summaries']:,}")
    print(f"Adjacent-quarter changes: {counts['quarterly_changes']:,}")
    print(
        "CIK quarterly activity summaries: "
        f"{counts['manager_activity_summaries']:,}"
    )
    print(
        "CUSIP quarterly activity summaries: "
        f"{counts['cusip_activity_summaries']:,}"
    )
    print(
        "CIK action activity summaries: "
        f"{counts['manager_action_activity_summaries']:,}"
    )
    print(
        "CUSIP action activity summaries: "
        f"{counts['cusip_action_activity_summaries']:,}"
    )
    print(
        "CUSIP instrument-type summaries: "
        f"{counts['cusip_instrument_type_summaries']:,}"
    )
    print(
        "CUSIP base-action summaries: "
        f"{counts['cusip_base_action_summaries']:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
