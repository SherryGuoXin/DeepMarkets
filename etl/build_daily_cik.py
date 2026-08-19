#!/usr/bin/env python3
"""Build institution-only analytics for the latest partial EDGAR quarter."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build(database: Path) -> dict[str, int | None]:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = FILE")
    try:
        connection.executescript(SCHEMA)
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
        completed_analytics_quarter = connection.execute(
            "SELECT MAX(QUARTER_ID) FROM CIK_QUARTER_SUMMARY"
        ).fetchone()[0]
        if (
            completed_analytics_quarter is not None
            and quarter_id <= int(completed_analytics_quarter)
        ):
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM DAILY_CIK_HOLDING WHERE QUARTER_ID <= ?",
                (completed_analytics_quarter,),
            )
            connection.execute(
                "DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE QUARTER_ID <= ?",
                (completed_analytics_quarter,),
            )
            connection.execute(
                "DELETE FROM DAILY_CIK_QUARTER_SUMMARY WHERE QUARTER_ID <= ?",
                (completed_analytics_quarter,),
            )
            connection.execute(
                """
                UPDATE DAILY_CIK_QUARTER_STATUS
                SET STATUS = 'COMPLETE', UPDATED_AT = ?
                WHERE QUARTER_ID <= ?
                """,
                (utc_now(), completed_analytics_quarter),
            )
            connection.commit()
            return {"quarter_id": None, "institutions": 0, "holdings": 0}

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE IF EXISTS temp.DAILY_MANAGER_STAGE")
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
            FROM DAILY_EDGAR_ACCESSION D
            JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
            JOIN QUARTER Q USING (QUARTER_ID)
            JOIN CANONICAL_FILING F
              ON F.MANAGER_CIK = N.MANAGER_CIK
             AND F.QUARTER_ID = N.QUARTER_ID
            WHERE N.QUARTER_ID = ?
            GROUP BY N.MANAGER_CIK, N.QUARTER_ID
            """,
            (quarter_id,),
        )
        connection.execute(
            "CREATE UNIQUE INDEX temp.DAILY_MANAGER_STAGE_PK "
            "ON DAILY_MANAGER_STAGE (MANAGER_CIK, QUARTER_ID)"
        )
        connection.execute(
            """
            CREATE TEMP TABLE DAILY_CURRENT_STAGE AS
            SELECT
                H.MANAGER_CIK,
                H.QUARTER_ID,
                H.CUSIP,
                MAX(H.NAMEOFISSUER) AS ISSUER,
                MAX(H.TITLEOFCLASS) AS TITLE_OF_CLASS,
                CASE UPPER(COALESCE(H.PUTCALL, ''))
                    WHEN 'CALL' THEN 'OPTION_CALL'
                    WHEN 'PUT' THEN 'OPTION_PUT'
                    ELSE COALESCE(T.SECURITY_TYPE_CODE, 'UNKNOWN')
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
                SUM(H.VALUE_USD) AS MARKET_VALUE_USD,
                SUM(H.SSHPRNAMT) AS REPORTED_AMOUNT,
                MAX(CASE
                    WHEN COALESCE(H.VOTING_AUTH_SHARED, 0) > 0 THEN 1
                    ELSE 0
                END) AS HAS_SHARED_DISCRETION,
                MAX(CASE
                    WHEN H.VALUE_RECONCILIATION_STATUS IN (
                        'MATCH', 'ROUNDING_DIFFERENCE'
                    )
                        THEN 0 ELSE 1
                END) AS HAS_VALUE_ISSUE
            FROM ANALYTICS_HOLDING_LINE H
            JOIN DAILY_MANAGER_STAGE M
              ON M.MANAGER_CIK = H.MANAGER_CIK
             AND M.QUARTER_ID = H.QUARTER_ID
            LEFT JOIN CUSIP D ON D.CUSIP = H.CUSIP
            LEFT JOIN CUSIP_CLASSIFICATION CC USING (CUSIP_ID)
            LEFT JOIN SECURITY_TYPE T USING (SECURITY_TYPE_ID)
            GROUP BY
                H.MANAGER_CIK,
                H.QUARTER_ID,
                H.CUSIP,
                SECURITY_TYPE,
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

        connection.execute("DELETE FROM DAILY_CIK_HOLDING WHERE QUARTER_ID = ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE QUARTER_ID = ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_SUMMARY WHERE QUARTER_ID = ?", (quarter_id,))
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
            """,
            (quarter_id,),
        )
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_ACTIVITY
            SELECT
                MANAGER_CIK, QUARTER_ID,
                SUM(ACTION = 'NEW'), SUM(ACTION = 'ADDED'),
                SUM(ACTION = 'REDUCED'), SUM(ACTION = 'EXITED'),
                SUM(CASE WHEN ACTION IN ('NEW', 'ADDED')
                    THEN MAX(VALUE_CHANGE_USD, 0) ELSE 0 END),
                SUM(CASE WHEN ACTION IN ('REDUCED', 'EXITED')
                    THEN ABS(MIN(VALUE_CHANGE_USD, 0)) ELSE 0 END),
                SUM(ABS(VALUE_CHANGE_USD)), SUM(VALUE_CHANGE_USD)
            FROM DAILY_CIK_HOLDING
            WHERE QUARTER_ID = ?
            GROUP BY MANAGER_CIK, QUARTER_ID
            """,
            (quarter_id,),
        )
        filing_count = connection.execute(
            """
            SELECT COUNT(DISTINCT D.ACCESSION_NUMBER)
            FROM DAILY_EDGAR_ACCESSION D
            JOIN NORMALIZED_FILING N USING (ACCESSION_NUMBER)
            WHERE N.QUARTER_ID = ?
            """,
            (quarter_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO DAILY_CIK_QUARTER_STATUS
                (QUARTER_ID, STATUS, FILING_COUNT, UPDATED_AT)
            VALUES (?, 'PARTIAL', ?, ?)
            ON CONFLICT (QUARTER_ID) DO UPDATE SET
                STATUS = 'PARTIAL',
                FILING_COUNT = excluded.FILING_COUNT,
                UPDATED_AT = excluded.UPDATED_AT
            """,
            (quarter_id, filing_count, built_at),
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
        }
        return counts
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
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM DAILY_CIK_HOLDING WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_ACTIVITY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute("DELETE FROM DAILY_CIK_QUARTER_SUMMARY WHERE QUARTER_ID <= ?", (quarter_id,))
        connection.execute(
            """
            UPDATE DAILY_CIK_QUARTER_STATUS
            SET STATUS = 'COMPLETE', UPDATED_AT = ?
            WHERE QUARTER_ID <= ?
            """,
            (utc_now(), quarter_id),
        )
        connection.commit()
        return quarter_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
