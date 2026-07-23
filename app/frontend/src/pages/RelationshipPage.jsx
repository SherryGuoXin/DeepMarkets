import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CalendarDays, ChartNoAxesCombined, Layers3, Weight } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent, signedPercent } from "../format";
import { RelationshipChart } from "../components/Charts";
import {
  ActionBadge,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  SectionHeader,
  Tabs,
} from "../components/UI";

const METRICS = [
  { value: "value", label: "Market value" },
  { value: "shares", label: "Shares / amount" },
  { value: "weight", label: "Portfolio weight" },
];

export function RelationshipPage() {
  const { cik, cusip } = useParams();
  const [metric, setMetric] = useState("value");
  const state = useApi(`/api/relationships/${cik}/${cusip}`, {}, [cik, cusip]);
  if (state.loading) return <LoadingState />;
  if (state.error) return <ErrorState error={state.error} />;
  const { identity, current, history, statistics } = state.data;

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
        <MetricCard label="Latest position value" value={money(current?.market_value_usd)} detail={current?.quarter_label} icon={ChartNoAxesCombined} />
        <MetricCard label="Reported amount" value={number(current?.reported_amount)} detail={current?.action ? <ActionBadge action={current.action} /> : "—"} icon={Layers3} />
        <MetricCard label="Portfolio weight" value={percent(current?.portfolio_weight)} detail={`Peak ${percent(statistics.highest_portfolio_weight)}`} icon={Weight} />
        <MetricCard label="Holding duration" value={`${number(statistics.holding_duration_quarters)} quarters`} detail={`${number(statistics.consecutive_quarters_held)} consecutive`} icon={CalendarDays} />
      </section>

      <section className="panel">
        <SectionHeader title="Relationship statistics" description="Observed across analytics-ready report quarters." />
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
        <SectionHeader title="Position history" description="Value, reported amount and portfolio weight over time." action={<Tabs items={METRICS} value={metric} onChange={setMetric} />} />
        <RelationshipChart data={history} metric={metric} />
      </section>

      <section className="panel table-panel">
        <SectionHeader title="Quarterly history" description="Every reported observation for this relationship." />
        <div className="data-table-wrap"><table className="data-table">
          <thead><tr><th>Quarter</th><th className="numeric">Shares / amount</th><th className="numeric">Δ amount</th><th className="numeric">Market value</th><th className="numeric">Δ value</th><th className="numeric">Weight</th><th>Action</th></tr></thead>
          <tbody>{[...history].reverse().map((item) => (
            <tr key={item.quarter_id}><td className="strong">{item.quarter_label}</td><td className="numeric">{number(item.reported_amount)}</td>
              <td className={`numeric ${item.amount_change > 0 ? "positive" : item.amount_change < 0 ? "negative" : ""}`}>{number(item.amount_change)}<small className="block">{signedPercent(item.amount_change_percent)}</small></td>
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
