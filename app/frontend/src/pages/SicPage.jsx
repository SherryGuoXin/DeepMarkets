import { useEffect, useMemo, useState } from "react";
import { Building2, Factory, Layers3, Search } from "lucide-react";
import { useApi } from "../hooks";
import { money, number } from "../format";
import {
  DataNotice,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  QuarterSelect,
  SectionHeader,
} from "../components/UI";

export function SicPage() {
  const quarters = useApi("/api/meta/quarters", {}, []);
  const [quarter, setQuarter] = useState(null);
  const [division, setDivision] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!quarter && quarters.data?.length) setQuarter(quarters.data[0].quarter_id);
  }, [quarter, quarters.data]);

  const sic = useApi(
    "/api/sic/aggregation",
    { quarter_id: quarter, division, limit: 100 },
    [quarter, division],
  );

  const filteredIndustries = useMemo(() => {
    const items = sic.data?.industries || [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) =>
      `${item.division} ${item.sic} ${item.sic_description}`.toLowerCase().includes(query),
    );
  }, [sic.data, search]);

  const selectedDivision = division || "All divisions";
  const totals = useMemo(() => {
    const source = division
      ? (sic.data?.divisions || []).filter((item) => item.division === division)
      : (sic.data?.divisions || []);
    return source.reduce(
      (acc, item) => ({
        institution_count: acc.institution_count + (item.institution_count || 0),
        portfolio_value_usd: acc.portfolio_value_usd + (item.portfolio_value_usd || 0),
        holding_count: acc.holding_count + (item.holding_count || 0),
        net_value_change_usd: acc.net_value_change_usd + (item.net_value_change_usd || 0),
      }),
      { institution_count: 0, portfolio_value_usd: 0, holding_count: 0, net_value_change_usd: 0 },
    );
  }, [division, sic.data]);

  if (quarters.loading || !quarter) return <LoadingState />;
  if (quarters.error) return <ErrorState error={quarters.error} />;

  return (
    <>
      <PageHeader
        eyebrow="SEC SIC aggregation"
        title="Group filing managers by SEC industry"
        description="Aggregate 13F manager portfolios using each filing entity's SEC SIC division and industry."
        actions={<QuarterSelect quarters={quarters.data} value={quarter} onChange={setQuarter} />}
      />
      <DataNotice>
        This page groups filing managers by their own SEC SIC classification.
        It does not classify the issuers inside each portfolio by sector.
      </DataNotice>

      {sic.loading ? <LoadingState /> : sic.error ? <ErrorState error={sic.error} /> : (
        <>
          <section className="metric-grid metric-grid-4">
            <MetricCard label="Scope" value={selectedDivision} detail="Manager SIC grouping" icon={Factory} />
            <MetricCard label="Institutions" value={number(totals.institution_count)} detail="Managers with summaries" icon={Building2} />
            <MetricCard label="Portfolio value" value={money(totals.portfolio_value_usd)} detail="Aggregated reported value" icon={Layers3} />
            <MetricCard label="Net value change" value={money(totals.net_value_change_usd)} detail="Comparable adjacent quarter" />
          </section>

          <section className="panel table-panel">
            <SectionHeader title="SIC divisions" description="Click a division to drill into SIC industry descriptions." />
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Division</th>
                    <th className="numeric">Institutions</th>
                    <th className="numeric">Portfolio value</th>
                    <th className="numeric">Holdings</th>
                    <th className="numeric">Net value change</th>
                    <th className="numeric">New / Exited</th>
                  </tr>
                </thead>
                <tbody>
                  {(sic.data.divisions || []).map((item) => (
                    <tr
                      key={item.division}
                      className={division === item.division ? "selected-row" : ""}
                      onClick={() => setDivision(division === item.division ? "" : item.division)}
                    >
                      <td className="strong">{item.division}</td>
                      <td className="numeric">{number(item.institution_count)}</td>
                      <td className="numeric strong">{money(item.portfolio_value_usd)}</td>
                      <td className="numeric">{number(item.holding_count)}</td>
                      <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>{money(item.net_value_change_usd)}</td>
                      <td className="numeric">{number(item.new_count)} / {number(item.exited_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel table-panel">
            <SectionHeader title="SIC industries" description={division || "Top industries across all divisions"} />
            <div className="table-filters">
              <label className="search-field">
                <Search size={17} />
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search SIC or industry" />
              </label>
            </div>
            {!filteredIndustries.length ? <EmptyState /> : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>SIC</th>
                      <th>Industry</th>
                      <th>Division</th>
                      <th className="numeric">Institutions</th>
                      <th className="numeric">Portfolio value</th>
                      <th className="numeric">Net value change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredIndustries.map((item) => (
                      <tr key={`${item.division}-${item.sic}`}>
                        <td className="strong">{item.sic}</td>
                        <td>{item.sic_description}</td>
                        <td>{item.division}</td>
                        <td className="numeric">{number(item.institution_count)}</td>
                        <td className="numeric strong">{money(item.portfolio_value_usd)}</td>
                        <td className={`numeric ${item.net_value_change_usd > 0 ? "positive" : item.net_value_change_usd < 0 ? "negative" : ""}`}>{money(item.net_value_change_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
