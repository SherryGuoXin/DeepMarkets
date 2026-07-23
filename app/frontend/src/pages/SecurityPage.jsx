import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Building2, ChartNoAxesCombined, Search, ShieldCheck, Users } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent, titleCase } from "../format";
import { ValueHistoryChart } from "../components/Charts";
import {
  ActionBadge,
  DataNotice,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Pager,
  QuarterSelect,
  SectionHeader,
  Tabs,
} from "../components/UI";

const HISTORY_TABS = [
  { value: "institutional_value_usd", label: "Institutional value" },
  { value: "institution_count", label: "Holder count" },
  { value: "net_value_change_usd", label: "Net value change" },
  { value: "average_position_value_usd", label: "Average position" },
];

export function SecurityPage() {
  const { cusip } = useParams();
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [historyMetric, setHistoryMetric] = useState("institutional_value_usd");
  const [action, setAction] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("value");
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  const profile = useApi(`/api/securities/${cusip}`, { quarter_id: quarter }, [cusip, quarter]);
  useEffect(() => {
    const actual = profile.data?.snapshot?.QUARTER_ID;
    if (actual && actual !== quarter) setQuarter(actual);
  }, [profile.data, quarter]);
  useEffect(() => setPage(1), [quarter, action, search, sort]);
  const holders = useApi(
    `/api/securities/${cusip}/holders`,
    { quarter_id: quarter, action, search, sort, page, page_size: 25 },
    [cusip, quarter, action, search, sort, page],
  );
  const activity = useMemo(
    () => Object.fromEntries((profile.data?.activity || []).map((item) => [item.action, item])),
    [profile.data],
  );

  if (quarters.loading || !quarter || profile.loading) return <LoadingState />;
  if (quarters.error || profile.error) return <ErrorState error={quarters.error || profile.error} />;
  const { identity, snapshot, history, same_issuer_cusips } = profile.data;
  const historyFormatter = historyMetric.includes("count") ? number : money;

  return (
    <>
      <PageHeader
        back="/securities"
        eyebrow={`Security · CUSIP ${identity.cusip}`}
        title={identity.issuer || "Unnamed security"}
        description={`${identity.title_of_class || "Unclassified"} · ${titleCase(identity.security_type)} · Reports ${identity.first_reportable_quarter || "—"}–${identity.latest_reportable_quarter || "—"}`}
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <section className="metric-grid metric-grid-4">
        <MetricCard label="Institutional value" value={money(snapshot.TOTAL_VALUE_USD)} detail={snapshot.quarter_label} icon={ChartNoAxesCombined} />
        <MetricCard label="Reporting institutions" value={number(snapshot.MANAGER_COUNT)} detail={`${number(activity.NEW?.institution_count || 0)} new`} icon={Users} />
        <MetricCard label="Largest holder" value={snapshot.largest_holder_name || "—"} detail={money(snapshot.LARGEST_MANAGER_VALUE_USD)} icon={Building2} />
        <MetricCard label="Ownership concentration" value={snapshot.MANAGER_CONCENTRATION_HHI?.toFixed(3) || "—"} detail="Manager HHI" icon={ShieldCheck} />
      </section>

      <div className="split-grid">
        <section className="panel">
          <SectionHeader title="Security identity" description="Current values selected from the latest SEC-reported CUSIP variant." />
          <div className="identity-grid">
            <Identity label="CUSIP" value={identity.cusip} />
            <Identity label="FIGI" value={identity.figi} />
            <Identity label="Reported class" value={identity.title_of_class} />
            <Identity label="Security type" value={titleCase(identity.security_type)} />
            <Identity label="Classification" value={titleCase(identity.classification_method)} />
            <Identity label="Confidence" value={percent(identity.classification_confidence)} />
          </div>
          <DataNotice>Ticker, sector and industry are awaiting an issuer-security reference source.</DataNotice>
        </section>
        <section className="panel">
          <SectionHeader title="Ownership activity" description="Distinct reporting managers by inferred action." />
          <div className="activity-grid">
            {["NEW", "ADDED", "REDUCED", "EXITED"].map((key) => (
              <div key={key}>
                <ActionBadge action={key} />
                <strong>{number(activity[key]?.institution_count || 0)}</strong>
                <small>{money(activity[key]?.value_change_usd || 0)} change</small>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <SectionHeader title="Ownership history" description="Aggregated manager reports by quarter." action={<Tabs items={HISTORY_TABS} value={historyMetric} onChange={setHistoryMetric} />} />
        <ValueHistoryChart data={history} dataKey={historyMetric} formatter={historyFormatter} />
      </section>

      {same_issuer_cusips.length > 0 && (
        <section className="panel">
          <SectionHeader title="Same reported issuer" description="Other CUSIPs whose current variant uses the same issuer name." />
          <div className="related-cusips">
            {same_issuer_cusips.map((item) => (
              <Link key={item.cusip} to={`/securities/${item.cusip}`}>
                <strong>{item.cusip}</strong>
                <small>{item.title_of_class || "Unclassified"}</small>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="panel table-panel">
        <SectionHeader title="Institution holders" description={`Managers reporting this CUSIP in ${snapshot.quarter_label}.`} />
        <div className="table-filters">
          <label className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search institution or CIK" /></label>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">All actions</option>
            {["NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED"].map((item) => <option key={item}>{titleCase(item)}</option>)}
          </select>
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="value">Sort by value</option><option value="shares">Sort by shares</option><option value="weight">Sort by weight</option><option value="share_change">Sort by share change</option><option value="institution">Sort alphabetically</option>
          </select>
        </div>
        {holders.loading ? <LoadingState /> : holders.error ? <ErrorState error={holders.error} /> : !holders.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap"><table className="data-table">
              <thead><tr><th>Institution</th><th className="numeric">Shares / amount</th><th className="numeric">Portfolio weight</th><th className="numeric">Market value</th><th className="numeric">Value change</th><th>Action</th></tr></thead>
              <tbody>{holders.data.items.map((item) => (
                <tr key={item.cik}>
                  <td><Link className="entity-link" to={`/relationships/${item.cik}/${cusip}`}><strong>{item.institution_name}</strong><small>CIK {item.cik}</small></Link></td>
                  <td className="numeric">{number(item.reported_amount)}</td><td className="numeric">{percent(item.portfolio_weight)}</td><td className="numeric strong">{money(item.market_value_usd)}</td>
                  <td className={`numeric ${item.value_change_usd > 0 ? "positive" : item.value_change_usd < 0 ? "negative" : ""}`}>{money(item.value_change_usd)}</td><td><ActionBadge action={item.action} /></td>
                </tr>
              ))}</tbody>
            </table></div>
            <Pager page={page} hasMore={holders.data.has_more} onChange={setPage} />
          </>
        )}
      </section>
    </>
  );
}

function Identity({ label, value }) {
  return <div className="identity-item"><span>{label}</span><strong>{value || "—"}</strong></div>;
}
