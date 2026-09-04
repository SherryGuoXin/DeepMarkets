#!/usr/bin/env python3
"""Build request-ready analytics for the latest partial EDGAR quarter."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    from .build_instruments import issuer_comparison_key, system_security_type_code
except ImportError:  # Allow direct execution: python3 etl/build_daily_cik.py
    from build_instruments import issuer_comparison_key, system_security_type_code


SCHEMA = """
CREATE TABLE IF NOT EXISTS ETL_BATCH_REPORT_QUARTER (
    ETL_BATCH_ID INTEGER NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    SOURCE_FILING_COUNT INTEGER NOT NULL,
    PRIMARY KEY (ETL_BATCH_ID, QUARTER_ID),
    FOREIGN KEY (ETL_BATCH_ID)
        REFERENCES ETL_BATCH (ETL_BATCH_ID) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS DAILY_CIK_QUARTER_STATUS (
    QUARTER_ID INTEGER PRIMARY KEY,
    STATUS TEXT NOT NULL CHECK (STATUS IN ('PARTIAL', 'COMPLETE')),
    FILING_COUNT INTEGER NOT NULL,
    UPDATED_AT TEXT NOT NULL,
    FOREIGN KEY (QUARTER_ID) REFERENCES QUARTER (QUARTER_ID)
);

CREATE TABLE IF NOT EXISTS DAILY_CIK_HOLDING (
    MANAGER_CIK CHAR(10) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    CUSIP CHAR(9) NOT NULL,
    ISSUER TEXT,
    TITLE_OF_CLASS TEXT,
    SECURITY_TYPE TEXT NOT NULL,
    OPTION_TYPE TEXT NOT NULL,
    AMOUNT_TYPE TEXT NOT NULL,
    MARKET_VALUE_USD INTEGER NOT NULL,
    REPORTED_AMOUNT INTEGER NOT NULL,
    PORTFOLIO_WEIGHT REAL,
    ACTION TEXT NOT NULL,
    AMOUNT_CHANGE INTEGER,
    AMOUNT_CHANGE_PERCENT REAL,
    VALUE_CHANGE_USD INTEGER NOT NULL,
    IS_COMPARABLE INTEGER NOT NULL,
    PRIMARY KEY (
        MANAGER_CIK, QUARTER_ID, CUSIP, OPTION_TYPE, AMOUNT_TYPE
    )
);

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_QUARTER_VALUE_IDX
    ON DAILY_CIK_HOLDING (QUARTER_ID, MARKET_VALUE_USD DESC);

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_CUSIP_QUARTER_IDX
    ON DAILY_CIK_HOLDING (CUSIP, QUARTER_ID, MARKET_VALUE_USD DESC);

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_MANAGER_QUARTER_IDX
    ON DAILY_CIK_HOLDING (MANAGER_CIK, QUARTER_ID);

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_QUARTER_CHANGE_IDX
    ON DAILY_CIK_HOLDING (QUARTER_ID, ABS(VALUE_CHANGE_USD) DESC);

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_ACTIVITY_FILTER_IDX
    ON DAILY_CIK_HOLDING (
        QUARTER_ID, OPTION_TYPE, ACTION, ABS(VALUE_CHANGE_USD) DESC
    );

CREATE INDEX IF NOT EXISTS DAILY_CIK_HOLDING_ACTIVITY_ALL_IDX
    ON DAILY_CIK_HOLDING (
        QUARTER_ID, OPTION_TYPE, ABS(VALUE_CHANGE_USD) DESC
    );

CREATE TABLE IF NOT EXISTS DAILY_CIK_QUARTER_SUMMARY (
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
    LARGEST_HOLDING_CUSIP CHAR(9),
    LARGEST_HOLDING_ISSUER TEXT,
    LARGEST_POSITION_VALUE_USD INTEGER,
    LARGEST_POSITION_WEIGHT REAL,
    TOP_10_WEIGHT REAL,
    HAS_SHARED_DISCRETION INTEGER NOT NULL,
    HAS_CONFIDENTIAL_OMISSION INTEGER NOT NULL,
    VALUE_QUALITY_STATUS TEXT NOT NULL,
    UPDATED_AT TEXT NOT NULL,
    PRIMARY KEY (MANAGER_CIK, QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS DAILY_CIK_SUMMARY_QUARTER_VALUE_IDX
    ON DAILY_CIK_QUARTER_SUMMARY (QUARTER_ID, PORTFOLIO_VALUE_USD DESC);

CREATE TABLE IF NOT EXISTS DAILY_CIK_QUARTER_ACTIVITY (
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
    PRIMARY KEY (MANAGER_CIK, QUARTER_ID)
);

CREATE TABLE IF NOT EXISTS DAILY_CUSIP_QUARTER_SUMMARY (
    CUSIP CHAR(9) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    ISSUER TEXT,
    TITLE_OF_CLASS TEXT,
    SECURITY_TYPE TEXT NOT NULL,
    MANAGER_COUNT INTEGER NOT NULL,
    TOTAL_VALUE_USD INTEGER NOT NULL,
    COMMON_STOCK_VALUE_USD INTEGER NOT NULL,
    ETF_VALUE_USD INTEGER NOT NULL,
    CALL_VALUE_USD INTEGER NOT NULL,
    PUT_VALUE_USD INTEGER NOT NULL,
    MANAGER_CONCENTRATION_HHI REAL,
    AVERAGE_POSITION_VALUE_USD REAL,
    LARGEST_MANAGER_CIK CHAR(10),
    LARGEST_MANAGER_VALUE_USD INTEGER,
    UPDATED_AT TEXT NOT NULL,
    PRIMARY KEY (CUSIP, QUARTER_ID)
);

CREATE INDEX IF NOT EXISTS DAILY_CUSIP_SUMMARY_QUARTER_VALUE_IDX
    ON DAILY_CUSIP_QUARTER_SUMMARY (QUARTER_ID, TOTAL_VALUE_USD DESC);

CREATE TABLE IF NOT EXISTS DAILY_CUSIP_QUARTER_ACTIVITY (
    CUSIP CHAR(9) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    NEW_INVESTOR_COUNT INTEGER NOT NULL,
    EXITED_INVESTOR_COUNT INTEGER NOT NULL,
    ADDED_HOLDER_COUNT INTEGER NOT NULL,
    REDUCED_HOLDER_COUNT INTEGER NOT NULL,
    NET_VALUE_CHANGE_USD INTEGER NOT NULL,
    PRIMARY KEY (CUSIP, QUARTER_ID)
);

CREATE TABLE IF NOT EXISTS DAILY_CUSIP_OPTION_SUMMARY (
    CUSIP CHAR(9) NOT NULL,
    QUARTER_ID INTEGER NOT NULL,
    OPTION_TYPE TEXT NOT NULL,
    TOTAL_VALUE_USD INTEGER NOT NULL,
    REPORTED_AMOUNT INTEGER NOT NULL,
    INSTITUTION_COUNT INTEGER NOT NULL,
    PRIMARY KEY (CUSIP, QUARTER_ID, OPTION_TYPE)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_status_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(DAILY_CIK_QUARTER_STATUS)")
    }
    additions = {
        "LATEST_FILING_DATE": "DATE",
        "EXPECTED_FILING_COUNT": "INTEGER",
        "MISSING_FILING_COUNT": "INTEGER",
        "COMPLETED_AT": "TEXT",
    }
    for name, column_type in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE DAILY_CIK_QUARTER_STATUS "
                f"ADD COLUMN {name} {column_type}"
            )


def rebuild_market_materializations(
    connection: sqlite3.Connection,
    quarter_id: int,
    built_at: str,
    cusips: set[str] | None = None,
) -> None:
    """Refresh partial-quarter security and market-wide serving tables."""
    connection.execute("DROP TABLE IF EXISTS temp.DAILY_CUSIP_SCOPE")
    connection.execute(
        "CREATE TEMP TABLE DAILY_CUSIP_SCOPE (CUSIP TEXT PRIMARY KEY)"
    )
    if cusips is not None:
        connection.executemany(
            "INSERT INTO DAILY_CUSIP_SCOPE VALUES (?)",
            ((cusip,) for cusip in sorted(cusips)),
        )
    scope = (
        " AND CUSIP IN (SELECT CUSIP FROM temp.DAILY_CUSIP_SCOPE)"
        if cusips is not None else ""
    )
    connection.execute(
        "DELETE FROM DAILY_CUSIP_QUARTER_SUMMARY WHERE QUARTER_ID = ?" + scope,
        (quarter_id,),
    )
    connection.execute(
        "DELETE FROM DAILY_CUSIP_QUARTER_ACTIVITY WHERE QUARTER_ID = ?" + scope,
        (quarter_id,),
    )
    connection.execute(
        "DELETE FROM DAILY_CUSIP_OPTION_SUMMARY WHERE QUARTER_ID = ?" + scope,
        (quarter_id,),
    )
    connection.execute(
        f"""
        INSERT INTO DAILY_CUSIP_QUARTER_SUMMARY (
            CUSIP, QUARTER_ID, ISSUER, TITLE_OF_CLASS, SECURITY_TYPE,
            MANAGER_COUNT, TOTAL_VALUE_USD, COMMON_STOCK_VALUE_USD,
            ETF_VALUE_USD, CALL_VALUE_USD, PUT_VALUE_USD,
            MANAGER_CONCENTRATION_HHI, AVERAGE_POSITION_VALUE_USD,
            LARGEST_MANAGER_CIK, LARGEST_MANAGER_VALUE_USD, UPDATED_AT
        )
        WITH MANAGER_POSITION AS (
            SELECT
                CUSIP, QUARTER_ID, MANAGER_CIK,
                MAX(ISSUER) AS ISSUER,
                MAX(TITLE_OF_CLASS) AS TITLE_OF_CLASS,
                MAX(CASE WHEN OPTION_TYPE = 'NONE' THEN SECURITY_TYPE END)
                    AS SECURITY_TYPE,
                SUM(MARKET_VALUE_USD) AS TOTAL_VALUE_USD,
                SUM(CASE WHEN OPTION_TYPE = 'NONE'
                    THEN MARKET_VALUE_USD ELSE 0 END) AS BASE_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE = 'COMMON_STOCK'
                    THEN MARKET_VALUE_USD ELSE 0 END) AS COMMON_STOCK_VALUE_USD,
                SUM(CASE WHEN SECURITY_TYPE = 'ETF'
                    THEN MARKET_VALUE_USD ELSE 0 END) AS ETF_VALUE_USD,
                SUM(CASE WHEN OPTION_TYPE = 'CALL'
                    THEN MARKET_VALUE_USD ELSE 0 END) AS CALL_VALUE_USD,
                SUM(CASE WHEN OPTION_TYPE = 'PUT'
                    THEN MARKET_VALUE_USD ELSE 0 END) AS PUT_VALUE_USD
            FROM DAILY_CIK_HOLDING
            WHERE QUARTER_ID = ? AND ACTION NOT IN ('EXITED', 'UNKNOWN')
                {scope}
            GROUP BY CUSIP, QUARTER_ID, MANAGER_CIK
        ), RANKED AS (
            SELECT M.*,
                ROW_NUMBER() OVER (
                    PARTITION BY CUSIP, QUARTER_ID
                    ORDER BY TOTAL_VALUE_USD DESC, MANAGER_CIK
                ) AS VALUE_RANK,
                SUM(TOTAL_VALUE_USD) OVER (
                    PARTITION BY CUSIP, QUARTER_ID
                ) AS SECURITY_TOTAL
            FROM MANAGER_POSITION M
        )
        SELECT
            R.CUSIP, R.QUARTER_ID,
            COALESCE(MAX(V.CURRENT_NAMEOFISSUER), MAX(R.ISSUER)),
            COALESCE(MAX(V.CURRENT_TITLEOFCLASS), MAX(R.TITLE_OF_CLASS)),
            CASE
                WHEN SUM(BASE_VALUE_USD) = 0 AND SUM(CALL_VALUE_USD) > 0
                    AND SUM(PUT_VALUE_USD) = 0 THEN 'OPTION_CALL'
                WHEN SUM(BASE_VALUE_USD) = 0 AND SUM(PUT_VALUE_USD) > 0
                    AND SUM(CALL_VALUE_USD) = 0 THEN 'OPTION_PUT'
                WHEN SUM(BASE_VALUE_USD) = 0 AND SUM(CALL_VALUE_USD) > 0
                    AND SUM(PUT_VALUE_USD) > 0 THEN 'OPTION'
                ELSE COALESCE(
                    MAX(T.SECURITY_TYPE_CODE), MAX(R.SECURITY_TYPE), 'UNKNOWN'
                )
            END,
            COUNT(*),
            MAX(SECURITY_TOTAL), SUM(COMMON_STOCK_VALUE_USD),
            SUM(ETF_VALUE_USD), SUM(CALL_VALUE_USD), SUM(PUT_VALUE_USD),
            SUM(1.0 * TOTAL_VALUE_USD * TOTAL_VALUE_USD)
                / NULLIF(1.0 * MAX(SECURITY_TOTAL) * MAX(SECURITY_TOTAL), 0),
            1.0 * MAX(SECURITY_TOTAL) / COUNT(*),
            MAX(CASE WHEN VALUE_RANK = 1 THEN MANAGER_CIK END),
            MAX(CASE WHEN VALUE_RANK = 1 THEN TOTAL_VALUE_USD END), ?
        FROM RANKED R
        LEFT JOIN CUSIP D ON D.CUSIP = R.CUSIP
        LEFT JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID)
        LEFT JOIN CUSIP_CLASSIFICATION CC USING (CUSIP_ID)
        LEFT JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
        GROUP BY R.CUSIP, R.QUARTER_ID
        """,
        (quarter_id, built_at),
    )
    connection.execute(
        f"""
        INSERT INTO DAILY_CUSIP_QUARTER_ACTIVITY
        WITH MANAGER_ACTION AS (
            SELECT
                CUSIP, QUARTER_ID, MANAGER_CIK,
                CASE
                    WHEN SUM(IS_COMPARABLE = 0) > 0 THEN 'UNKNOWN'
                    WHEN SUM(ACTION = 'NEW') > 0 THEN 'NEW'
                    WHEN SUM(ACTION = 'ADDED') > 0 THEN 'ADDED'
                    WHEN SUM(ACTION = 'REDUCED') > 0 THEN 'REDUCED'
                    WHEN SUM(ACTION = 'EXITED') > 0 THEN 'EXITED'
                    ELSE 'UNCHANGED'
                END AS ACTION,
                SUM(CASE WHEN IS_COMPARABLE = 1
                    THEN VALUE_CHANGE_USD ELSE 0 END) AS VALUE_CHANGE_USD
            FROM DAILY_CIK_HOLDING
            WHERE QUARTER_ID = ? AND OPTION_TYPE = 'NONE'
                {scope}
            GROUP BY CUSIP, QUARTER_ID, MANAGER_CIK
        )
        SELECT CUSIP, QUARTER_ID,
            SUM(ACTION = 'NEW'), SUM(ACTION = 'EXITED'),
            SUM(ACTION = 'ADDED'), SUM(ACTION = 'REDUCED'),
            SUM(VALUE_CHANGE_USD)
        FROM MANAGER_ACTION
        GROUP BY CUSIP, QUARTER_ID
        """,
        (quarter_id,),
    )
    connection.execute(
        f"""
        INSERT INTO DAILY_CUSIP_OPTION_SUMMARY
        SELECT CUSIP, QUARTER_ID, OPTION_TYPE,
            SUM(MARKET_VALUE_USD), SUM(REPORTED_AMOUNT),
            COUNT(DISTINCT MANAGER_CIK)
        FROM DAILY_CIK_HOLDING
        WHERE QUARTER_ID = ? AND ACTION NOT IN ('EXITED', 'UNKNOWN')
            {scope}
        GROUP BY CUSIP, QUARTER_ID, OPTION_TYPE
        """,
        (quarter_id,),
    )


def suppress_probable_identifier_transitions(
    connection: sqlite3.Connection, quarter_id: int
) -> set[str]:
    """Suppress high-overlap old/new CUSIP comparisons without merging them."""
    connection.execute("DROP TABLE IF EXISTS temp.DAILY_CHANGE_IDENTITY_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE DAILY_CHANGE_IDENTITY_STAGE AS
        SELECT
            MANAGER_CIK,
            QUARTER_ID,
            CUSIP,
            ISSUER_KEY(ISSUER) AS ISSUER_KEY,
            CASE
                WHEN ACTION = 'EXITED'
                  OR (ACTION = 'UNKNOWN' AND AMOUNT_CHANGE < 0) THEN 'EXITED'
                WHEN ACTION = 'NEW'
                  OR (ACTION = 'UNKNOWN' AND AMOUNT_CHANGE > 0) THEN 'NEW'
            END AS EFFECTIVE_ACTION
        FROM DAILY_CIK_HOLDING
        WHERE QUARTER_ID = ? AND OPTION_TYPE = 'NONE' AND AMOUNT_TYPE = 'SH'
          AND (
              ACTION IN ('NEW', 'EXITED')
              OR (ACTION = 'UNKNOWN' AND AMOUNT_CHANGE <> 0)
          )
        """,
        (quarter_id,),
    )
    connection.execute(
        "CREATE INDEX temp.DAILY_CHANGE_IDENTITY_MATCH_IDX ON "
        "DAILY_CHANGE_IDENTITY_STAGE "
        "(QUARTER_ID, ISSUER_KEY, MANAGER_CIK, EFFECTIVE_ACTION)"
    )
    connection.execute(
        "CREATE INDEX temp.DAILY_CHANGE_IDENTITY_HOLDING_IDX ON "
        "DAILY_CHANGE_IDENTITY_STAGE "
        "(MANAGER_CIK, QUARTER_ID, CUSIP, EFFECTIVE_ACTION, ISSUER_KEY)"
    )
    connection.execute("DROP TABLE IF EXISTS temp.DAILY_IDENTIFIER_TRANSITION_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE DAILY_IDENTIFIER_TRANSITION_STAGE AS
        WITH PAIR_OVERLAP AS (
            SELECT
                E.QUARTER_ID,
                E.ISSUER_KEY,
                E.CUSIP AS OLD_CUSIP,
                N.CUSIP AS NEW_CUSIP,
                COUNT(DISTINCT E.MANAGER_CIK) AS OVERLAP_COUNT
            FROM DAILY_CHANGE_IDENTITY_STAGE E
            JOIN DAILY_CHANGE_IDENTITY_STAGE N
              ON N.MANAGER_CIK = E.MANAGER_CIK
             AND N.QUARTER_ID = E.QUARTER_ID
             AND N.ISSUER_KEY = E.ISSUER_KEY
             AND N.EFFECTIVE_ACTION = 'NEW'
             AND N.CUSIP <> E.CUSIP
            WHERE E.EFFECTIVE_ACTION = 'EXITED' AND E.ISSUER_KEY <> ''
            GROUP BY E.QUARTER_ID, E.ISSUER_KEY, E.CUSIP, N.CUSIP
        ), OLD_TOTAL AS (
            SELECT QUARTER_ID, CUSIP, COUNT(DISTINCT MANAGER_CIK) AS N
            FROM DAILY_CHANGE_IDENTITY_STAGE
            WHERE EFFECTIVE_ACTION = 'EXITED'
            GROUP BY QUARTER_ID, CUSIP
        ), NEW_TOTAL AS (
            SELECT QUARTER_ID, CUSIP, COUNT(DISTINCT MANAGER_CIK) AS N
            FROM DAILY_CHANGE_IDENTITY_STAGE
            WHERE EFFECTIVE_ACTION = 'NEW'
            GROUP BY QUARTER_ID, CUSIP
        )
        SELECT P.QUARTER_ID, P.ISSUER_KEY, P.OLD_CUSIP, P.NEW_CUSIP
        FROM PAIR_OVERLAP P
        JOIN OLD_TOTAL O
          ON O.QUARTER_ID = P.QUARTER_ID AND O.CUSIP = P.OLD_CUSIP
        JOIN NEW_TOTAL N
          ON N.QUARTER_ID = P.QUARTER_ID AND N.CUSIP = P.NEW_CUSIP
        WHERE P.OVERLAP_COUNT >= 25
          AND P.OVERLAP_COUNT * 100 >= O.N * 60
          AND P.OVERLAP_COUNT * 100 >= N.N * 60
        """
    )
    transition_cusips = {
        str(cusip)
        for row in connection.execute(
            "SELECT OLD_CUSIP, NEW_CUSIP "
            "FROM DAILY_IDENTIFIER_TRANSITION_STAGE"
        )
        for cusip in row
    }
    connection.execute("DROP TABLE IF EXISTS temp.DAILY_NONCOMPARABLE_STAGE")
    connection.execute(
        """
        CREATE TEMP TABLE DAILY_NONCOMPARABLE_STAGE AS
        SELECT DISTINCT S.MANAGER_CIK, S.QUARTER_ID, S.CUSIP
        FROM DAILY_CHANGE_IDENTITY_STAGE S
        JOIN DAILY_IDENTIFIER_TRANSITION_STAGE T
          ON T.QUARTER_ID = S.QUARTER_ID
         AND T.ISSUER_KEY = S.ISSUER_KEY
         AND (
             (S.EFFECTIVE_ACTION = 'EXITED' AND S.CUSIP = T.OLD_CUSIP)
             OR (S.EFFECTIVE_ACTION = 'NEW' AND S.CUSIP = T.NEW_CUSIP)
         )
        JOIN DAILY_CHANGE_IDENTITY_STAGE OTHER
          ON OTHER.MANAGER_CIK = S.MANAGER_CIK
         AND OTHER.QUARTER_ID = S.QUARTER_ID
         AND OTHER.ISSUER_KEY = S.ISSUER_KEY
         AND (
             (S.EFFECTIVE_ACTION = 'EXITED'
              AND OTHER.EFFECTIVE_ACTION = 'NEW'
              AND OTHER.CUSIP = T.NEW_CUSIP)
             OR (S.EFFECTIVE_ACTION = 'NEW'
                 AND OTHER.EFFECTIVE_ACTION = 'EXITED'
                 AND OTHER.CUSIP = T.OLD_CUSIP)
         )
        """,
    )
    connection.execute(
        "CREATE UNIQUE INDEX temp.DAILY_NONCOMPARABLE_STAGE_PK ON "
        "DAILY_NONCOMPARABLE_STAGE (MANAGER_CIK, QUARTER_ID, CUSIP)"
    )
    connection.execute(
        """
        UPDATE DAILY_CIK_HOLDING AS H
        SET IS_COMPARABLE = 0
        WHERE H.QUARTER_ID = ?
          AND EXISTS (
              SELECT 1 FROM DAILY_NONCOMPARABLE_STAGE S
              WHERE S.MANAGER_CIK = H.MANAGER_CIK
                AND S.QUARTER_ID = H.QUARTER_ID
                AND S.CUSIP = H.CUSIP
          )
        """,
        (quarter_id,),
    )
    return transition_cusips


def build(
    database: Path,
    *,
    quarter_id: int | None = None,
    manager_ciks: set[str] | None = None,
) -> dict[str, int | None]:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    connection.create_function(
        "DAILY_SECURITY_TYPE", 2, system_security_type_code, deterministic=True
    )
    connection.create_function(
        "ISSUER_KEY", 1, issuer_comparison_key, deterministic=True
    )
    try:
        connection.executescript(SCHEMA)
        ensure_status_columns(connection)
        if quarter_id is None:
            latest = connection.execute(
                """
                SELECT MAX(N.QUARTER_ID)
                FROM DAILY_EDGAR_ACCESSION D
                JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
                WHERE N.QUARTER_ID IS NOT NULL
                """
            ).fetchone()[0]
            if latest is None:
                return {"quarter_id": None, "institutions": 0, "holdings": 0}
            quarter_id = int(latest)
        targeted = bool(manager_ciks)
        connection.execute("CREATE TEMP TABLE TARGET_MANAGER (CIK TEXT PRIMARY KEY)")
        if targeted:
            connection.executemany(
                "INSERT INTO TARGET_MANAGER VALUES (?)",
                ((cik,) for cik in sorted(manager_ciks or set())),
            )
        connection.commit()
        completed_analytics_quarter = connection.execute(
            "SELECT MAX(QUARTER_ID) FROM CIK_QUARTER_SUMMARY"
        ).fetchone()[0]
        daily_status_row = connection.execute(
            "SELECT STATUS FROM DAILY_CIK_QUARTER_STATUS WHERE QUARTER_ID = ?",
            (quarter_id,),
        ).fetchone()
        daily_status = daily_status_row[0] if daily_status_row else None
        if (
            completed_analytics_quarter is not None
            and quarter_id <= int(completed_analytics_quarter)
            and daily_status != "PARTIAL"
        ):
            # A reconciled quarter is a coverage checkpoint, not immutable.
            # The first later filing seeds a complete daily snapshot so APIs
            # never switch from the bulk layer to a manager-only fragment.
            targeted = False
            connection.execute("DELETE FROM TARGET_MANAGER")
            connection.commit()

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE IF EXISTS temp.DAILY_MANAGER_STAGE")
        connection.execute("DROP TABLE IF EXISTS temp.DAILY_RECON_STAGE")
        connection.execute("DROP TABLE IF EXISTS temp.DAILY_CURRENT_STAGE")
        connection.execute("DROP TABLE IF EXISTS temp.DAILY_PRIOR_STAGE")
        connection.execute(
            """
            CREATE TEMP TABLE DAILY_MANAGER_STAGE AS
            SELECT
                N.MANAGER_CIK,
                N.QUARTER_ID,
                Q.PREVIOUS_QUARTER_ID,
                MAX(F.HAS_CONFIDENTIAL_OMISSION) AS HAS_CONFIDENTIAL_OMISSION
            FROM NORMALIZED_FILING N
            JOIN QUARTER Q USING (QUARTER_ID)
            JOIN CANONICAL_FILING F
              ON F.MANAGER_CIK = N.MANAGER_CIK
             AND F.QUARTER_ID = N.QUARTER_ID
            WHERE N.QUARTER_ID = ?
              AND (
                  NOT EXISTS (SELECT 1 FROM TARGET_MANAGER)
                  OR N.MANAGER_CIK IN (SELECT CIK FROM TARGET_MANAGER)
              )
            GROUP BY N.MANAGER_CIK, N.QUARTER_ID
            """,
            (quarter_id,),
        )
        connection.execute(
            "CREATE UNIQUE INDEX temp.DAILY_MANAGER_STAGE_PK "
            "ON DAILY_MANAGER_STAGE (MANAGER_CIK, QUARTER_ID)"
        )
        affected_cusips = (
            {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT H.CUSIP
                    FROM DAILY_CIK_HOLDING H
                    JOIN DAILY_MANAGER_STAGE M
                      ON M.MANAGER_CIK = H.MANAGER_CIK
                     AND M.QUARTER_ID = H.QUARTER_ID
                    """
                )
            }
            if targeted else None
        )
        connection.execute(
            """
            CREATE TEMP TABLE DAILY_RECON_STAGE AS
            SELECT
                C.ACCESSION_NUMBER,
                CASE
                    WHEN SP.TABLEVALUETOTAL IS NULL THEN 1
                    WHEN SUM(I.VALUE) = SP.TABLEVALUETOTAL THEN 0
                    WHEN ABS(SUM(I.VALUE) - SP.TABLEVALUETOTAL) <= 1 THEN 0
                    ELSE 1
                END AS HAS_VALUE_ISSUE
            FROM DAILY_MANAGER_STAGE M
            JOIN CANONICAL_FILING F
              ON F.MANAGER_CIK = M.MANAGER_CIK
             AND F.QUARTER_ID = M.QUARTER_ID
             AND F.IS_ANALYTICS_READY = 1
            JOIN CANONICAL_FILING_COMPONENT C
              ON C.CANONICAL_FILING_ID = F.CANONICAL_FILING_ID
             AND C.IS_EFFECTIVE = 1
            JOIN INFOTABLE I USING (ACCESSION_NUMBER)
            LEFT JOIN SUMMARYPAGE SP USING (ACCESSION_NUMBER)
            GROUP BY C.ACCESSION_NUMBER
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX temp.DAILY_RECON_STAGE_PK "
            "ON DAILY_RECON_STAGE (ACCESSION_NUMBER)"
        )
        connection.execute(
            """
            CREATE TEMP TABLE DAILY_CURRENT_STAGE AS
            WITH CLASSIFIED_HOLDING AS (
                SELECT
                    F.MANAGER_CIK,
                    F.QUARTER_ID,
                    H.CUSIP,
                    H.NAMEOFISSUER AS ISSUER,
                    H.TITLEOFCLASS AS TITLE_OF_CLASS,
                    CASE UPPER(COALESCE(H.PUTCALL, ''))
                        WHEN 'CALL' THEN 'OPTION_CALL'
                        WHEN 'PUT' THEN 'OPTION_PUT'
                        ELSE COALESCE(
                            NULLIF(T.SECURITY_TYPE_CODE, 'UNKNOWN'),
                            DAILY_SECURITY_TYPE(H.TITLEOFCLASS, H.NAMEOFISSUER),
                            T.SECURITY_TYPE_CODE,
                            'UNKNOWN'
                        )
                    END AS SECURITY_TYPE,
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
                    H.VALUE * COALESCE(VS.VALUE_MULTIPLIER,
                        CASE WHEN N.FILING_DATE_ISO < '2023-01-03'
                            THEN 1000 ELSE 1 END
                    ) AS MARKET_VALUE_USD,
                    H.SSHPRNAMT AS REPORTED_AMOUNT,
                    CASE WHEN COALESCE(H.VOTING_AUTH_SHARED, 0) > 0
                        THEN 1 ELSE 0 END AS HAS_SHARED_DISCRETION,
                    R.HAS_VALUE_ISSUE
                FROM DAILY_MANAGER_STAGE M
                JOIN CANONICAL_FILING F
                  ON F.MANAGER_CIK = M.MANAGER_CIK
                 AND F.QUARTER_ID = M.QUARTER_ID
                 AND F.IS_ANALYTICS_READY = 1
                JOIN CANONICAL_FILING_COMPONENT C
                  ON C.CANONICAL_FILING_ID = F.CANONICAL_FILING_ID
                 AND C.IS_EFFECTIVE = 1
                JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
                JOIN INFOTABLE H USING (ACCESSION_NUMBER)
                LEFT JOIN FILING_VALUE_SCALE VS USING (ACCESSION_NUMBER)
                JOIN DAILY_RECON_STAGE R USING (ACCESSION_NUMBER)
                LEFT JOIN CUSIP D ON D.CUSIP = H.CUSIP
                LEFT JOIN CUSIP_CLASSIFICATION CC USING (CUSIP_ID)
                LEFT JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
            )
            SELECT
                MANAGER_CIK,
                QUARTER_ID,
                CUSIP,
                MAX(ISSUER) AS ISSUER,
                MAX(TITLE_OF_CLASS) AS TITLE_OF_CLASS,
                CASE
                    WHEN COUNT(DISTINCT NULLIF(SECURITY_TYPE, 'UNKNOWN')) = 1
                        THEN MAX(NULLIF(SECURITY_TYPE, 'UNKNOWN'))
                    ELSE 'UNKNOWN'
                END AS SECURITY_TYPE,
                OPTION_TYPE,
                AMOUNT_TYPE,
                SUM(MARKET_VALUE_USD) AS MARKET_VALUE_USD,
                SUM(REPORTED_AMOUNT) AS REPORTED_AMOUNT,
                MAX(HAS_SHARED_DISCRETION) AS HAS_SHARED_DISCRETION,
                MAX(HAS_VALUE_ISSUE) AS HAS_VALUE_ISSUE
            FROM CLASSIFIED_HOLDING
            GROUP BY
                MANAGER_CIK,
                QUARTER_ID,
                CUSIP,
                OPTION_TYPE,
                AMOUNT_TYPE
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX temp.DAILY_CURRENT_STAGE_PK ON "
            "DAILY_CURRENT_STAGE (MANAGER_CIK, CUSIP, OPTION_TYPE, AMOUNT_TYPE)"
        )
        connection.execute(
            """
            CREATE TEMP TABLE DAILY_PRIOR_STAGE AS
            SELECT
                R.MANAGER_CIK,
                M.QUARTER_ID,
                V.CUSIP,
                V.CURRENT_NAMEOFISSUER AS ISSUER,
                V.CURRENT_TITLEOFCLASS AS TITLE_OF_CLASS,
                T.SECURITY_TYPE_CODE AS SECURITY_TYPE,
                I.OPTION_TYPE,
                I.AMOUNT_TYPE,
                P.VALUE_USD AS MARKET_VALUE_USD,
                P.REPORTED_AMOUNT
            FROM DAILY_MANAGER_STAGE M
            JOIN CIK_INSTRUMENT R ON R.MANAGER_CIK = M.MANAGER_CIK
            JOIN CIK_INSTRUMENT_QUARTER P
              ON P.CIK_INSTRUMENT_ID = R.CIK_INSTRUMENT_ID
             AND P.QUARTER_ID = M.PREVIOUS_QUARTER_ID
            JOIN INSTRUMENT I USING (INSTRUMENT_ID)
            JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
            JOIN CUSIP_CURRENT_VARIANT V USING (CUSIP_ID)
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX temp.DAILY_PRIOR_STAGE_PK ON "
            "DAILY_PRIOR_STAGE (MANAGER_CIK, CUSIP, OPTION_TYPE, AMOUNT_TYPE)"
        )

        delete_scope = """
            QUARTER_ID = ? AND (
                NOT EXISTS (SELECT 1 FROM TARGET_MANAGER)
                OR MANAGER_CIK IN (SELECT MANAGER_CIK FROM DAILY_MANAGER_STAGE)
            )
        """
        connection.execute(
            f"DELETE FROM DAILY_CIK_HOLDING WHERE {delete_scope}", (quarter_id,)
        )
        connection.execute(
            f"DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE {delete_scope}",
            (quarter_id,),
        )
        connection.execute(
            f"DELETE FROM DAILY_CIK_QUARTER_SUMMARY WHERE {delete_scope}",
            (quarter_id,),
        )
        connection.execute(
            """
            INSERT INTO DAILY_CIK_HOLDING (
                MANAGER_CIK, QUARTER_ID, CUSIP, ISSUER, TITLE_OF_CLASS,
                SECURITY_TYPE, OPTION_TYPE, AMOUNT_TYPE, MARKET_VALUE_USD,
                REPORTED_AMOUNT, ACTION, AMOUNT_CHANGE,
                AMOUNT_CHANGE_PERCENT, VALUE_CHANGE_USD, IS_COMPARABLE
            )
            SELECT
                C.MANAGER_CIK, C.QUARTER_ID, C.CUSIP, C.ISSUER,
                C.TITLE_OF_CLASS, C.SECURITY_TYPE, C.OPTION_TYPE,
                C.AMOUNT_TYPE, C.MARKET_VALUE_USD, C.REPORTED_AMOUNT,
                CASE
                    WHEN P.CUSIP IS NULL THEN 'NEW'
                    WHEN C.REPORTED_AMOUNT > P.REPORTED_AMOUNT THEN 'ADDED'
                    WHEN C.REPORTED_AMOUNT < P.REPORTED_AMOUNT THEN 'REDUCED'
                    ELSE 'UNCHANGED'
                END,
                CASE WHEN P.CUSIP IS NULL THEN C.REPORTED_AMOUNT
                    ELSE C.REPORTED_AMOUNT - P.REPORTED_AMOUNT END,
                CASE
                    WHEN P.CUSIP IS NULL OR P.REPORTED_AMOUNT = 0 THEN NULL
                    ELSE 1.0 * (C.REPORTED_AMOUNT - P.REPORTED_AMOUNT)
                        / P.REPORTED_AMOUNT
                END,
                C.MARKET_VALUE_USD - COALESCE(P.MARKET_VALUE_USD, 0),
                1
            FROM DAILY_CURRENT_STAGE C
            LEFT JOIN DAILY_PRIOR_STAGE P
              ON P.MANAGER_CIK = C.MANAGER_CIK
             AND P.CUSIP = C.CUSIP
             AND P.OPTION_TYPE = C.OPTION_TYPE
             AND P.AMOUNT_TYPE = C.AMOUNT_TYPE
            """
        )
        connection.execute(
            """
            INSERT INTO DAILY_CIK_HOLDING (
                MANAGER_CIK, QUARTER_ID, CUSIP, ISSUER, TITLE_OF_CLASS,
                SECURITY_TYPE, OPTION_TYPE, AMOUNT_TYPE, MARKET_VALUE_USD,
                REPORTED_AMOUNT, ACTION, AMOUNT_CHANGE,
                AMOUNT_CHANGE_PERCENT, VALUE_CHANGE_USD, IS_COMPARABLE
            )
            SELECT
                P.MANAGER_CIK, P.QUARTER_ID, P.CUSIP, P.ISSUER,
                P.TITLE_OF_CLASS, P.SECURITY_TYPE, P.OPTION_TYPE,
                P.AMOUNT_TYPE, P.MARKET_VALUE_USD, P.REPORTED_AMOUNT,
                CASE WHEN M.HAS_CONFIDENTIAL_OMISSION = 1
                    THEN 'UNKNOWN' ELSE 'EXITED' END,
                -P.REPORTED_AMOUNT, -1.0, -P.MARKET_VALUE_USD,
                CASE WHEN M.HAS_CONFIDENTIAL_OMISSION = 1 THEN 0 ELSE 1 END
            FROM DAILY_PRIOR_STAGE P
            JOIN DAILY_MANAGER_STAGE M
              ON M.MANAGER_CIK = P.MANAGER_CIK
             AND M.QUARTER_ID = P.QUARTER_ID
            LEFT JOIN DAILY_CURRENT_STAGE C
              ON C.MANAGER_CIK = P.MANAGER_CIK
             AND C.CUSIP = P.CUSIP
             AND C.OPTION_TYPE = P.OPTION_TYPE
             AND C.AMOUNT_TYPE = P.AMOUNT_TYPE
            WHERE C.CUSIP IS NULL
            """
        )
        connection.execute(
            """
            UPDATE DAILY_CIK_HOLDING AS H
            SET PORTFOLIO_WEIGHT = CASE
                WHEN H.ACTION IN ('EXITED', 'UNKNOWN') THEN NULL
                ELSE 1.0 * H.MARKET_VALUE_USD / NULLIF((
                    SELECT SUM(X.MARKET_VALUE_USD)
                    FROM DAILY_CURRENT_STAGE X
                    WHERE X.MANAGER_CIK = H.MANAGER_CIK
                ), 0)
            END
            WHERE H.QUARTER_ID = ?
              AND (
                  NOT EXISTS (SELECT 1 FROM TARGET_MANAGER)
                  OR H.MANAGER_CIK IN (
                      SELECT MANAGER_CIK FROM DAILY_MANAGER_STAGE
                  )
              )
            """,
            (quarter_id,),
        )
        built_at = utc_now()
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_SUMMARY (
                MANAGER_CIK, QUARTER_ID, PORTFOLIO_VALUE_USD,
                INSTRUMENT_COUNT, CUSIP_COUNT, COMMON_STOCK_VALUE_USD,
                ETF_VALUE_USD, CALL_VALUE_USD, PUT_VALUE_USD,
                UNKNOWN_VALUE_USD, LARGEST_POSITION_VALUE_USD,
                LARGEST_POSITION_WEIGHT, TOP_10_WEIGHT,
                HAS_SHARED_DISCRETION, HAS_CONFIDENTIAL_OMISSION,
                VALUE_QUALITY_STATUS, UPDATED_AT
            )
            WITH RANKED AS (
                SELECT C.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY C.MANAGER_CIK
                        ORDER BY C.MARKET_VALUE_USD DESC, C.CUSIP
                    ) AS VALUE_RANK
                FROM DAILY_CURRENT_STAGE C
            )
            SELECT
                R.MANAGER_CIK, R.QUARTER_ID,
                SUM(R.MARKET_VALUE_USD), COUNT(*), COUNT(DISTINCT R.CUSIP),
                SUM(CASE WHEN R.SECURITY_TYPE = 'COMMON_STOCK'
                    THEN R.MARKET_VALUE_USD ELSE 0 END),
                SUM(CASE WHEN R.SECURITY_TYPE = 'ETF'
                    THEN R.MARKET_VALUE_USD ELSE 0 END),
                SUM(CASE WHEN R.OPTION_TYPE = 'CALL'
                    THEN R.MARKET_VALUE_USD ELSE 0 END),
                SUM(CASE WHEN R.OPTION_TYPE = 'PUT'
                    THEN R.MARKET_VALUE_USD ELSE 0 END),
                SUM(CASE WHEN R.SECURITY_TYPE = 'UNKNOWN'
                    THEN R.MARKET_VALUE_USD ELSE 0 END),
                MAX(CASE WHEN R.VALUE_RANK = 1 THEN R.MARKET_VALUE_USD END),
                MAX(CASE WHEN R.VALUE_RANK = 1 THEN
                    1.0 * R.MARKET_VALUE_USD / NULLIF(T.TOTAL_VALUE, 0) END),
                SUM(CASE WHEN R.VALUE_RANK <= 10 THEN R.MARKET_VALUE_USD ELSE 0 END)
                    / NULLIF(1.0 * T.TOTAL_VALUE, 0),
                MAX(R.HAS_SHARED_DISCRETION),
                MAX(M.HAS_CONFIDENTIAL_OMISSION),
                CASE WHEN MAX(R.HAS_VALUE_ISSUE) = 1 THEN 'ISSUE' ELSE 'OK' END,
                ?
            FROM RANKED R
            JOIN DAILY_MANAGER_STAGE M
              ON M.MANAGER_CIK = R.MANAGER_CIK
             AND M.QUARTER_ID = R.QUARTER_ID
            JOIN (
                SELECT MANAGER_CIK, SUM(MARKET_VALUE_USD) AS TOTAL_VALUE
                FROM DAILY_CURRENT_STAGE GROUP BY MANAGER_CIK
            ) T USING (MANAGER_CIK)
            GROUP BY R.MANAGER_CIK, R.QUARTER_ID
            """,
            (built_at,),
        )
        connection.execute(
            """
            UPDATE DAILY_CIK_QUARTER_SUMMARY AS S
            SET (LARGEST_HOLDING_CUSIP, LARGEST_HOLDING_ISSUER) = (
                SELECT H.CUSIP, H.ISSUER
                FROM DAILY_CIK_HOLDING H
                WHERE H.MANAGER_CIK = S.MANAGER_CIK
                  AND H.QUARTER_ID = S.QUARTER_ID
                  AND H.ACTION NOT IN ('EXITED', 'UNKNOWN')
                ORDER BY H.MARKET_VALUE_USD DESC, H.CUSIP
                LIMIT 1
            )
            WHERE S.QUARTER_ID = ?
              AND (
                  NOT EXISTS (SELECT 1 FROM TARGET_MANAGER)
                  OR S.MANAGER_CIK IN (
                      SELECT MANAGER_CIK FROM DAILY_MANAGER_STAGE
                  )
              )
            """,
            (quarter_id,),
        )
        transition_cusips = suppress_probable_identifier_transitions(
            connection, quarter_id
        )
        if affected_cusips is not None:
            affected_cusips.update(transition_cusips)
        # A newly detected identifier transition can affect managers published
        # by earlier incremental runs, so refresh this small quarter-wide rollup.
        connection.execute(
            "DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE QUARTER_ID = ?",
            (quarter_id,),
        )
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_ACTIVITY
            SELECT
                MANAGER_CIK, QUARTER_ID,
                SUM(ACTION = 'NEW' AND IS_COMPARABLE = 1),
                SUM(ACTION = 'ADDED' AND IS_COMPARABLE = 1),
                SUM(ACTION = 'REDUCED' AND IS_COMPARABLE = 1),
                SUM(ACTION = 'EXITED' AND IS_COMPARABLE = 1),
                SUM(CASE WHEN IS_COMPARABLE = 1
                    AND ACTION IN ('NEW', 'ADDED')
                    THEN MAX(VALUE_CHANGE_USD, 0) ELSE 0 END),
                SUM(CASE WHEN IS_COMPARABLE = 1
                    AND ACTION IN ('REDUCED', 'EXITED')
                    THEN ABS(MIN(VALUE_CHANGE_USD, 0)) ELSE 0 END),
                SUM(CASE WHEN IS_COMPARABLE = 1
                    THEN ABS(VALUE_CHANGE_USD) ELSE 0 END),
                SUM(CASE WHEN IS_COMPARABLE = 1
                    THEN VALUE_CHANGE_USD ELSE 0 END)
            FROM DAILY_CIK_HOLDING
            WHERE QUARTER_ID = ?
            GROUP BY MANAGER_CIK, QUARTER_ID
            """,
            (quarter_id,),
        )
        if affected_cusips is not None:
            affected_cusips.update(
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT H.CUSIP
                    FROM DAILY_CIK_HOLDING H
                    JOIN DAILY_MANAGER_STAGE M
                      ON M.MANAGER_CIK = H.MANAGER_CIK
                     AND M.QUARTER_ID = H.QUARTER_ID
                    """
                )
            )
        rebuild_market_materializations(
            connection, quarter_id, built_at, affected_cusips
        )
        filing_count = connection.execute(
            """
            SELECT COUNT(DISTINCT N.ACCESSION_NUMBER)
            FROM NORMALIZED_FILING N
            WHERE N.QUARTER_ID = ?
            """,
            (quarter_id,),
        ).fetchone()[0]
        latest_filing_date = connection.execute(
            """
            SELECT MAX(N.FILING_DATE_ISO)
            FROM NORMALIZED_FILING N
            WHERE N.QUARTER_ID = ?
            """,
            (quarter_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_STATUS
                (QUARTER_ID, STATUS, FILING_COUNT, UPDATED_AT,
                 LATEST_FILING_DATE, EXPECTED_FILING_COUNT,
                 MISSING_FILING_COUNT, COMPLETED_AT)
            VALUES (?, 'PARTIAL', ?, ?, ?, NULL, NULL, NULL)
            ON CONFLICT (QUARTER_ID) DO UPDATE SET
                STATUS = 'PARTIAL',
                FILING_COUNT = excluded.FILING_COUNT,
                UPDATED_AT = excluded.UPDATED_AT,
                LATEST_FILING_DATE = excluded.LATEST_FILING_DATE,
                EXPECTED_FILING_COUNT = NULL,
                MISSING_FILING_COUNT = NULL,
                COMPLETED_AT = NULL
            """,
            (quarter_id, filing_count, built_at, latest_filing_date),
        )
        connection.commit()
        counts = {
            "quarter_id": quarter_id,
            "institutions": connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_QUARTER_SUMMARY WHERE QUARTER_ID = ?",
                (quarter_id,),
            ).fetchone()[0],
            "holdings": connection.execute(
                "SELECT COUNT(*) FROM DAILY_CIK_HOLDING WHERE QUARTER_ID = ?",
                (quarter_id,),
            ).fetchone()[0],
            "securities": connection.execute(
                "SELECT COUNT(*) FROM DAILY_CUSIP_QUARTER_SUMMARY "
                "WHERE QUARTER_ID = ?",
                (quarter_id,),
            ).fetchone()[0],
        }
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def build_incremental(
    database: Path, manager_quarters: set[tuple[str, int]]
) -> dict[str, int]:
    """Rebuild daily institution analytics only for affected manager/quarters."""
    by_quarter: dict[int, set[str]] = {}
    for manager_cik, quarter_id in manager_quarters:
        by_quarter.setdefault(int(quarter_id), set()).add(manager_cik)
    published = 0
    for quarter_id, manager_ciks in sorted(by_quarter.items()):
        counts = build(
            database, quarter_id=quarter_id, manager_ciks=manager_ciks
        )
        if counts["quarter_id"] is not None:
            published += len(manager_ciks)
    return {"quarters": len(by_quarter), "institutions": published}


def backfill_market_materializations(database: Path) -> dict[str, int]:
    """Create global partial-quarter tables for an existing daily database."""
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    try:
        connection.executescript(SCHEMA)
        ensure_status_columns(connection)
        quarter_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT QUARTER_ID FROM DAILY_CIK_QUARTER_STATUS "
                "WHERE STATUS = 'PARTIAL' ORDER BY QUARTER_ID"
            )
        ]
        connection.execute("BEGIN IMMEDIATE")
        built_at = utc_now()
        for quarter_id in quarter_ids:
            rebuild_market_materializations(connection, quarter_id, built_at)
            connection.execute(
                """
                UPDATE DAILY_CIK_QUARTER_STATUS
                SET UPDATED_AT = ?, LATEST_FILING_DATE = (
                    SELECT MAX(N.FILING_DATE_ISO)
                    FROM DAILY_EDGAR_ACCESSION D
                    JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
                    WHERE N.QUARTER_ID = DAILY_CIK_QUARTER_STATUS.QUARTER_ID
                )
                WHERE QUARTER_ID = ?
                """,
                (built_at, quarter_id),
            )
        connection.commit()
        return {
            "quarters": len(quarter_ids),
            "securities": int(
                connection.execute(
                    "SELECT COUNT(*) FROM DAILY_CUSIP_QUARTER_SUMMARY"
                ).fetchone()[0]
            ),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def mark_bulk_complete(database: Path) -> int | None:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(SCHEMA)
        ensure_status_columns(connection)
        latest = connection.execute(
            """
            SELECT MAX(QUARTER_ID) FROM (
                SELECT R.QUARTER_ID
                FROM ETL_BATCH_REPORT_QUARTER R
                JOIN ETL_BATCH B USING (ETL_BATCH_ID)
                WHERE B.STATUS = 'COMPLETED'
                UNION ALL
                SELECT N.QUARTER_ID
                FROM ETL_BATCH_ACCESSION A
                JOIN ETL_BATCH B USING (ETL_BATCH_ID)
                JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
                WHERE B.STATUS = 'COMPLETED'
            )
            """
        ).fetchone()[0]
        if latest is None:
            return None
        quarter_id = int(latest)
        expected_count = int(
            connection.execute(
                """
                SELECT SUM(R.SOURCE_FILING_COUNT)
                FROM ETL_BATCH_REPORT_QUARTER R
                JOIN ETL_BATCH B USING (ETL_BATCH_ID)
                WHERE B.STATUS = 'COMPLETED' AND R.QUARTER_ID = ?
                """,
                (quarter_id,),
            ).fetchone()[0]
            or 0
        )
        database_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM NORMALIZED_FILING WHERE QUARTER_ID = ?",
                (quarter_id,),
            ).fetchone()[0]
        )
        missing_count = max(expected_count - database_count, 0)
        if missing_count:
            raise RuntimeError(
                f"bulk coverage check failed for {quarter_id}: "
                f"expected at least {expected_count:,} filings, "
                f"found {database_count:,}"
            )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM DAILY_CIK_HOLDING WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_SUMMARY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CUSIP_QUARTER_SUMMARY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CUSIP_QUARTER_ACTIVITY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CUSIP_OPTION_SUMMARY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_STATUS (
                QUARTER_ID, STATUS, FILING_COUNT, UPDATED_AT,
                LATEST_FILING_DATE, EXPECTED_FILING_COUNT,
                MISSING_FILING_COUNT, COMPLETED_AT
            ) VALUES (
                ?, 'COMPLETE', ?, ?,
                (SELECT MAX(FILING_DATE_ISO) FROM NORMALIZED_FILING
                 WHERE QUARTER_ID = ?), ?, 0, ?
            )
            ON CONFLICT (QUARTER_ID) DO UPDATE SET
                STATUS = 'COMPLETE',
                FILING_COUNT = excluded.FILING_COUNT,
                UPDATED_AT = excluded.UPDATED_AT,
                LATEST_FILING_DATE = excluded.LATEST_FILING_DATE,
                EXPECTED_FILING_COUNT = excluded.EXPECTED_FILING_COUNT,
                MISSING_FILING_COUNT = 0,
                COMPLETED_AT = excluded.COMPLETED_AT
            """,
            (
                quarter_id, database_count, utc_now(), quarter_id,
                expected_count, utc_now(),
            ),
        )
        connection.execute(
            """
            UPDATE DAILY_CIK_QUARTER_STATUS
            SET STATUS = 'COMPLETE', MISSING_FILING_COUNT = 0,
                COMPLETED_AT = COALESCE(COMPLETED_AT, ?), UPDATED_AT = ?
            WHERE QUARTER_ID < ?
            """,
            (utc_now(), utc_now(), quarter_id),
        )
        connection.commit()
        return quarter_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
