import { Link } from "react-router-dom";
import { date, money, number } from "../format";

export function LatestFilingsTable({ filings, ranked = false }) {
  return (
    <div className="data-table-wrap">
      <table className="data-table latest-filings-table">
        <thead>
          <tr>
            {ranked && <th>Row</th>}
            <th>Institution</th>
            <th>Filed</th>
            <th>Report period</th>
            <th className="numeric">Reported 13F assets</th>
            <th className="numeric">Holdings</th>
          </tr>
        </thead>
        <tbody>
          {filings.map((filing, index) => (
            <tr key={`${filing.cik}-${filing.accession_number}`}>
              {ranked && (
                <td className="rank-cell">{String(index + 1).padStart(2, "0")}</td>
              )}
              <td>
                <Link className="entity-link" to={`/institutions/${filing.cik}`}>
                  <strong>{filing.institution_name}</strong>
                  <small>CIK {filing.cik}</small>
                </Link>
              </td>
              <td>
                <time dateTime={filing.filing_date}>{date(filing.filing_date)}</time>
                <small className="block">{filing.submission_type}</small>
              </td>
              <td>
                <strong>{filing.quarter_label}</strong>
                <small className="block">Period ended {date(filing.period_end_date)}</small>
              </td>
              <td className="numeric strong">{money(filing.reported_assets_usd)}</td>
              <td className="numeric">
                {number(filing.holding_count)}
                {filing.is_partial ? <small className="block partial-label">Partial</small> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
