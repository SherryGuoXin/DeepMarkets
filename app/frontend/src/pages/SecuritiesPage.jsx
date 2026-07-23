import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, titleCase } from "../format";
import {
  DataNotice,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pager,
  QuarterSelect,
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

export function SecuritiesPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [metric, setMetric] = useState("ownership");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  useEffect(() => setPage(1), [metric, quarter, search]);
  const list = useApi(
    "/api/securities",
    { quarter_id: quarter, metric, search, page, page_size: 25 },
    [quarter, metric, search, page],
  );
  if (quarters.loading || !quarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;

  return (
    <>
      <PageHeader
        eyebrow="Security directory"
        title="Where institutional ownership is moving"
        description="Aggregate manager-reported positions by CUSIP without assuming that similarly named securities are identical."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <DataNotice>
        Held-security ticker and issuer sector mappings are not in the current source data.
        CUSIP and current SEC-reported issuer name remain authoritative.
      </DataNotice>
      <section className="toolbar-panel">
        <Tabs items={METRICS} value={metric} onChange={setMetric} />
        <label className="search-field">
          <Search size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search issuer or CUSIP" />
        </label>
      </section>
      <section className="panel table-panel">
        {list.loading ? <LoadingState /> : list.error ? <ErrorState error={list.error} /> : !list.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Security</th>
                    <th>Class</th>
                    <th className="numeric">Institutional value</th>
                    <th className="numeric">Institutions</th>
                    <th className="numeric">Net value change</th>
                    <th className="numeric">New / Exited</th>
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
                      <td className="numeric strong">{money(item.institutional_value_usd)}</td>
                      <td className="numeric">{number(item.institution_count)}</td>
                      <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>
                        {money(item.net_value_change_usd)}
                      </td>
                      <td className="numeric">{number(item.new_investor_count)} / {number(item.exited_investor_count)}</td>
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
