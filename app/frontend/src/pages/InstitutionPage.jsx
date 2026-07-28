import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Activity,
  Building2,
  ChartNoAxesCombined,
  Layers3,
  Search,
  Trophy,
} from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent, signedPercent, titleCase } from "../format";
import { ActivityChart, AllocationChart, ValueHistoryChart } from "../components/Charts";
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
  SortableHeader,
  Tabs,
} from "../components/UI";

const HISTORY_TABS = [
  { value: "portfolio_value_usd", label: "Portfolio value" },
  { value: "holding_count", label: "Holdings count" },
  { value: "turnover_rate", label: "Turnover" },
  { value: "top_10_weight", label: "Top 10 weight" },
];
const ACTIONS = ["", "NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED"];

export function InstitutionPage() {
  const { cik } = useParams();
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [historyMetric, setHistoryMetric] = useState("portfolio_value_usd");
  const [action, setAction] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("value");
  const [direction, setDirection] = useState("desc");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);
  const profile = useApi(
    `/api/institutions/${cik}`,
    { quarter_id: quarter },
    [cik, quarter],
  );
  useEffect(() => {
    const actual = profile.data?.snapshot?.QUARTER_ID;
    if (actual && actual !== quarter) setQuarter(actual);
  }, [profile.data, quarter]);
  useEffect(() => setPage(1), [quarter, action, search, sortBy, direction]);
  const holdings = useApi(
    `/api/institutions/${cik}/holdings`,
    { quarter_id: quarter, action, search, sort: sortBy, direction, page, page_size: 25 },
    [cik, quarter, action, search, sortBy, direction, page],
  );
  const changeSort = (field) => {
    if (field === sortBy) {
      setDirection((value) => value === "desc" ? "asc" : "desc");
    } else {
      setSortBy(field);
      setDirection(field === "issuer" || field === "action" ? "asc" : "desc");
    }
  };

  const activity = useMemo(
    () => Object.fromEntries((profile.data?.activity || []).map((item) => [item.action, item])),
    [profile.data],
  );
  const behavior = useMemo(() => {
    const history = profile.data?.history || [];
    if (!history.length) return {};
    const averageTurnover =
      history.reduce((sum, item) => sum + (item.turnover_rate || 0), 0) / history.length;
    const averagePosition =
      history.reduce((sum, item) => sum + (item.average_position_value_usd || 0), 0) / history.length;
    const buys = history.reduce((sum, item) => sum + Math.max(item.net_value_change_usd || 0, 0), 0);
    const sells = history.reduce((sum, item) => sum + Math.abs(Math.min(item.net_value_change_usd || 0, 0)), 0);
    return {
      averageTurnover,
      averagePosition,
      buySellRatio: sells ? buys / sells : null,
      diversification: profile.data.snapshot.CUSIP_COUNT
        ? 1 - (profile.data.snapshot.TOP_10_WEIGHT || 0)
        : null,
    };
  }, [profile.data]);

  if (quarters.loading || !quarter || profile.loading) return <LoadingState />;
  if (quarters.error || profile.error) return <ErrorState error={quarters.error || profile.error} />;
  const { identity, snapshot, allocation, history } = profile.data;
  const activityTotal = ["NEW", "ADDED", "REDUCED", "EXITED"].reduce(
    (sum, key) => sum + (activity[key]?.position_count || 0),
    0,
  );
  const historyFormatter =
    historyMetric.includes("weight") || historyMetric.includes("turnover")
      ? percent
      : historyMetric.includes("count")
        ? number
        : money;

  return (
    <>
      <PageHeader
        back="/institutions"
        eyebrow={`Institution · CIK ${identity.cik}`}
        title={identity.institution_name}
        description={[
          identity.city,
          identity.state_or_country,
          `Reports ${identity.first_reportable_quarter || "—"}–${identity.latest_reportable_quarter || "—"}`,
        ].filter(Boolean).join(" · ")}
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />

      <section className="metric-grid metric-grid-4">
        <MetricCard label="Portfolio value" value={money(snapshot.PORTFOLIO_VALUE_USD)} detail={snapshot.quarter_label} icon={ChartNoAxesCombined} />
        <MetricCard label="Holdings" value={number(snapshot.CUSIP_COUNT)} detail={`${number(snapshot.INSTRUMENT_COUNT)} instruments`} icon={Layers3} />
        <MetricCard label="Largest position" value={money(snapshot.LARGEST_POSITION_VALUE_USD)} detail={snapshot.largest_holding_issuer || snapshot.largest_holding_cusip} icon={Trophy} />
        <MetricCard label="Top 10 weight" value={percent(snapshot.TOP_10_WEIGHT)} detail={`Largest ${percent(snapshot.LARGEST_POSITION_WEIGHT)}`} icon={Activity} />
      </section>

      <section className="panel">
        <SectionHeader title="Identity" description="Current manager attributes and SEC filing identity." />
        <div className="identity-grid">
          <IdentityItem label="CIK" value={identity.cik} />
          <IdentityItem label="SEC company name" value={identity.sec_company_name} />
          <IdentityItem label="13F file number" value={identity.form_13f_file_number} />
          <IdentityItem label="First reportable quarter" value={identity.first_reportable_quarter} />
          <IdentityItem label="Latest reportable quarter" value={identity.latest_reportable_quarter} />
          <IdentityItem
            label="Current address"
            value={[identity.street_1, identity.street_2, identity.city, identity.state_or_country, identity.postal_code].filter(Boolean).join(", ")}
            wide
          />
          <IdentityItem
            label="Latest SEC filing"
            value={identity.latest_accession_number}
            href={identity.latest_accession_number ? `https://www.sec.gov/Archives/edgar/data/${Number(identity.cik)}/${identity.latest_accession_number.replaceAll("-", "")}/` : null}
          />
        </div>
      </section>

      <div className="split-grid">
        <section className="panel">
          <SectionHeader title="Quarterly activity" description="Position actions are classified by reported amount, not price movement." />
          {activityTotal ? (
            <div className="activity-grid">
              {["NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED"].map((key) => (
                <div key={key}>
                  <ActionBadge action={key} />
                  <strong>{number(activity[key]?.position_count || 0)}</strong>
                  <small>{money(activity[key]?.value_change_usd || 0)} value change</small>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No comparable prior quarter" detail="This quarter still has a complete current snapshot." />
          )}
        </section>
        <section className="panel">
          <SectionHeader title="Asset type allocation" description="Reported value by classified instrument type." />
          <AllocationChart data={allocation} />
        </section>
      </div>

      <section className="panel">
        <SectionHeader title="Portfolio behavior" description="Derived from available analytics-ready quarters." />
        <div className="metric-grid metric-grid-4 metric-grid-compact">
          <MetricCard label="Average turnover" value={percent(behavior.averageTurnover)} detail="Across available comparisons" />
          <MetricCard label="Average position" value={money(behavior.averagePosition)} detail="Historical average" />
          <MetricCard label="Buy / sell ratio" value={behavior.buySellRatio === null ? "—" : behavior.buySellRatio.toFixed(2)} detail="Value-change proxy" />
          <MetricCard label="Diversification score" value={percent(behavior.diversification)} detail="1 − top 10 weight" />
        </div>
      </section>

      <section className="panel">
        <SectionHeader title="Portfolio history" description="Quarter-end reported values and behavior." action={<Tabs items={HISTORY_TABS} value={historyMetric} onChange={setHistoryMetric} />} />
        <ValueHistoryChart data={history} dataKey={historyMetric} formatter={historyFormatter} />
        <div className="chart-divider" />
        <h3 className="subchart-title">New positions and exits</h3>
        <ActivityChart data={history} />
      </section>

      <section className="panel table-panel">
        <SectionHeader title="Holdings" description={`Current positions reported for ${snapshot.quarter_label}.`} />
        <div className="table-filters">
          <label className="search-field">
            <Search size={17} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search issuer or CUSIP" />
          </label>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            {ACTIONS.map((item) => <option key={item} value={item}>{item ? titleCase(item) : "All actions"}</option>)}
          </select>
        </div>
        {holdings.loading ? <LoadingState /> : holdings.error ? <ErrorState error={holdings.error} /> : !holdings.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <SortableHeader label="Security" field="issuer" sortBy={sortBy} direction={direction} onSort={changeSort} />
                    <th>Class</th>
                    <SortableHeader label="Value" field="value" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    <SortableHeader label="Shares / amount" field="shares" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    <SortableHeader label="Weight" field="weight" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    <SortableHeader label="Change" field="share_change" sortBy={sortBy} direction={direction} onSort={changeSort} numeric />
                    <SortableHeader label="Action" field="action" sortBy={sortBy} direction={direction} onSort={changeSort} />
                  </tr>
                </thead>
                <tbody>
                  {holdings.data.items.map((item, index) => (
                    <tr key={`${item.cusip}-${item.option_type}-${index}`}>
                      <td><Link className="entity-link" to={`/relationships/${cik}/${item.cusip}`}><strong>{item.issuer || "Unnamed security"}</strong><small>{item.cusip} · {item.title_of_class || "—"}</small></Link></td>
                      <td><span className="class-chip">{titleCase(item.security_type)}</span></td>
                      <td className="numeric strong">{money(item.market_value_usd)}</td>
                      <td className="numeric">{number(item.reported_amount)} <small>{item.amount_type}</small></td>
                      <td className="numeric">{percent(item.portfolio_weight)}</td>
                      <td className={`numeric ${item.amount_change > 0 ? "positive" : item.amount_change < 0 ? "negative" : ""}`}>{number(item.amount_change)}<small className="block">{signedPercent(item.amount_change_percent)}</small></td>
                      <td><ActionBadge action={item.action} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} hasMore={holdings.data.has_more} onChange={setPage} />
          </>
        )}
      </section>

      <DataNotice>
        Sector, industry and market-cap allocation require an issuer-level CUSIP mapping source.
        The existing CIK SIC data describes filing entities and is intentionally not joined to held securities.
      </DataNotice>
    </>
  );
}

function IdentityItem({ label, value, href, wide }) {
  return (
    <div className={wide ? "identity-item identity-wide" : "identity-item"}>
      <span>{label}</span>
      {href ? <a href={href} target="_blank" rel="noreferrer">{value || "—"}</a> : <strong>{value || "—"}</strong>}
    </div>
  );
}
