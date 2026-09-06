import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Building2,
  ChartNoAxesCombined,
  CirclePlus,
  CircleX,
  Info,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { useApi } from "../hooks";
import { actionLabel, money, number, percent, titleCase } from "../format";
import { ValueHistoryChart } from "../components/Charts";
import {
  ActionBadge,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Pager,
  QuarterlyDataNotice,
  QuarterSelect,
  SectionHeader,
  Tabs,
} from "../components/UI";

const HISTORY_TABS = [
  { value: "institutional_value_usd", label: "Institutional value" },
  { value: "institution_count", label: "Holder count" },
  { value: "net_value_change_usd", label: "Reported value change" },
  { value: "average_position_value_usd", label: "Average position" },
];
const REPORTING_CHANGES = [
  { key: "NEW", icon: CirclePlus },
  { key: "ADDED", icon: TrendingUp },
  { key: "REDUCED", icon: TrendingDown },
  { key: "EXITED", icon: CircleX },
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
  const profile = useApi(
    `/api/securities/${cusip}`,
    { quarter_id: quarter },
    [cusip, quarter],
    quarter !== null,
  );
  useEffect(() => {
    const actual = profile.data?.snapshot?.QUARTER_ID;
    if (actual) setQuarter((current) => actual !== current ? actual : current);
  }, [profile.data]);
  useEffect(() => setPage(1), [quarter, action, search, sort]);
  const holders = useApi(
    `/api/securities/${cusip}/holders`,
    { quarter_id: quarter, action, search, sort, page, page_size: 25 },
    [cusip, quarter, action, search, sort, page],
    quarter !== null,
  );
  const activity = useMemo(
    () => Object.fromEntries((profile.data?.activity || []).map((item) => [item.action, item])),
    [profile.data],
  );

  if (quarters.loading || !quarter || profile.loading) return <LoadingState />;
  if (quarters.error || profile.error) return <ErrorState error={quarters.error || profile.error} />;
  const {
    identity,
    snapshot,
    history,
    instrument_breakdown: instrumentBreakdown,
    same_issuer_cusips,
  } = profile.data;
  const availableQuarterIds = new Set(history.map((item) => item.quarter_id));
  const availableQuarters = quarters.data.filter(
    (item) => availableQuarterIds.has(item.quarter_id),
  );
  const exposure = Object.fromEntries(
    (instrumentBreakdown || []).map((item) => [item.option_type, item]),
  );
  const historyFormatter = historyMetric.includes("count") ? number : money;

  return (
    <>
      <PageHeader
        back="/securities"
        eyebrow={`Security · CUSIP ${identity.cusip}`}
        title={identity.issuer || "Unnamed security"}
        description={`${identity.title_of_class || "Unclassified"} · ${titleCase(identity.security_type)} · Reports ${identity.first_reportable_quarter || "—"}–${identity.latest_reportable_quarter || "—"}`}
        actions={<QuarterSelect quarters={availableQuarters} value={quarter} onChange={setQuarter} />}
      />
      <section className="panel">
        <SectionHeader title={`${snapshot.quarter_label} security summary`} description="Ownership totals and reporting changes for the selected quarter." />
        <QuarterlyDataNotice quarterId={quarter} />
        <div className="metric-grid metric-grid-4 metric-grid-compact">
          <MetricCard
            label="Total reported value"
            value={money(snapshot.TOTAL_VALUE_USD)}
            detail={`Base security ${money(exposure.NONE?.value_usd || 0)} + Call options ${money(exposure.CALL?.value_usd || 0)} + Put options ${money(exposure.PUT?.value_usd || 0)}`}
            icon={ChartNoAxesCombined}
          />
          <MetricCard label="Reporting institutions" value={number(snapshot.MANAGER_COUNT)} detail={`${number(activity.NEW?.institution_count || 0)} newly reported base positions`} icon={Users} />
          <MetricCard label="Largest holder" value={snapshot.largest_holder_name || "—"} detail={money(snapshot.LARGEST_MANAGER_VALUE_USD)} icon={Building2} />
          <MetricCard label="Ownership concentration" value={snapshot.MANAGER_CONCENTRATION_HHI?.toFixed(3) || "—"} detail="Manager HHI" icon={ShieldCheck} />
        </div>
        <div className="metric-grid metric-grid-4 metric-grid-compact filing-summary-changes">
          {REPORTING_CHANGES.map(({ key, icon }) => (
            <MetricCard
              key={key}
              label={actionLabel(key)}
              value={number(activity[key]?.institution_count || 0)}
              detail={`${money(activity[key]?.value_change_usd || 0)} change`}
              icon={icon}
            />
          ))}
        </div>
      </section>

      <section className="panel">
        <SectionHeader title="Exact-CUSIP common-stock history" description="Reported common-stock value for this CUSIP only; successor identifiers are not combined." action={<Tabs items={HISTORY_TABS} value={historyMetric} onChange={setHistoryMetric} />} />
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
        <SectionHeader title="Institution holders" description={`Base-security positions and separately reported option value for ${snapshot.quarter_label}.`} />
        <div className="table-filters">
          <label className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search institution or CIK" /></label>
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="value">Sort by current holding value</option><option value="shares">Sort by current reported quantity</option><option value="weight">Sort by current portfolio weight</option><option value="share_change">Sort by absolute QoQ quantity change</option><option value="institution">Sort alphabetically</option>
          </select>
          <div className="action-filter-group">
            <select value={action} onChange={(event) => setAction(event.target.value)}>
              <option value="">All changes</option>
              {["NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED", "UNKNOWN"].map((item) => (
                <option key={item} value={item}>{actionLabel(item)}</option>
              ))}
            </select>
            <details className="action-definition">
              <summary aria-label="Show action definition" title="Action definition"><Info size={16} /></summary>
              <div className="action-definition-popover">
                <strong>Action definition — explicitly non-split-adjusted</strong>
                <span>Changes use only non-option SEC-reported quantity for the exact CUSIP. Probable identifier changes and confidential omissions are marked not comparable. Calls and puts never affect the classification. These labels describe quarterly reports, not confirmed trades.</span>
              </div>
            </details>
          </div>
        </div>
        {holders.loading ? <LoadingState /> : holders.error ? <ErrorState error={holders.error} /> : !holders.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap"><table className="data-table holder-table">
              <thead><tr><th className="holder-institution-column">Institution</th><th className="numeric">Filed quantity</th><th className="numeric">Quantity change</th><th className="numeric">Holding value</th><th className="numeric">Call / Put value</th><th className="numeric">Portfolio weight</th><th className="numeric">Holding value change</th><th>Action</th></tr></thead>
              <tbody>{holders.data.items.map((item) => (
                <tr key={item.cik}>
                  <td className="holder-institution-column"><Link className="entity-link" to={`/relationships/${item.cik}/${cusip}`} title={item.institution_name}><strong>{item.institution_name}</strong><small>CIK {item.cik}</small></Link></td>
                  <td className="numeric">{quantityDisplay(item)}</td>
                  <td className={`numeric ${item.amount_change > 0 ? "positive" : item.amount_change < 0 ? "negative" : ""}`}>{quantityChangeDisplay(item)}</td>
                  <td className="numeric strong">{money(item.market_value_usd)}</td>
                  <td className="numeric"><span className="option-value-pair"><span>Call {money(item.call_value_usd)}</span><span>Put {money(item.put_value_usd)}</span></span></td>
                  <td className="numeric">{percent(item.portfolio_weight)}</td>
                  <td className={`numeric ${item.value_change_usd > 0 ? "positive" : item.value_change_usd < 0 ? "negative" : ""}`}>{money(item.value_change_usd)}</td>
                  <td>{item.action ? <ActionBadge action={item.action} /> : "—"}</td>
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

function quantityDisplay(item) {
  return quantityParts(item, [
    ["shares", "shares"],
    ["principal_amount", "principal amount"],
    ["other_amount", "units"],
  ], false);
}

function quantityChangeDisplay(item) {
  return quantityParts(item, [
    ["share_change", "shares"],
    ["principal_amount_change", "principal amount"],
    ["other_amount_change", "units"],
  ], true);
}

function quantityParts(item, fields, signed) {
  const parts = fields
    .filter(([field]) => (
      item[field] !== null
      && item[field] !== undefined
      && Number(item[field]) !== 0
    ))
    .map(([field, unit]) => {
      const value = item[field];
      return `${signed && Number(value) > 0 ? "+" : ""}${number(value)} ${unit}`;
    });
  return parts.length ? parts.join(" · ") : "—";
}
