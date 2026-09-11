import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { applySeo } from "../seoMetadata";

// The API supplies the same factual content used in the initial server HTML.
export function ReportedSummary({ summary }) {
  const { pathname } = useLocation();

  useEffect(() => {
    if (!summary) return;
    const canonicalPath = new URL(summary.canonical_url).pathname;
    if (canonicalPath !== pathname.replace(/\/+$/, "")) return;
    applySeo({
      title: summary.title,
      description: summary.description,
      canonicalUrl: summary.canonical_url,
      structuredData: summary.structured_data,
      keywords: [],
    });
  }, [summary, pathname]);

  if (!summary) return null;
  return (
    <div className="reported-summary">
      {(summary.paragraphs || [summary.summary]).map((paragraph, index) => (
        <p className="reported-summary-text" key={index}>{paragraph}</p>
      ))}
      {summary.context_note && <p className="reported-summary-context">{summary.context_note}</p>}
      {summary.links?.length > 0 && (
        <nav className="reported-summary-links" aria-label="Related data and sources">
          {summary.links.map(({ label, url }) => (
            url.startsWith("/")
              ? <Link key={url} to={url}>{label}</Link>
              : <a key={url} href={url} target="_blank" rel="noreferrer">{label}</a>
          ))}
        </nav>
      )}
    </div>
  );
}

export function ReportedDataNote({ summary }) {
  if (!summary?.data_note) return null;
  return <p className="reported-data-note">{summary.data_note}</p>;
}
