import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, titleCase } from "../format";
import {
  ActionBadge,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pager,
  QuarterSelect,
  SectionHeader,
  Tabs,
} from "../components/UI";

const ACTIONS = [
  { value: "NEW", label: "New" },
  { value: "EXITED", label: "Exited" },
  { value: "ADDED", label: "Added" },
  { value: "REDUCED", label: "Reduced" },
  { value: "", label: "All" },
];

export function ActivityPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [action, setAction] = useState("NEW");
  const [search, setSearch] = useState("");
  const [cik, setCik] = useState("");
  const [cusip, setCusip] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  useEffect(() => setPage(1), [quarter, action, search, cik, cusip]);

  const activity = useApi(
    "/api/activity",
    { quarter_id: quarter, action, search, cik, cusip, page, page_size: 25 },
    [quarter, action, search, cik, cusip, page],
  );

  if (quarters.loading || !quarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;

  return (
    <>
      <PageHeader
        eyebrow="Position activity"
        title="Explore new, exited and changed positions"
        description="Browse relationship-level motion from adjacent-quarter comparisons across institutions and CUSIPs."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />

      <section className="toolbar-panel activity-toolbar">
        <Tabs items={ACTIONS} value={action} onChange={setAction} />
        <label className="search-field">
          <Search size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search CIK, institution, CUSIP or issuer" />
        </label>
        <input className="compact-input" value={cik} onChange={(event) => setCik(event.target.value)} placeholder="CIK filter" />
        <input className="compact-input" value={cusip} onChange={(event) => setCusip(event.target.value)} placeholder="CUSIP filter" />
      </section>

      <section className="panel table-panel">
        <SectionHeader title={`${titleCase(action || "all")} activity`} description="Sorted by largest absolute reported value change." />
        {activity.loading ? <LoadingState /> : activity.error ? <ErrorState error={activity.error} /> : !activity.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Institution</th>
                    <th>Security</th>
                    <th>Class</th>
                    <th>Action</th>
                    <th className="numeric">Prior value</th>
                    <th className="numeric">Current value</th>
                    <th className="numeric">Value change</th>
                    <th className="numeric">Amount change</th>
                  </tr>
                </thead>
                <tbody>
                  {activity.data.items.map((item, index) => (
                    <tr key={`${item.cik}-${item.cusip}-${index}`}>
                      <td>
                        <Link className="entity-link" to={`/institutions/${item.cik}`}>
                          <strong>{item.institution_name}</strong>
                          <small>CIK {item.cik}</small>
                        </Link>
                      </td>
                      <td>
                        <Link className="entity-link" to={`/relationships/${item.cik}/${item.cusip}`}>
                          <strong>{item.issuer || "Unnamed security"}</strong>
                          <small>{item.cusip} · {item.title_of_class || "—"}</small>
                        </Link>
                      </td>
                      <td><span className="class-chip">{titleCase(item.security_type)}</span></td>
                      <td><ActionBadge action={item.action} /></td>
                      <td className="numeric">{money(item.prior_value_usd)}</td>
                      <td className="numeric">{money(item.current_value_usd)}</td>
                      <td className={`numeric ${item.value_change_usd > 0 ? "positive" : item.value_change_usd < 0 ? "negative" : ""}`}>{money(item.value_change_usd)}</td>
                      <td className="numeric">{number(item.amount_change)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} hasMore={activity.data.has_more} onChange={setPage} />
          </>
        )}
      </section>
    </>
  );
}
