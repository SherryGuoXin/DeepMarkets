import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, titleCase } from "../format";
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
  { value: "ownership", label: "Largest ownership" },
  { value: "bought", label: "Net bought" },
  { value: "sold", label: "Net sold" },
  { value: "new", label: "Most new investors" },
  { value: "exits", label: "Most exits" },
  { value: "holders", label: "Most widely held" },
  { value: "concentrated", label: "Most concentrated" },
];
const METRIC_SORT = {
  ownership: "institutional_value",
  bought: "net_value_change",
  sold: "net_value_change",
  new: "new_count",
  exits: "exited_count",
  holders: "institutions",
  concentrated: "concentration",
};
const METRIC_DESCRIPTIONS = {
  ownership: {
    label: "Largest ownership",
    detail: "Ranks securities by total quarter-end reported value summed across all filing managers.",
  },
  bought: {
    label: "Net bought",
    detail: "Ranks the largest positive aggregate value change from the prior comparable quarter. Market-price movement can affect this value.",
  },
  sold: {
    label: "Net sold",
    detail: "Ranks the largest negative aggregate value change from the prior comparable quarter. Market-price movement can affect this value.",
  },
  new: {
    label: "Most new investors",
    detail: "Ranks securities by the number of managers reporting a new position relative to the prior comparable quarter.",
  },
  exits: {
    label: "Most exits",
    detail: "Ranks securities by the number of managers whose previously reported position is absent in the selected quarter.",
  },
  holders: {
    label: "Most widely held",
    detail: "Ranks securities by the number of distinct filing managers reporting a position in the selected quarter.",
  },
  concentrated: {
    label: "Most concentrated",
    detail: "Ranks securities by manager value concentration (HHI); a higher score means reported ownership is concentrated among fewer or larger holders.",
  },
};
const RANK_COLUMNS = {
  ownership: {
    label: "Institutional value",
    field: "institutional_value",
    value: (item) => money(item.institutional_value_usd),
  },
  bought: {
    label: "Net value change",
    field: "net_value_change",
    value: (item) => money(item.net_value_change_usd),
  },
  sold: {
    label: "Net value change",
    field: "net_value_change",
    value: (item) => money(item.net_value_change_usd),
  },
  new: {
    label: "New investors",
    field: "new_count",
    value: (item) => number(item.new_investor_count),
  },
  exits: {
    label: "Exited investors",
    field: "exited_count",
    value: (item) => number(item.exited_investor_count),
  },
  holders: {
    label: "Institutions",
    field: "institutions",
    value: (item) => number(item.institution_count),
  },
  concentrated: {
    label: "Concentration HHI",
    field: "concentration",
    value: (item) => item.concentration_hhi === null || item.concentration_hhi === undefined
      ? "—"
      : Number(item.concentration_hhi).toFixed(3),
  },
};
const EMPTY_FILTERS = {
  security_type: "",
  min_value_millions: "",
  max_value_millions: "",
  min_institutions: "",
  max_institutions: "",
  min_net_change_millions: "",
  max_net_change_millions: "",
  min_new: "",
  min_exited: "",
};

export function SecuritiesPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const securityTypes = useApi("/api/meta/security-types", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [metric, setMetric] = useState("ownership");
  const [sortBy, setSortBy] = useState("institutional_value");
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
    "/api/securities",
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
    setDirection(nextMetric === "sold" ? "asc" : "desc");
  };
  const changeSort = (field) => {
    if (field === sortBy) setDirection((value) => value === "desc" ? "asc" : "desc");
    else {
      setSortBy(field);
      setDirection(field === "security" || field === "class" ? "asc" : "desc");
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
  const metricDescription = METRIC_DESCRIPTIONS[metric];
  const rankColumn = RANK_COLUMNS[metric];
  const showInstitutionalValue = metric !== "ownership";
  const showInstitutions = metric !== "holders";
  const showNetValueChange = metric !== "bought" && metric !== "sold";

  return (
    <>
      <PageHeader
        eyebrow="Security directory"
        title="Where institutional ownership is moving"
        description="Aggregate manager-reported positions by CUSIP without assuming that similarly named securities are identical."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <section className="toolbar-panel">
        <Tabs items={METRICS} value={metric} onChange={changeMetric} />
        <label className="search-field">
          <Search size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search issuer or CUSIP" />
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
        <strong>{metricDescription.label}</strong>
        <span>{metricDescription.detail}</span>
      </section>
      {filtersOpen && (
        <form className="filter-panel" onSubmit={applyFilters}>
          <label className="filter-field">
            <span>Security class</span>
            <select value={filterDraft.security_type} onChange={(event) => setFilterDraft({ ...filterDraft, security_type: event.target.value })}>
              <option value="">All classes</option>
              {(securityTypes.data || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <FilterRange label="Institutional value ($M)" minKey="min_value_millions" maxKey="max_value_millions" values={filterDraft} onChange={setFilterDraft} />
          <FilterRange label="Institution count" minKey="min_institutions" maxKey="max_institutions" values={filterDraft} onChange={setFilterDraft} />
          <FilterRange label="Net value change ($M)" minKey="min_net_change_millions" maxKey="max_net_change_millions" values={filterDraft} onChange={setFilterDraft} />
          <label className="filter-field"><span>Minimum new</span><input type="number" min="0" value={filterDraft.min_new} onChange={(event) => setFilterDraft({ ...filterDraft, min_new: event.target.value })} placeholder="Any" /></label>
          <label className="filter-field"><span>Minimum exited</span><input type="number" min="0" value={filterDraft.min_exited} onChange={(event) => setFilterDraft({ ...filterDraft, min_exited: event.target.value })} placeholder="Any" /></label>
          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={clearFilters}><X size={14} /> Clear</button>
            <button type="submit" className="primary-button">Apply filters</button>
          </div>
        </form>
      )}
      <section className="panel table-panel">
        {list.loading ? <LoadingState /> : list.error ? <ErrorState error={list.error} /> : !list.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <SortableHeader label="Rank" field={sortBy} sortBy={sortBy} direction={direction} onSort={changeSort} />
                    <SortableHeader label="Security" field="security" sortBy={sortBy} direction={direction} onSort={changeSort} />
                    <SortableHeader label="Class" field="class" sortBy={sortBy} direction={direction} onSort={changeSort} />
                    <SortableHeader label={rankColumn.label} field={rankColumn.field} sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    {showInstitutionalValue && (
                      <SortableHeader label="Institutional value" field="institutional_value" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {showInstitutions && (
                      <SortableHeader label="Institutions" field="institutions" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {showNetValueChange && (
                      <SortableHeader label="Net value change" field="net_value_change" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                    {metric === "new" ? (
                      <SortableHeader label="Exited investors" field="exited_count" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    ) : metric === "exits" ? (
                      <SortableHeader label="New investors" field="new_count" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    ) : (
                      <SortableHeader label="New / Exited" field="new_exited" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    )}
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((item, index) => (
                    <tr key={item.cusip}>
                      <td className="rank-cell">{(page - 1) * 25 + index + 1}</td>
                      <td>
                        <Link className="entity-link" to={`/securities/${item.cusip}`}>
                          <strong>{item.issuer || "Unnamed security"}</strong>
                          <small>CUSIP {item.cusip}</small>
                        </Link>
                      </td>
                      <td><span className="class-chip">{titleCase(item.security_type)}</span></td>
                      <td className={`numeric strong ${rankColumn.field === "net_value_change" ? (item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : "") : ""}`}>
                        {rankColumn.value(item)}
                      </td>
                      {showInstitutionalValue && <td className="numeric">{money(item.institutional_value_usd)}</td>}
                      {showInstitutions && <td className="numeric">{number(item.institution_count)}</td>}
                      {showNetValueChange && (
                        <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>
                          {money(item.net_value_change_usd)}
                        </td>
                      )}
                      {metric === "new" ? (
                        <td className="numeric">{number(item.exited_investor_count)}</td>
                      ) : metric === "exits" ? (
                        <td className="numeric">{number(item.new_investor_count)}</td>
                      ) : (
                        <td className="numeric">{number(item.new_investor_count)} / {number(item.exited_investor_count)}</td>
                      )}
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
