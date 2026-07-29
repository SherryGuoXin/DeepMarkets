import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Building2,
  ChartNoAxesCombined,
  Layers3,
  ShieldCheck,
} from "lucide-react";
import { useApi } from "../hooks";
import { money, number } from "../format";
import {
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  QuarterSelect,
  SectionHeader,
} from "../components/UI";

export function OverviewPage() {
  const quartersState = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  useEffect(() => {
    if (!quarter && quartersState.data?.length) {
      setQuarter(quartersState.data[0].quarter_id);
    }
  }, [quarter, quartersState.data]);
  const overview = useApi(
    "/api/overview",
    { quarter_id: quarter },
    [quarter],
  );

  if (quartersState.loading || !quarter) return <LoadingState />;
  if (quartersState.error) return <ErrorState error={quartersState.error} />;
  const summary = overview.data?.summary;

  return (
    <>
      <PageHeader
        eyebrow="Market intelligence"
        title="See institutional ownership in motion."
        description="Follow how institutions build, trim and rotate reported positions across quarters, with each security variant kept distinct."
        actions={
          <QuarterSelect
            quarters={quartersState.data}
            value={quarter}
            onChange={setQuarter}
          />
        }
      />
      {overview.loading ? (
        <LoadingState />
      ) : overview.error ? (
        <ErrorState error={overview.error} />
      ) : (
        <>
          <section className="metric-grid metric-grid-4">
            <MetricCard
              label="Reported portfolio value"
              value={money(summary.portfolio_value_usd)}
              detail={summary.quarter_label}
              icon={ChartNoAxesCombined}
            />
            <MetricCard
              label="Reporting institutions"
              value={number(summary.institution_count)}
              detail="Analytics-ready managers"
              icon={Building2}
            />
            <MetricCard
              label="Reported positions"
              value={number(summary.reported_position_count, true)}
              detail="Institution × security observations"
              icon={Layers3}
            />
            <MetricCard
              label="Common stock value"
              value={money(summary.common_stock_value_usd)}
              detail="Options remain separate"
              icon={ShieldCheck}
            />
          </section>

          <div className="split-grid">
            <section className="panel">
              <SectionHeader
                title="Largest institutions"
                description={`Portfolio value in ${summary.quarter_label}`}
                action={<Link className="text-link" to="/institutions">View all <ArrowRight size={15} /></Link>}
              />
              <div className="rank-list">
                {overview.data.largest_institutions.map((item, index) => (
                  <Link to={`/institutions/${item.cik}`} key={item.cik}>
                    <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                    <span className="rank-identity">
                      <strong>{item.institution_name}</strong>
                      <small>{number(item.holding_count)} reported holdings</small>
                    </span>
                    <strong>{money(item.portfolio_value_usd)}</strong>
                  </Link>
                ))}
              </div>
            </section>

            <section className="panel">
              <SectionHeader
                title="Largest reported securities"
                description={`Aggregated institutional value in ${summary.quarter_label}`}
                action={<Link className="text-link" to="/securities">View all <ArrowRight size={15} /></Link>}
              />
              <div className="rank-list">
                {overview.data.largest_securities.map((item, index) => (
                  <Link to={`/securities/${item.cusip}`} key={item.cusip}>
                    <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                    <span className="rank-identity">
                      <strong>{item.issuer || "Unnamed security"}</strong>
                      <small>{number(item.institution_count)} reporting institutions</small>
                    </span>
                    <strong>{money(item.institutional_value_usd)}</strong>
                  </Link>
                ))}
              </div>
            </section>
          </div>

          <section className="panel methodology-panel">
            <div>
              <span className="eyebrow">A clearer view beneath the surface</span>
              <h2>Watch the deep currents of institutional capital.</h2>
              <p>
                See where leading investors are building conviction, reducing
                exposure and changing direction. 13f-data.com turns dense filings
                into a clean, comparable view of ownership and motion.
              </p>
            </div>
            <div className="method-steps">
              <span><b>01</b> Clean filings</span>
              <span><b>02</b> Comparable holdings</span>
              <span><b>03</b> Capital in motion</span>
            </div>
          </section>
        </>
      )}
    </>
  );
}
