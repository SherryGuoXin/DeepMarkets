import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRightLeft, Search } from "lucide-react";
import { useApi } from "../hooks";
import { money, number, percent, titleCase } from "../format";
import {
  ActionBadge,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  QuarterSelect,
  SectionHeader,
  Tabs,
} from "../components/UI";

const MODES = [
  { value: "institution", label: "Institution" },
  { value: "security", label: "Security" },
];
const ACTIONS = ["", "NEW", "ADDED", "REDUCED", "EXITED", "UNCHANGED", "UNKNOWN"];

export function ComparePage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [mode, setMode] = useState("institution");
  const [identifier, setIdentifier] = useState("0001067983");
  const [fromQuarter, setFromQuarter] = useState(null);
  const [toQuarter, setToQuarter] = useState(null);
  const [action, setAction] = useState("");

  useEffect(() => {
    if (!quarters.data?.length || toQuarter) return;
    setToQuarter(quarters.data[0].quarter_id);
    setFromQuarter(quarters.data[1]?.quarter_id || quarters.data[0].quarter_id);
  }, [quarters.data, toQuarter]);

  useEffect(() => {
    setIdentifier(mode === "institution" ? "0001067983" : "037833100");
  }, [mode]);

  const path =
    mode === "institution"
      ? `/api/compare/institutions/${identifier.trim()}`
      : `/api/compare/securities/${identifier.trim()}`;
  const comparison = useApi(
    path,
    { from_quarter_id: fromQuarter, to_quarter_id: toQuarter, action, limit: 25 },
    [mode, identifier, fromQuarter, toQuarter, action],
  );

  if (quarters.loading || !fromQuarter || !toQuarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;

  return (
    <>
      <PageHeader
        eyebrow="Quarter comparison"
        title="Compare motion between two report quarters"
        description="Select an institution CIK or security CUSIP, then review summary deltas and the largest position-level changes."
      />

      <section className="toolbar-panel compare-toolbar">
        <Tabs items={MODES} value={mode} onChange={setMode} />
        <label className="search-field">
          <Search size={17} />
          <input
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder={mode === "institution" ? "CIK" : "CUSIP"}
          />
        </label>
        <QuarterSelect quarters={quarters.data} value={fromQuarter} onChange={setFromQuarter} compact />
        <ArrowRightLeft size={17} className="muted-icon" />
        <QuarterSelect quarters={quarters.data} value={toQuarter} onChange={setToQuarter} compact />
        <select value={action} onChange={(event) => setAction(event.target.value)}>
          {ACTIONS.map((item) => (
            <option key={item} value={item}>{item ? titleCase(item) : "All actions"}</option>
          ))}
        </select>
      </section>

      {comparison.loading ? (
        <LoadingState />
      ) : comparison.error ? (
        <ErrorState error={comparison.error} />
      ) : (
        <ComparisonBody mode={mode} data={comparison.data} />
      )}
    </>
  );
}

function ComparisonBody({ mode, data }) {
  const summary = useMemo(() => {
    if (mode === "institution") {
      return [
        ["Portfolio value", data.delta.portfolio_value_usd, money],
        ["CUSIPs", data.delta.cusip_count, number],
        ["Instruments", data.delta.instrument_count, number],
        ["Top 10 weight", data.delta.top_10_weight, percent],
      ];
    }
    return [
      ["Institutional value", data.delta.institutional_value_usd, money],
      ["Institutions", data.delta.institution_count, number],
      ["Common value", data.delta.common_stock_value_usd, money],
      ["Concentration", data.delta.concentration_hhi, (value) => value?.toFixed?.(3) || "0.000"],
    ];
  }, [data, mode]);

  return (
    <>
      <section className="metric-grid metric-grid-4">
        {summary.map(([label, value, formatter]) => (
          <MetricCard
            key={label}
            label={label}
            value={formatter(value)}
            detail="Change across selected quarters"
            tone={value > 0 ? "positive" : value < 0 ? "negative" : undefined}
          />
        ))}
      </section>

      <section className="panel">
        <SectionHeader
          title={mode === "institution" ? data.identity.institution_name : data.identity.issuer}
          description={`${data.prior.QUARTER_LABEL} to ${data.current.QUARTER_LABEL}`}
        />
        <div className="compare-grid">
          <Snapshot title="Starting quarter" item={data.prior} mode={mode} />
          <Snapshot title="Ending quarter" item={data.current} mode={mode} />
        </div>
      </section>

      <section className="panel table-panel">
        <SectionHeader title="Largest base-security changes" description="Calculated directly between the two selected quarters and sorted by absolute holding-value change. Actions exclude calls and puts and are non-split-adjusted. UNKNOWN is reserved for a missing-side position when that filing reports confidential omissions." />
        {!data.movers.length ? <EmptyState /> : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{mode === "institution" ? "Security" : "Institution"}</th>
                  <th>Action</th>
                  <th className="numeric">Prior value</th>
                  <th className="numeric">Current value</th>
                  <th className="numeric">Value change</th>
                  <th className="numeric">Amount change</th>
                </tr>
              </thead>
              <tbody>
                {data.movers.map((item, index) => (
                  <tr key={`${item.cusip || item.cik}-${index}`}>
                    <td>
                      {mode === "institution" ? (
                        <Link className="entity-link" to={`/securities/${item.cusip}`}>
                          <strong>{item.issuer || "Unnamed security"}</strong>
                          <small>{item.cusip} · {item.title_of_class || "—"}</small>
                        </Link>
                      ) : (
                        <Link className="entity-link" to={`/institutions/${item.cik}`}>
                          <strong>{item.institution_name}</strong>
                          <small>CIK {item.cik}</small>
                        </Link>
                      )}
                    </td>
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
        )}
      </section>
    </>
  );
}

function Snapshot({ title, item, mode }) {
  const rows =
    mode === "institution"
      ? [
          ["Portfolio", money(item.PORTFOLIO_VALUE_USD)],
          ["CUSIPs", number(item.CUSIP_COUNT)],
          ["Instruments", number(item.INSTRUMENT_COUNT)],
          ["Top 10 weight", percent(item.TOP_10_WEIGHT)],
        ]
      : [
          ["Institutional value", money(item.TOTAL_VALUE_USD)],
          ["Institutions", number(item.MANAGER_COUNT)],
          ["Common value", money(item.COMMON_STOCK_VALUE_USD)],
          ["Concentration", item.MANAGER_CONCENTRATION_HHI?.toFixed?.(3) || "0.000"],
        ];
  return (
    <div className="compare-snapshot">
      <h3>{title}</h3>
      <strong>{item.QUARTER_LABEL}</strong>
      {rows.map(([label, value]) => (
        <div key={label}><span>{label}</span><b>{value}</b></div>
      ))}
    </div>
  );
}
