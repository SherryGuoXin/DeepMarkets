import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent } from "../format";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pager,
  QuarterSelect,
  SortableHeader,
  Tabs,
} from "../components/UI";

const METRICS = [
  { value: "portfolio", label: "Largest portfolios" },
  { value: "buyers", label: "Largest gross buys" },
  { value: "sellers", label: "Largest gross sells" },
  { value: "new", label: "New positions" },
  { value: "exits", label: "Exits" },
  { value: "growth", label: "Portfolio growth" },
  { value: "diversified", label: "Most diversified" },
  { value: "concentrated", label: "Most concentrated" },
];
const METRIC_SORT = {
  portfolio: "portfolio_value",
  buyers: "gross_buy",
  sellers: "gross_sell",
  new: "new_count",
  exits: "exited_count",
  growth: "net_value_change",
  diversified: "holdings",
  concentrated: "top_10_weight",
};
const SPECIAL_RANK_BASIS_COLUMNS = new Set([
  "gross_buy",
  "gross_sell",
  "new_count",
  "exited_count",
]);
const RANK_BASIS = {
  portfolio_value: {
    label: "Portfolio value",
    detail: "Total reported portfolio value in the selected quarter.",
    value: (item) => money(item.portfolio_value_usd),
  },
  gross_buy: {
    label: "Gross buy value",
    detail: "Reported value increase from NEW and ADDED positions; not share count.",
    value: (item) => money(item.gross_buy_value_usd),
  },
  gross_sell: {
    label: "Gross sell value",
    detail: "Absolute reported value decrease from REDUCED and EXITED positions; not share count.",
    value: (item) => money(item.gross_sell_value_usd),
  },
  new_count: {
    label: "New position count",
    detail: "Count of CIK-instrument relationships that appear this quarter but not the prior comparable quarter.",
    value: (item) => number(item.new_count),
  },
  exited_count: {
    label: "Exit count",
    detail: "Count of CIK-instrument relationships present in the prior comparable quarter but absent this quarter.",
    value: (item) => number(item.exited_count),
  },
  net_value_change: {
    label: "Net value change",
    detail: "Comparable current value minus prior value across the manager's changed relationships.",
    value: (item) => money(item.net_value_change_usd),
  },
  holdings: {
    label: "Holding count",
    detail: "Number of distinct CUSIPs in the selected quarter.",
    value: (item) => number(item.holding_count),
  },
  top_10_weight: {
    label: "Top 10 weight",
    detail: "Share of portfolio value represented by the ten largest positions.",
    value: (item) => percent(item.top_10_weight),
  },
  new_exited: {
    label: "New plus exited",
    detail: "Combined count of new and exited CIK-instrument relationships.",
    value: (item) => number((item.new_count || 0) + (item.exited_count || 0)),
  },
  institution: {
    label: "Institution name",
    detail: "Alphabetical institution name order.",
    value: (item) => item.institution_name,
  },
};
const EMPTY_FILTERS = {
  min_portfolio_millions: "",
  max_portfolio_millions: "",
  min_holdings: "",
  max_holdings: "",
  min_net_change_millions: "",
  max_net_change_millions: "",
  min_new: "",
  min_exited: "",
  min_top_10_percent: "",
  max_top_10_percent: "",
};

export function InstitutionsPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [metric, setMetric] = useState("portfolio");
  const [sortBy, setSortBy] = useState("portfolio_value");
  const [direction, setDirection] = useState("desc");
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterDraft, setFilterDraft] = useState(EMPTY_FILTERS);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  useEffect(() => setPage(1), [metric, quarter, search, sortBy, direction, filters]);
  const list = useApi(
    "/api/institutions",
    {
      quarter_id: quarter,
      metric,
      sort_by: sortBy,
      direction,
      search,
      ...filters,
      page,
      page_size: 25,
    },
    [quarter, metric, sortBy, direction, search, JSON.stringify(filters), page],
  );
  const activeFilterCount = Object.values(filters).filter((value) => value !== "").length;
  const changeMetric = (nextMetric) => {
    setMetric(nextMetric);
    setSortBy(METRIC_SORT[nextMetric]);
    setDirection("desc");
  };
  const changeSort = (field) => {
    if (field === sortBy) setDirection((value) => value === "desc" ? "asc" : "desc");
    else {
      setSortBy(field);
      setDirection(field === "institution" ? "asc" : "desc");
    }
  };
  const applyFilters = (event) => {
    event.preventDefault();
    setFilters(filterDraft);
  };
  const clearFilters = () => {
    setFilterDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
  };

  if (quarters.loading || !quarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;
  const rankBasis = RANK_BASIS[sortBy] || RANK_BASIS[METRIC_SORT[metric]];
  const metricSort = METRIC_SORT[metric];
  const metricBasis = RANK_BASIS[metricSort];
  const showRankBasisColumn =
    SPECIAL_RANK_BASIS_COLUMNS.has(metricSort);
  const isGrowthTab = metric === "growth";
  const showNewColumn = metric !== "new";
  const showExitedColumn = metric !== "exits";

  return (
    <>
      <PageHeader
        eyebrow="Institution directory"
        title="How managers are allocating capital"
        description="Rank filing managers, compare quarterly activity and open any portfolio for position-level history."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <section className="toolbar-panel">
        <Tabs items={METRICS} value={metric} onChange={changeMetric} />
        <label className="search-field">
          <Search size={17} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search institution or CIK"
          />
        </label>
        <button
          className={`filter-button ${filtersOpen ? "active" : ""}`}
          onClick={() => setFiltersOpen((value) => !value)}
        >
          <SlidersHorizontal size={15} />
          Filters
          {activeFilterCount > 0 && <b>{activeFilterCount}</b>}
        </button>
      </section>
      <section className="rank-basis-note">
        <strong>Rank basis: {rankBasis.label}</strong>
        <span>{rankBasis.detail}</span>
      </section>
      {filtersOpen && (
        <form className="filter-panel" onSubmit={applyFilters}>
          <FilterRange label="Portfolio value ($M)" minKey="min_portfolio_millions" maxKey="max_portfolio_millions" values={filterDraft} onChange={setFilterDraft} />
          <FilterRange label="Holdings" minKey="min_holdings" maxKey="max_holdings" values={filterDraft} onChange={setFilterDraft} />
          <FilterRange label="Net value change ($M)" minKey="min_net_change_millions" maxKey="max_net_change_millions" values={filterDraft} onChange={setFilterDraft} />
          <FilterRange label="Top 10 weight (%)" minKey="min_top_10_percent" maxKey="max_top_10_percent" values={filterDraft} onChange={setFilterDraft} />
          <label className="filter-field"><span>Minimum new</span><input type="number" min="0" value={filterDraft.min_new} onChange={(event) => setFilterDraft({ ...filterDraft, min_new: event.target.value })} placeholder="Any" /></label>
          <label className="filter-field"><span>Minimum exited</span><input type="number" min="0" value={filterDraft.min_exited} onChange={(event) => setFilterDraft({ ...filterDraft, min_exited: event.target.value })} placeholder="Any" /></label>
          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={clearFilters}><X size={14} /> Clear</button>
            <button type="submit" className="primary-button">Apply filters</button>
          </div>
        </form>
      )}

      <section className="panel table-panel">
        {list.loading ? (
          <LoadingState />
        ) : list.error ? (
          <ErrorState error={list.error} />
        ) : !list.data.items.length ? (
          <EmptyState />
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <SortableHeader label="Institution" field="institution" sortBy={sortBy} direction={direction} onSort={changeSort} />
                    {isGrowthTab && (
                      <SortableHeader label="Net value change" field="net_value_change" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {showRankBasisColumn && (
                      <SortableHeader label={metricBasis.label} field={metricSort} sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    <SortableHeader label="Portfolio value" field="portfolio_value" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    <SortableHeader label="Holdings" field="holdings" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    {!isGrowthTab && (
                      <SortableHeader label="Net value change" field="net_value_change" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {showNewColumn && (
                      <SortableHeader label="New" field="new_count" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {showExitedColumn && (
                      <SortableHeader label="Exited" field="exited_count" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    <SortableHeader label="Top 10 weight" field="top_10_weight" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((item, index) => (
                    <tr key={item.cik}>
                      <td className="rank-cell">{(page - 1) * 25 + index + 1}</td>
                      <td>
                        <Link className="entity-link" to={`/institutions/${item.cik}`}>
                          <strong>{item.institution_name}</strong>
                          <small>CIK {item.cik} · {item.quarter_label}</small>
                        </Link>
                      </td>
                      {isGrowthTab && (
                        <td className={`numeric strong ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>
                          {money(item.net_value_change_usd)}
                        </td>
                      )}
                      {showRankBasisColumn && (
                        <td className="numeric strong">{metricBasis.value(item)}</td>
                      )}
                      <td className={`numeric ${isGrowthTab ? "" : "strong"}`}>{money(item.portfolio_value_usd)}</td>
                      <td className="numeric">{number(item.holding_count)}</td>
                      {!isGrowthTab && (
                        <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>
                          {money(item.net_value_change_usd)}
                        </td>
                      )}
                      {showNewColumn && <td className="numeric">{number(item.new_count)}</td>}
                      {showExitedColumn && <td className="numeric">{number(item.exited_count)}</td>}
                      <td className="numeric">{percent(item.top_10_weight)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} hasMore={list.data.has_more} onChange={setPage} />
          </>
        )}
      </section>
    </>
  );
}

function FilterRange({ label, minKey, maxKey, values, onChange }) {
  return (
    <div className="filter-range">
      <span>{label}</span>
      <div>
        <input type="number" value={values[minKey]} onChange={(event) => onChange({ ...values, [minKey]: event.target.value })} placeholder="Min" />
        <i>to</i>
        <input type="number" value={values[maxKey]} onChange={(event) => onChange({ ...values, [maxKey]: event.target.value })} placeholder="Max" />
      </div>
    </div>
  );
}
