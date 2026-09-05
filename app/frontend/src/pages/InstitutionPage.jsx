import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Activity,
  ChartNoAxesCombined,
  Layers3,
  Search,
  Trophy,
} from "lucide-react";
import { useApi } from "../hooks";
import { actionLabel, money, number, percent, signedPercent, titleCase } from "../format";
import { ActivityChart, ValueHistoryChart } from "../components/Charts";
import {
  ActionBadge,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Pager,
  QuarterSelect,
  QuarterlyDataNotice,
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
  const quarters = useApi("/api/meta/institution-quarters", {}, []);
  const securityTypes = useApi("/api/meta/security-types", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [historyMetric, setHistoryMetric] = useState("portfolio_value_usd");
  const [action, setAction] = useState("");
  const [securityType, setSecurityType] = useState("");
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
    quarter !== null,
  );
  useEffect(() => {
    const actual = profile.data?.snapshot?.QUARTER_ID;
    if (actual) setQuarter((current) => actual !== current ? actual : current);
  }, [profile.data]);
  useEffect(() => setPage(1), [quarter, action, securityType, search, sortBy, direction]);
  const holdings = useApi(
    `/api/institutions/${cik}/holdings`,
    {
      quarter_id: quarter,
      action,
      security_type: securityType,
      search,
      sort: sortBy,
      direction,
      page,
      page_size: 25,
    },
    [cik, quarter, action, securityType, search, sortBy, direction, page],
    quarter !== null,
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

  if (quarters.loading || !quarter || profile.loading) return <LoadingState />;
  if (quarters.error || profile.error) return <ErrorState error={quarters.error || profile.error} />;
  const { identity, snapshot, history, notable_people: notablePeople = [] } = profile.data;
  const availableQuarterIds = new Set(history.map((item) => item.quarter_id));
  const availableQuarters = quarters.data.filter(
    (item) => availableQuarterIds.has(item.quarter_id),
  );
  const notablePeopleNames = notablePeople.map((person) => person.name).filter(Boolean).join(", ");
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
        actions={<QuarterSelect quarters={availableQuarters} value={quarter} onChange={setQuarter} />}
      />

      <section className="panel">
        <SectionHeader title="Identity" description="Current manager attributes and SEC filing identity." />
        <div className="identity-grid">
          <IdentityItem label="CIK" value={identity.cik} />
          <IdentityItem
            label={notablePeopleNames ? "Notable people" : "13F file number"}
            value={notablePeopleNames || identity.form_13f_file_number}
          />
          <IdentityItem label="First reportable quarter" value={identity.first_reportable_quarter} />
          <IdentityItem label="Latest reportable quarter" value={identity.latest_reportable_quarter} />
          <IdentityItem
            label="Current address"
            value={[identity.street_1, identity.street_2, identity.city, identity.state_or_country, identity.postal_code].filter(Boolean).join(", ")}
          />
          <IdentityItem
            label="Latest SEC filing"
            value={identity.latest_accession_number}
            href={identity.latest_accession_number ? `https://www.sec.gov/Archives/edgar/data/${Number(identity.cik)}/${identity.latest_accession_number.replaceAll("-", "")}/` : null}
          />
        </div>
      </section>

      <section className="panel">
        <SectionHeader title={`${snapshot.quarter_label} filing summary`} description="Portfolio totals and reporting changes for the selected quarter." />
        <QuarterlyDataNotice quarterId={quarter} />
        <div className="metric-grid metric-grid-4 metric-grid-compact">
          <MetricCard label="Portfolio value" value={money(snapshot.PORTFOLIO_VALUE_USD)} detail={snapshot.quarter_label} icon={ChartNoAxesCombined} />
          <MetricCard label="Holdings" value={number(snapshot.CUSIP_COUNT)} detail={`${number(snapshot.INSTRUMENT_COUNT)} instruments`} icon={Layers3} />
          <MetricCard label="Largest position" value={money(snapshot.LARGEST_POSITION_VALUE_USD)} detail={snapshot.largest_holding_issuer || snapshot.largest_holding_cusip} icon={Trophy} />
          <MetricCard label="Top 10 weight" value={percent(snapshot.TOP_10_WEIGHT)} detail={`Largest ${percent(snapshot.LARGEST_POSITION_WEIGHT)}`} icon={Activity} />
        </div>
        <div className="chart-divider" />
        <SectionHeader title="Quarterly reporting changes" description="Comparable exact-CUSIP positions are classified by reported amount; the labels do not assert trades." />
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
          <EmptyState title="No comparable prior quarter" detail="This quarter still has a current snapshot." />
        )}
      </section>

      <section className="panel">
        <SectionHeader title="Portfolio history" description="Quarter-end reported values and behavior." action={<Tabs items={HISTORY_TABS} value={historyMetric} onChange={setHistoryMetric} />} />
        <ValueHistoryChart data={history} dataKey={historyMetric} formatter={historyFormatter} />
        <div className="chart-divider" />
        <h3 className="subchart-title">Newly and no longer reported positions</h3>
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
            {ACTIONS.map((item) => <option key={item} value={item}>{item ? actionLabel(item) : "All changes"}</option>)}
          </select>
          <select
            value={securityType}
            onChange={(event) => setSecurityType(event.target.value)}
            aria-label="Filter holdings by class"
          >
            <option value="">All classes</option>
            {(securityTypes.data || []).map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
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
                      <td>
                        {profile.data.quarter_status === "PARTIAL" ? (
                          <span className="entity-link"><strong>{item.issuer || "Unnamed security"}</strong><small>{item.cusip} · {item.title_of_class || "—"}</small></span>
                        ) : (
                          <Link className="entity-link" to={`/relationships/${cik}/${item.cusip}`}><strong>{item.issuer || "Unnamed security"}</strong><small>{item.cusip} · {item.title_of_class || "—"}</small></Link>
                        )}
                      </td>
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

    </>
  );
}

function IdentityItem({ label, value, href }) {
  return (
    <div className="identity-item">
      <span>{label}</span>
      {href ? <a href={href} target="_blank" rel="noreferrer">{value || "—"}</a> : <strong>{value || "—"}</strong>}
    </div>
  );
}
