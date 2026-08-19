import { useState } from "react";
import { useApi } from "../hooks";
import { LatestFilingsTable } from "../components/LatestFilingsTable";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pager,
} from "../components/UI";

export function LatestFilingsPage() {
  const [page, setPage] = useState(1);
  const filings = useApi(
    "/api/filings/latest",
    { page, page_size: 50 },
    [page],
  );

  return (
    <>
      <PageHeader
        eyebrow="Latest updates"
        title="Latest institutional 13F filings"
        description="The newest canonical manager reports, ordered by SEC filing date. Reported 13F assets cover disclosed 13F securities and are not the institution's total assets under management."
      />
      <section className="panel table-panel">
        {filings.loading ? (
          <LoadingState label="Loading recent filings" />
        ) : filings.error ? (
          <ErrorState error={filings.error} />
        ) : !filings.data.items.length ? (
          <EmptyState title="No filings are available" />
        ) : (
          <>
            <LatestFilingsTable filings={filings.data.items} />
            <Pager
              page={page}
              hasMore={filings.data.has_more}
              onChange={setPage}
            />
          </>
        )}
      </section>
    </>
  );
}
