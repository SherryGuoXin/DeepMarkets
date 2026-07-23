import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent } from "../format";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pager,
  QuarterSelect,
  Tabs,
} from "../components/UI";

const METRICS = [
  { value: "portfolio", label: "Largest portfolios" },
  { value: "buyers", label: "Net buyers" },
  { value: "sellers", label: "Net sellers" },
  { value: "new", label: "New positions" },
  { value: "exits", label: "Exits" },
  { value: "growth", label: "Portfolio growth" },
  { value: "diversified", label: "Most diversified" },
  { value: "concentrated", label: "Most concentrated" },
];

export function InstitutionsPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [metric, setMetric] = useState("portfolio");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  useEffect(() => setPage(1), [metric, quarter, search]);
  const list = useApi(
    "/api/institutions",
    { quarter_id: quarter, metric, search, page, page_size: 25 },
    [quarter, metric, search, page],
  );

  if (quarters.loading || !quarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;

  return (
    <>
      <PageHeader
        eyebrow="Institution directory"
        title="How managers are allocating capital"
        description="Rank filing managers, compare quarterly activity and open any portfolio for position-level history."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <section className="toolbar-panel">
        <Tabs items={METRICS} value={metric} onChange={setMetric} />
        <label className="search-field">
          <Search size={17} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search institution or CIK"
          />
        </label>
      </section>

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
                    <th>Rank</th>
                    <th>Institution</th>
                    <th className="numeric">Portfolio value</th>
                    <th className="numeric">Holdings</th>
                    <th className="numeric">Net value change</th>
                    <th className="numeric">New / Exited</th>
                    <th className="numeric">Top 10 weight</th>
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
                      <td className="numeric strong">{money(item.portfolio_value_usd)}</td>
                      <td className="numeric">{number(item.holding_count)}</td>
                      <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>
                        {money(item.net_value_change_usd)}
                      </td>
                      <td className="numeric">{number(item.new_count)} / {number(item.exited_count)}</td>
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
