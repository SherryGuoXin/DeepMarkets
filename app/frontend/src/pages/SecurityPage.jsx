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
  const {
    identity,
    snapshot,
    history,
    instrument_breakdown: instrumentBreakdown,
    same_issuer_cusips,
  } = profile.data;
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
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <section className="metric-grid metric-grid-4">
        <MetricCard label="Total CUSIP value" value={money(snapshot.TOTAL_VALUE_USD)} detail="Base security + calls + puts" icon={ChartNoAxesCombined} />
        <MetricCard label="Reporting institutions" value={number(snapshot.MANAGER_COUNT)} detail={`${number(activity.NEW?.institution_count || 0)} new base positions`} icon={Users} />
        <MetricCard label="Largest holder" value={snapshot.largest_holder_name || "—"} detail={money(snapshot.LARGEST_MANAGER_VALUE_USD)} icon={Building2} />
        <MetricCard label="Ownership concentration" value={snapshot.MANAGER_CONCENTRATION_HHI?.toFixed(3) || "—"} detail="Manager HHI" icon={ShieldCheck} />
      </section>

      <section className="panel">
        <SectionHeader title="Instrument exposure" description={`Reported value for ${snapshot.quarter_label}, separated by instrument variant.`} />
        <div className="metric-grid metric-grid-3 metric-grid-compact">
          <MetricCard label="Base security" value={money(exposure.NONE?.value_usd)} detail={exposureDetail(exposure.NONE)} />
          <MetricCard label="Call options" value={money(exposure.CALL?.value_usd)} detail={exposureDetail(exposure.CALL)} />
          <MetricCard label="Put options" value={money(exposure.PUT?.value_usd)} detail={exposureDetail(exposure.PUT)} />
        </div>
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
          <SectionHeader title="Base-security activity" description="Distinct managers by reported-quantity action; calls and puts are excluded." />
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
        <SectionHeader title="Base-security ownership history" description="Manager reports for the non-option instrument only." action={<Tabs items={HISTORY_TABS} value={historyMetric} onChange={setHistoryMetric} />} />
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
        <div className="table-explanations">
          <DataNotice>
            <strong>Column definitions for {snapshot.quarter_label}:</strong>{" "}
            Filed quantity is the non-option amount reported for the selected quarter—not the amount added QoQ. Form 13F identifies this amount as shares (SH) or principal amount (PRN), so each row displays its actual unit. Quantity change and holding value change are selected-quarter amounts minus prior-quarter amounts. Holding, call and put values are the selected-quarter normalized Form 13F values. Portfolio weight is the non-option holding value divided by that institution&apos;s total 13F portfolio value.
          </DataNotice>
          <DataNotice>
            <strong>Action definition — explicitly non-split-adjusted:</strong>{" "}
            Actions use only non-option SEC-reported quantity. NEW = no prior position; ADDED = quantity increased; REDUCED = quantity decreased but remains held; EXITED = prior position is absent this quarter; UNCHANGED = equal quantity; UNKNOWN = a confidential omission prevents a reliable comparison. Calls and puts never affect the action. A stock split can therefore appear as ADDED or REDUCED.
          </DataNotice>
        </div>
        <div className="table-filters">
          <label className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search institution or CIK" /></label>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">All actions</option>
            {["NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED", "UNKNOWN"].map((item) => <option key={item}>{titleCase(item)}</option>)}
          </select>
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="value">Sort by current holding value</option><option value="shares">Sort by current reported quantity</option><option value="weight">Sort by current portfolio weight</option><option value="share_change">Sort by absolute QoQ quantity change</option><option value="institution">Sort alphabetically</option>
          </select>
        </div>
        {holders.loading ? <LoadingState /> : holders.error ? <ErrorState error={holders.error} /> : !holders.data.items.length ? <EmptyState /> : (
          <>
            <div className="data-table-wrap"><table className="data-table">
              <thead><tr><th>Institution</th><th className="numeric">Filed quantity ({snapshot.quarter_label})</th><th className="numeric">Quantity change (QoQ)</th><th className="numeric">Holding value ({snapshot.quarter_label})</th><th className="numeric">Call value ({snapshot.quarter_label})</th><th className="numeric">Put value ({snapshot.quarter_label})</th><th className="numeric">Portfolio weight ({snapshot.quarter_label})</th><th className="numeric">Holding value change (QoQ)</th><th>Action (non-split-adjusted)</th></tr></thead>
              <tbody>{holders.data.items.map((item) => (
                <tr key={item.cik}>
                  <td><Link className="entity-link" to={`/relationships/${item.cik}/${cusip}`}><strong>{item.institution_name}</strong><small>CIK {item.cik}</small></Link></td>
                  <td className="numeric">{quantityDisplay(item)}</td>
                  <td className={`numeric ${item.amount_change > 0 ? "positive" : item.amount_change < 0 ? "negative" : ""}`}>{quantityChangeDisplay(item)}</td>
                  <td className="numeric strong">{money(item.market_value_usd)}</td>
                  <td className="numeric">{money(item.call_value_usd)}</td>
                  <td className="numeric">{money(item.put_value_usd)}</td>
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

function Identity({ label, value }) {
  return <div className="identity-item"><span>{label}</span><strong>{value || "—"}</strong></div>;
}

function exposureDetail(item) {
  if (!item) return "No reported position";
  return `${number(item.institution_count)} institutions · ${number(item.reported_amount)} quantity`;
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
    .filter(([field]) => item[field] !== null && item[field] !== undefined)
    .map(([field, unit]) => {
      const value = item[field];
      return `${signed && Number(value) > 0 ? "+" : ""}${number(value)} ${unit}`;
    });
  return parts.length ? parts.join(" · ") : "—";
}
