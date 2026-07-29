import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CalendarDays, ChartNoAxesCombined, Layers3, Weight } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent, signedPercent } from "../format";
import { RelationshipChart } from "../components/Charts";
import {
  ActionBadge,
  DataNotice,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  SectionHeader,
  Tabs,
} from "../components/UI";

const METRICS = [
  { value: "value", label: "Market value" },
  { value: "shares", label: "Reported quantity" },
  { value: "weight", label: "Portfolio weight" },
];

export function RelationshipPage() {
  const { cik, cusip } = useParams();
  const [metric, setMetric] = useState("value");
  const state = useApi(`/api/relationships/${cik}/${cusip}`, {}, [cik, cusip]);
  if (state.loading) return <LoadingState />;
  if (state.error) return <ErrorState error={state.error} />;
  const {
    identity,
    current,
    history,
    option_history: optionHistory = [],
    statistics,
  } = state.data;
  const latestQuarterId = Math.max(
    0,
    ...history.map((item) => item.quarter_id),
    ...optionHistory.map((item) => item.quarter_id),
  );
  const latestOptions = Object.fromEntries(
    optionHistory
      .filter((item) => item.quarter_id === latestQuarterId)
      .map((item) => [item.option_type, item]),
  );
  const optionQuarters = Object.values(
    optionHistory.reduce((result, item) => {
      if (!result[item.quarter_id]) {
        result[item.quarter_id] = {
          quarter_id: item.quarter_id,
          quarter_label: item.quarter_label,
        };
      }
      result[item.quarter_id][item.option_type] = item;
      return result;
    }, {}),
  ).reverse();
  const hasLatestOptions = Boolean(latestOptions.CALL || latestOptions.PUT);
  const latestOptionValue = hasLatestOptions
    ? (latestOptions.CALL?.market_value_usd || 0)
      + (latestOptions.PUT?.market_value_usd || 0)
    : null;

  return (
    <>
      <PageHeader
        back={`/institutions/${cik}`}
        eyebrow="Institution × security"
        title={`${identity.institution_name} × ${identity.issuer}`}
        description={`CIK ${identity.cik} · CUSIP ${identity.cusip} · ${identity.title_of_class || "Unclassified"}`}
      />
      <div className="relationship-crumbs">
        <Link to={`/institutions/${cik}`}>{identity.institution_name}</Link>
        <span>owns</span>
        <Link to={`/securities/${cusip}`}>{identity.issuer}</Link>
      </div>
      <section className="metric-grid metric-grid-4">
        <MetricCard label="Latest base value" value={money(current?.market_value_usd)} detail={current?.quarter_label} icon={ChartNoAxesCombined} />
        <MetricCard label="Base reported quantity" value={reportedQuantityDisplay(current)} detail={current?.action ? <ActionBadge action={current.action} /> : "—"} icon={Layers3} />
        <MetricCard label="Base portfolio weight" value={percent(current?.portfolio_weight)} detail={`Peak ${percent(statistics.highest_portfolio_weight)}`} icon={Weight} />
        <MetricCard label="Holding duration" value={`${number(statistics.holding_duration_quarters)} quarters`} detail={`${number(statistics.consecutive_quarters_held)} consecutive`} icon={CalendarDays} />
      </section>
      <DataNotice>
        Base actions compare SEC-reported quantity with the prior quarter. Calls and puts are excluded, and the quantities are not split-adjusted.
      </DataNotice>

      <section className="panel">
        <SectionHeader title="Base-security statistics" description="Observed across analytics-ready report quarters for the non-option instrument." />
        <div className="identity-grid">
          <Identity label="First purchased" value={identity.first_purchased} />
          <Identity label="Latest quarter" value={identity.latest_quarter} />
          <Identity label="Last added" value={statistics.last_added} />
          <Identity label="Last reduced" value={statistics.last_reduced} />
          <Identity label="Largest position ever" value={money(statistics.largest_position_value_usd)} />
          <Identity label="Highest portfolio weight" value={percent(statistics.highest_portfolio_weight)} />
        </div>
      </section>

      <section className="panel">
        <SectionHeader title="Base-security history" description="Value, SEC-reported quantity and portfolio weight for the non-option instrument." action={<Tabs items={METRICS} value={metric} onChange={setMetric} />} />
        <RelationshipChart data={history} metric={metric} />
      </section>

      <section className="panel table-panel">
        <SectionHeader title="Option exposure" description="Calls and puts reported under this CUSIP are listed separately and excluded from base actions." />
        <div className="metric-grid metric-grid-3 metric-grid-compact">
          <MetricCard label="Latest call value" value={money(latestOptions.CALL?.market_value_usd)} detail={optionQuantity(latestOptions.CALL)} />
          <MetricCard label="Latest put value" value={money(latestOptions.PUT?.market_value_usd)} detail={optionQuantity(latestOptions.PUT)} />
          <MetricCard label="Latest total option value" value={money(latestOptionValue)} detail={latestOptions.CALL?.quarter_label || latestOptions.PUT?.quarter_label || "No current options"} />
        </div>
        {optionQuarters.length > 0 && (
          <div className="data-table-wrap"><table className="data-table">
            <thead><tr><th>Quarter</th><th className="numeric">Call quantity</th><th className="numeric">Call value</th><th className="numeric">Put quantity</th><th className="numeric">Put value</th></tr></thead>
            <tbody>{optionQuarters.map((item) => (
              <tr key={item.quarter_id}>
                <td className="strong">{item.quarter_label}</td>
                <td className="numeric">{optionQuantity(item.CALL)}</td>
                <td className="numeric">{money(item.CALL?.market_value_usd)}</td>
                <td className="numeric">{optionQuantity(item.PUT)}</td>
                <td className="numeric">{money(item.PUT?.market_value_usd)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      <section className="panel table-panel">
        <SectionHeader title="Base quarterly history" description="Each base-security quantity includes its filed SEC unit; option instruments are excluded." />
        <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>Quarter</th><th className="numeric">Reported quantity</th><th className="numeric">Amount change</th><th className="numeric">Amount change %</th><th className="numeric">Market value</th><th className="numeric">Market value change</th><th className="numeric">Weight</th><th>Action</th></tr></thead>
          <tbody>{[...history].reverse().map((item) => (
            <tr key={item.quarter_id}><td className="strong">{item.quarter_label}</td>
              <td className="numeric">{reportedQuantityDisplay(item)}</td>
              <td className={`numeric ${item.amount_change > 0 ? "positive" : item.amount_change < 0 ? "negative" : ""}`}>{number(item.amount_change)}</td>
              <td className={`numeric ${item.amount_change_percent > 0 ? "positive" : item.amount_change_percent < 0 ? "negative" : ""}`}>{signedPercent(item.amount_change_percent)}</td>
              <td className="numeric">{money(item.market_value_usd)}</td><td className={`numeric ${item.value_change_usd > 0 ? "positive" : item.value_change_usd < 0 ? "negative" : ""}`}>{money(item.value_change_usd)}</td>
              <td className="numeric">{percent(item.portfolio_weight)}</td><td><ActionBadge action={item.action} /></td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
    </>
  );
}

function Identity({ label, value }) {
  return <div className="identity-item"><span>{label}</span><strong>{value || "—"}</strong></div>;
}

function reportedQuantityDisplay(item) {
  if (!item) return "—";
  const quantities = [];
  if (item.shares !== null && item.shares !== undefined) {
    quantities.push(`${number(item.shares)} shares`);
  }
  if (item.principal_amount !== null && item.principal_amount !== undefined) {
    quantities.push(`${number(item.principal_amount)} principal amount`);
  }
  return quantities.length ? quantities.join(" · ") : number(item.reported_amount);
}

function optionQuantity(item) {
  if (!item) return "—";
  const unit = item.amount_type === "PRN" ? "principal amount" : "shares";
  return `${number(item.reported_amount)} ${unit}`;
}
