from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import queries
from .database import database_path, row, rows


app = FastAPI(
    title="13F Intelligence API",
    version="1.0.0",
    description="Read-only API over canonical SEC Form 13F analytical tables.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


INSTITUTION_ORDERS = {
    "portfolio": "S.PORTFOLIO_VALUE_USD",
    "buyers": "COALESCE(A.gross_buy_value_usd, 0)",
    "sellers": "COALESCE(A.gross_sell_value_usd, 0)",
    "new": "COALESCE(A.new_count, 0)",
    "exits": "COALESCE(A.exited_count, 0)",
    "growth": "COALESCE(A.net_value_change_usd, 0)",
    "diversified": "S.CUSIP_COUNT",
    "concentrated": "COALESCE(S.TOP_10_WEIGHT, 0)",
    "institution": "institution_name",
    "portfolio_value": "S.PORTFOLIO_VALUE_USD",
    "holdings": "S.CUSIP_COUNT",
    "net_value_change": "COALESCE(A.net_value_change_usd, 0)",
    "new_exited": "COALESCE(A.new_count, 0) + COALESCE(A.exited_count, 0)",
    "top_10_weight": "COALESCE(S.TOP_10_WEIGHT, 0)",
    "gross_buy": "COALESCE(A.gross_buy_value_usd, 0)",
    "gross_sell": "COALESCE(A.gross_sell_value_usd, 0)",
    "new_count": "COALESCE(A.new_count, 0)",
    "exited_count": "COALESCE(A.exited_count, 0)",
}
SECURITY_ORDERS = {
    "ownership": "S.TOTAL_VALUE_USD",
    "bought": "COALESCE(A.net_value_change_usd, 0)",
    "sold": "-COALESCE(A.net_value_change_usd, 0)",
    "new": "COALESCE(A.new_investor_count, 0)",
    "exits": "COALESCE(A.exited_investor_count, 0)",
    "holders": "S.MANAGER_COUNT",
    "concentrated": "COALESCE(S.MANAGER_CONCENTRATION_HHI, 0)",
    "security": "issuer",
    "class": "T.SECURITY_TYPE_CODE",
    "institutional_value": "S.TOTAL_VALUE_USD",
    "institutions": "S.MANAGER_COUNT",
    "net_value_change": "COALESCE(A.net_value_change_usd, 0)",
    "new_exited": (
        "COALESCE(A.new_investor_count, 0) "
        "+ COALESCE(A.exited_investor_count, 0)"
    ),
    "new_count": "COALESCE(A.new_investor_count, 0)",
    "exited_count": "COALESCE(A.exited_investor_count, 0)",
    "concentration": "COALESCE(S.MANAGER_CONCENTRATION_HHI, 0)",
}
HOLDING_ORDERS = {
    "value": "H.MARKET_VALUE_USD",
    "weight": "COALESCE(H.PORTFOLIO_WEIGHT, 0)",
    "shares": "H.REPORTED_AMOUNT",
    "share_change": "ABS(COALESCE(H.AMOUNT_CHANGE, 0))",
    "value_change": "ABS(COALESCE(H.VALUE_CHANGE_USD, 0))",
    "issuer": "V.CURRENT_NAMEOFISSUER",
}
HOLDER_ORDERS = {
    "value": "H.MARKET_VALUE_USD",
    "shares": "H.REPORTED_AMOUNT",
    "weight": "COALESCE(H.PORTFOLIO_WEIGHT, 0)",
    "share_change": "ABS(H.AMOUNT_CHANGE)",
    "institution": "institution_name",
}


def require_quarter(quarter_id: int | None) -> int:
    if quarter_id is not None:
        return quarter_id
    latest = row(
        "SELECT MAX(QUARTER_ID) AS quarter_id FROM CIK_QUARTER_SUMMARY"
    )
    if not latest or latest["quarter_id"] is None:
        raise HTTPException(404, "No analytical quarters are available")
    return int(latest["quarter_id"])


def paged(data: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": data,
        "page": page,
        "page_size": page_size,
        "has_more": len(data) == page_size,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "database": str(database_path()),
        "read_only": True,
    }


@app.get("/api/meta/quarters")
def quarters() -> list[dict[str, Any]]:
    return rows(queries.QUARTERS)


@app.get("/api/meta/security-types")
def security_types() -> list[dict[str, Any]]:
    return rows(
        "SELECT SECURITY_TYPE_CODE AS value, SECURITY_TYPE_NAME AS label "
        "FROM SECURITY_TYPE ORDER BY SECURITY_TYPE_NAME"
    )


@app.get("/api/overview")
def overview(quarter_id: int | None = None) -> dict[str, Any]:
    selected = require_quarter(quarter_id)
    summary = row(queries.OVERVIEW, (selected,))
    if not summary:
        raise HTTPException(404, "Quarter not found")
    leaders = rows(queries.OVERVIEW_INSTITUTIONS, (selected,))
    securities_list = rows(queries.OVERVIEW_SECURITIES, (selected,))
    return {
        "summary": summary,
        "largest_institutions": leaders,
        "largest_securities": securities_list,
    }


@app.get("/api/search")
def search(q: str = Query(min_length=2, max_length=100)) -> list[dict[str, Any]]:
    pattern = f"%{q.strip()}%"
    return rows(
        queries.GLOBAL_SEARCH,
        (pattern, pattern, pattern, pattern, pattern),
    )


@app.get("/api/institutions")
def institutions(
    quarter_id: int | None = None,
    metric: Literal[
        "portfolio", "buyers", "sellers", "new", "exits", "growth",
        "diversified", "concentrated"
    ] = "portfolio",
    sort_by: Literal[
        "institution", "portfolio_value", "holdings", "net_value_change",
        "new_exited", "top_10_weight", "gross_buy", "gross_sell",
        "new_count", "exited_count"
    ] | None = None,
    direction: Literal["asc", "desc"] = "desc",
    search: str = "",
    min_portfolio_millions: float | None = None,
    max_portfolio_millions: float | None = None,
    min_holdings: int | None = Query(None, ge=0),
    max_holdings: int | None = Query(None, ge=0),
    min_net_change_millions: float | None = None,
    max_net_change_millions: float | None = None,
    min_new: int | None = Query(None, ge=0),
    min_exited: int | None = Query(None, ge=0),
    min_top_10_percent: float | None = Query(None, ge=0, le=100),
    max_top_10_percent: float | None = Query(None, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    selected = require_quarter(quarter_id)
    offset = (page - 1) * page_size
    filter_clauses: list[str] = []
    filter_parameters: list[Any] = []

    def add_filter(expression: str, value: Any) -> None:
        if value is not None:
            filter_clauses.append(f"AND {expression}")
            filter_parameters.append(value)

    add_filter("S.PORTFOLIO_VALUE_USD >= ?", _millions(min_portfolio_millions))
    add_filter("S.PORTFOLIO_VALUE_USD <= ?", _millions(max_portfolio_millions))
    add_filter("S.CUSIP_COUNT >= ?", min_holdings)
    add_filter("S.CUSIP_COUNT <= ?", max_holdings)
    add_filter(
        "COALESCE(A.net_value_change_usd, 0) >= ?",
        _millions(min_net_change_millions),
    )
    add_filter(
        "COALESCE(A.net_value_change_usd, 0) <= ?",
        _millions(max_net_change_millions),
    )
    add_filter("COALESCE(A.new_count, 0) >= ?", min_new)
    add_filter("COALESCE(A.exited_count, 0) >= ?", min_exited)
    add_filter(
        "COALESCE(S.TOP_10_WEIGHT, 0) >= ?",
        _percent(min_top_10_percent),
    )
    add_filter(
        "COALESCE(S.TOP_10_WEIGHT, 0) <= ?",
        _percent(max_top_10_percent),
    )
    order_key = sort_by or metric
    sql = queries.INSTITUTIONS.format(
        order_expression=INSTITUTION_ORDERS[order_key],
        order_direction=direction.upper(),
        filter_clauses="\n  ".join(filter_clauses),
    )
    params = [
        selected,
        search,
        search,
        search,
        search,
        *filter_parameters,
        page_size,
        offset,
    ]
    return paged(rows(sql, params), page, page_size)


@app.get("/api/institutions/{cik}")
def institution_profile(cik: str, quarter_id: int | None = None) -> dict[str, Any]:
    identity = row(queries.INSTITUTION_IDENTITY, (cik,))
    if not identity:
        raise HTTPException(404, "Institution not found")
    selected = require_quarter(quarter_id)
    snapshot = row(queries.INSTITUTION_SNAPSHOT, (cik, selected))
    if not snapshot:
        fallback = row(
            "SELECT MAX(QUARTER_ID) AS quarter_id FROM CIK_QUARTER_SUMMARY "
            "WHERE MANAGER_CIK = ?",
            (cik,),
        )
        if not fallback or fallback["quarter_id"] is None:
            raise HTTPException(404, "Institution has no analytical summaries")
        selected = int(fallback["quarter_id"])
        snapshot = row(queries.INSTITUTION_SNAPSHOT, (cik, selected))
    return {
        "identity": identity,
        "snapshot": snapshot,
        "activity": rows(queries.INSTITUTION_ACTIVITY, (cik, selected)),
        "allocation": rows(queries.INSTITUTION_ALLOCATION, (cik, selected)),
        "history": rows(queries.INSTITUTION_HISTORY, (cik,)),
        "data_availability": {
            "security_ticker": False,
            "issuer_sector": False,
            "market_cap": False,
            "cash_equivalent": False,
            "historical_win_rate": False,
        },
    }


@app.get("/api/institutions/{cik}/holdings")
def institution_holdings(
    cik: str,
    quarter_id: int | None = None,
    action: str = "",
    search: str = "",
    sort: Literal[
        "value", "weight", "shares", "share_change", "value_change", "issuer"
    ] = "value",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    selected = require_quarter(quarter_id)
    normalized_action = action.upper()
    if normalized_action not in {
        "", "NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED", "UNKNOWN"
    }:
        raise HTTPException(422, "Invalid action")
    sql = queries.INSTITUTION_HOLDINGS.format(
        order_expression=HOLDING_ORDERS[sort]
    )
    offset = (page - 1) * page_size
    params = (
        cik,
        selected,
        cik,
        selected,
        normalized_action,
        normalized_action,
        search,
        search,
        search,
        page_size,
        offset,
    )
    return paged(rows(sql, params), page, page_size)


@app.get("/api/securities")
def securities(
    quarter_id: int | None = None,
    metric: Literal[
        "ownership", "bought", "sold", "new", "exits", "holders",
        "concentrated"
    ] = "ownership",
    sort_by: Literal[
        "security", "class", "institutional_value", "institutions",
        "net_value_change", "new_exited", "new_count", "exited_count",
        "concentration"
    ] | None = None,
    direction: Literal["asc", "desc"] = "desc",
    search: str = "",
    security_type: str = "",
    min_value_millions: float | None = None,
    max_value_millions: float | None = None,
    min_institutions: int | None = Query(None, ge=0),
    max_institutions: int | None = Query(None, ge=0),
    min_net_change_millions: float | None = None,
    max_net_change_millions: float | None = None,
    min_new: int | None = Query(None, ge=0),
    min_exited: int | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    selected = require_quarter(quarter_id)
    filter_clauses: list[str] = []
    filter_parameters: list[Any] = []

    def add_filter(expression: str, value: Any) -> None:
        if value is not None and value != "":
            filter_clauses.append(f"AND {expression}")
            filter_parameters.append(value)

    add_filter("T.SECURITY_TYPE_CODE = ?", security_type)
    add_filter("S.TOTAL_VALUE_USD >= ?", _millions(min_value_millions))
    add_filter("S.TOTAL_VALUE_USD <= ?", _millions(max_value_millions))
    add_filter("S.MANAGER_COUNT >= ?", min_institutions)
    add_filter("S.MANAGER_COUNT <= ?", max_institutions)
    add_filter(
        "COALESCE(A.net_value_change_usd, 0) >= ?",
        _millions(min_net_change_millions),
    )
    add_filter(
        "COALESCE(A.net_value_change_usd, 0) <= ?",
        _millions(max_net_change_millions),
    )
    add_filter("COALESCE(A.new_investor_count, 0) >= ?", min_new)
    add_filter("COALESCE(A.exited_investor_count, 0) >= ?", min_exited)
    order_key = sort_by or metric
    sql = queries.SECURITIES.format(
        order_expression=SECURITY_ORDERS[order_key],
        order_direction=direction.upper(),
        filter_clauses="\n  ".join(filter_clauses),
    )
    offset = (page - 1) * page_size
    params = [
        selected,
        search,
        search,
        search,
        *filter_parameters,
        page_size,
        offset,
    ]
    return paged(rows(sql, params), page, page_size)


@app.get("/api/securities/{cusip}")
def security_profile(cusip: str, quarter_id: int | None = None) -> dict[str, Any]:
    identity = row(queries.SECURITY_IDENTITY, (cusip,))
    if not identity:
        raise HTTPException(404, "Security not found")
    selected = require_quarter(quarter_id)
    snapshot = row(queries.SECURITY_SNAPSHOT, (cusip, selected))
    if not snapshot:
        fallback = row(
            "SELECT MAX(S.QUARTER_ID) AS quarter_id "
            "FROM CUSIP_QUARTER_SUMMARY S JOIN CUSIP D USING (CUSIP_ID) "
            "WHERE D.CUSIP = ?",
            (cusip,),
        )
        if not fallback or fallback["quarter_id"] is None:
            raise HTTPException(404, "Security has no analytical summaries")
        selected = int(fallback["quarter_id"])
        snapshot = row(queries.SECURITY_SNAPSHOT, (cusip, selected))
    same_issuer = rows(
        "SELECT CUSIP AS cusip, CURRENT_TITLEOFCLASS AS title_of_class "
        "FROM CUSIP_CURRENT_VARIANT WHERE CURRENT_NAMEOFISSUER = ? "
        "AND CUSIP <> ? ORDER BY CUSIP LIMIT 20",
        (identity["issuer"], cusip),
    )
    return {
        "identity": identity,
        "snapshot": snapshot,
        "activity": rows(queries.SECURITY_ACTIVITY, (cusip, selected)),
        "history": rows(queries.SECURITY_HISTORY, (cusip,)),
        "same_issuer_cusips": same_issuer,
        "data_availability": {
            "ticker": False,
            "sector": False,
            "industry": False,
            "market_cap": False,
        },
    }


@app.get("/api/securities/{cusip}/holders")
def security_holders(
    cusip: str,
    quarter_id: int | None = None,
    action: str = "",
    search: str = "",
    sort: Literal[
        "value", "shares", "weight", "share_change", "institution"
    ] = "value",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    selected = require_quarter(quarter_id)
    normalized_action = action.upper()
    sql = queries.SECURITY_HOLDERS.format(
        order_expression=HOLDER_ORDERS[sort]
    )
    offset = (page - 1) * page_size
    params = (
        selected,
        cusip,
        selected,
        cusip,
        normalized_action,
        normalized_action,
        search,
        search,
        search,
        search,
        page_size,
        offset,
    )
    return paged(rows(sql, params), page, page_size)


@app.get("/api/relationships/{cik}/{cusip}")
def relationship(cik: str, cusip: str) -> dict[str, Any]:
    identity = row(queries.RELATIONSHIP_IDENTITY, (cik, cusip))
    if not identity:
        raise HTTPException(404, "Institution/security relationship not found")
    history = rows(queries.RELATIONSHIP_HISTORY, (cik, cusip))
    current = history[-1] if history else None
    actions = [item for item in history if item["action"] not in ("UNCHANGED", None)]
    held_quarters = sum(1 for item in history if item["market_value_usd"] > 0)
    return {
        "identity": identity,
        "current": current,
        "history": history,
        "statistics": {
            "holding_duration_quarters": held_quarters,
            "consecutive_quarters_held": _consecutive_quarters(history),
            "last_added": _latest_action(actions, {"NEW", "ADDED"}),
            "last_reduced": _latest_action(actions, {"REDUCED"}),
            "largest_position_value_usd": max(
                (item["market_value_usd"] for item in history), default=0
            ),
            "highest_portfolio_weight": max(
                (item["portfolio_weight"] or 0 for item in history), default=0
            ),
        },
    }


def _latest_action(
    history: list[dict[str, Any]], wanted: set[str]
) -> str | None:
    matching = [item["quarter_label"] for item in history if item["action"] in wanted]
    return matching[-1] if matching else None


def _millions(value: float | None) -> int | None:
    return None if value is None else round(value * 1_000_000)


def _percent(value: float | None) -> float | None:
    return None if value is None else value / 100


def _consecutive_quarters(history: list[dict[str, Any]]) -> int:
    count = 0
    previous: int | None = None
    for item in reversed(history):
        current = int(item["quarter_id"])
        if previous is None:
            count = 1
        else:
            previous_year, previous_quarter = divmod(previous, 100)
            expected = (
                (previous_year - 1) * 100 + 4
                if previous_quarter == 1
                else previous_year * 100 + previous_quarter - 1
            )
            if current != expected:
                break
            count += 1
        previous = current
    return count


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> FileResponse:
        requested = FRONTEND_DIST / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
