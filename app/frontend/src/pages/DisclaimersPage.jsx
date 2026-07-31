import { ExternalLink } from "lucide-react";

const LAST_UPDATED = "July 29, 2026";

export function DisclaimersPage() {
  return (
    <article className="panel legal-document">
      <header className="legal-document-header">
        <span className="eyebrow">Legal</span>
        <h1>Website Disclaimer</h1>
        <p className="legal-effective">Last updated: {LAST_UPDATED}</p>
      </header>

      <div className="legal-notice">
        <strong>Important notice</strong>
        <p>
          Please read this Disclaimer carefully before using 13fdata.net (the
          “Website”). By accessing or using the Website, you acknowledge and
          accept this Disclaimer. If you do not agree, do not use the Website.
        </p>
      </div>

      <div className="legal-body">
        <LegalSection number="1" title="Purpose and scope">
          <p>
            The Website is an independent research and data-visualization
            project. Its content, including data, calculations, classifications,
            rankings, charts, comparisons, estimates and commentary
            (collectively, “Content”), is provided solely for general
            informational, educational and research purposes.
          </p>
          <p>
            The Website is not affiliated with, sponsored by, approved by or
            endorsed by the U.S. Securities and Exchange Commission (“SEC”),
            EDGAR, any reporting institution, any security issuer, any government
            agency or any market participant.
          </p>
        </LegalSection>

        <LegalSection number="2" title="No investment or professional advice">
          <p>
            Nothing on the Website constitutes investment, financial, legal, tax,
            accounting or other professional advice. Nothing is an offer,
            solicitation, recommendation, endorsement or invitation to buy, sell,
            hold or otherwise transact in any security, financial instrument or
            investment product. Use of the Website does not create an
            adviser-client, fiduciary or other professional relationship.
          </p>
          <p>
            You are solely responsible for your research and decisions. Obtain
            advice from appropriately licensed professionals and verify material
            information against original filings and other authoritative sources
            before acting. Do not make an investment or other material decision
            solely from Content displayed on the Website.
          </p>
        </LegalSection>

        <LegalSection number="3" title="Investment risk">
          <p>
            Investing involves risk, including possible loss of principal.
            Historical filings, reported ownership, portfolio activity and past
            performance do not predict future holdings, prices, performance or
            results. A reported position does not establish that a filer still
            owns the position or intends to buy, sell or hold it.
          </p>
        </LegalSection>

        <LegalSection number="4" title="Data sources and attribution">
          <p>
            The Website primarily uses publicly disseminated Form 13F and related
            data obtained from SEC.gov and EDGAR. 13fdata.net does not claim
            ownership of underlying SEC filings or works of the United States
            government.
          </p>
          <p>
            Filings and third-party sources may contain material subject to
            separate rights. Names, trademarks, service marks, logos and other
            protected material remain the property of their respective owners.
            Use, reference or linking does not grant a license or imply
            affiliation, sponsorship or endorsement.
          </p>
          <div className="legal-sources" aria-label="Source references">
            <SourceLink href="https://www.sec.gov/about/privacy-information">
              SEC privacy, dissemination and trademark information
            </SourceLink>
            <SourceLink href="https://uscode.house.gov/view.xhtml?edition=2023&num=0&req=granuleid%3AUSC-2023-title17-section105">
              17 U.S.C. §105 — United States government works
            </SourceLink>
          </div>
        </LegalSection>

        <LegalSection number="5" title="Source-data limitations">
          <p>
            Source filings are prepared by third-party filers and may be
            inaccurate, incomplete, delayed, amended, duplicated, inconsistently
            formatted or subject to confidential treatment. Filings generally
            reflect holdings as of a past reporting date and may be published
            weeks later. They do not provide a complete or real-time view of a
            filer’s assets, exposures, transactions, strategies or performance.
          </p>
          <p>
            Form 13F data may omit non-reportable securities, short positions,
            cash and other assets. Reported values are filing values, not live
            market prices. Shared investment discretion, amendments and
            confidential treatment can affect interpretation.
          </p>
        </LegalSection>

        <LegalSection number="6" title="Processing, classifications and errors">
          <p>
            13fdata.net processes source data using automated and manual rules,
            including amendment resolution, unit normalization, entity matching,
            security classification, aggregation and inferred
            quarter-to-quarter activity. These processes may introduce or
            preserve errors, omissions, duplication, incorrect matches,
            inconsistent units or misleading results.
          </p>
          <p>
            Unless expressly stated otherwise, quantities and inferred actions
            are not adjusted for stock splits, corporate actions or changes in
            security identifiers. Tickers, issuer names, security classes, SIC
            classifications and other reference attributes may be stale,
            incomplete or incorrect. Aggregated or inferred Content may not match
            a user’s independent calculation.
          </p>
          <p>
            The Website is operated in good faith and is not intended to deceive
            or mislead. Errors may be corrected, data may be revised, and
            methodology or features may change at any time without notice.
          </p>
        </LegalSection>

        <LegalSection number="7" title="No warranties">
          <p className="legal-emphasis">
            To the fullest extent permitted by applicable law, the Website and
            all Content are provided “as is” and “as available,” without any
            representation or warranty of any kind, express, implied or
            statutory.
          </p>
          <p>
            13fdata.net disclaims warranties of accuracy, completeness,
            timeliness, reliability, availability, merchantability, fitness for a
            particular purpose, title, non-infringement, security and freedom from
            harmful components. Continuous, uninterrupted, error-free or secure
            operation is not guaranteed.
          </p>
        </LegalSection>

        <LegalSection number="8" title="Limitation of liability">
          <p className="legal-emphasis">
            To the fullest extent permitted by applicable law, 13fdata.net and
            its operators, contributors, affiliates, service providers and
            licensors will not be liable for any loss, damage, claim, liability,
            cost or expense arising out of or relating to the Website, the
            Content, any error or omission, unavailable service, unauthorized
            access, or any decision or action taken in reliance on the Website.
          </p>
          <p>
            This exclusion includes direct, indirect, incidental, consequential,
            special, exemplary and punitive damages; loss of profits, revenue,
            opportunity, goodwill or data; investment or trading losses; and
            third-party claims, under any legal theory, even if the possibility of
            harm was known or foreseeable.
          </p>
          <p>
            Some jurisdictions do not permit certain exclusions or limitations.
            In those jurisdictions, each exclusion or limitation applies only to
            the maximum extent permitted by applicable law.
          </p>
        </LegalSection>

        <LegalSection number="9" title="Third-party links and services">
          <p>
            Third-party links and references are provided for convenience.
            13fdata.net does not control and is not responsible for third-party
            content, products, availability, accuracy, security, privacy, terms
            or practices. You access third-party resources at your own risk, and a
            link does not imply endorsement by either party.
          </p>
        </LegalSection>

        <LegalSection number="10" title="Availability and changes">
          <p>
            Access to the Website may be limited, suspended or discontinued, and
            Content may be changed or removed, at any time without notice.
            13fdata.net may revise this Disclaimer by posting an updated version
            on this page. Continued use after an update means the updated
            Disclaimer applies to that use.
          </p>
        </LegalSection>

        <LegalSection number="11" title="Severability">
          <p>
            If any provision of this Disclaimer is found invalid, unlawful or
            unenforceable, that provision will be applied to the greatest extent
            permitted and the remaining provisions will remain in effect.
          </p>
        </LegalSection>
      </div>
    </article>
  );
}

function LegalSection({ number, title, children }) {
  return (
    <section className="legal-section">
      <h2>
        <span>{number}.</span> {title}
      </h2>
      {children}
    </section>
  );
}

function SourceLink({ href, children }) {
  return (
    <a className="legal-source" href={href} target="_blank" rel="noreferrer">
      {children} <ExternalLink size={13} />
    </a>
  );
}
