import { ExternalLink } from "lucide-react";
import { PageHeader } from "../components/UI";

export function DisclaimersPage() {
  return (
    <>
      <PageHeader
        eyebrow="Important information"
        title="Disclaimers"
        description="Please read these disclosures before using DeepMarkets or relying on any information displayed by the website."
      />

      <section className="panel legal-intro">
        <strong>Use DeepMarkets at your own risk.</strong>
        <p>
          The website is an independent research and data-visualization project.
          It is not affiliated with, sponsored by, approved by or endorsed by the
          U.S. Securities and Exchange Commission, EDGAR, any reporting
          institution, any security issuer or any other government agency or
          market participant.
        </p>
      </section>

      <div className="legal-grid">
        <LegalSection title="Informational purposes only">
          <p>
            All content, data, calculations, classifications, rankings, charts,
            comparisons and other materials are provided solely for general
            informational, educational and research purposes. Nothing on this
            website is investment, financial, legal, tax, accounting or other
            professional advice.
          </p>
          <p>
            Nothing on this website is an offer, solicitation, recommendation,
            endorsement or invitation to buy, sell, hold or otherwise transact in
            any security or investment product. Use of the website does not create
            an adviser-client, fiduciary or other professional relationship.
          </p>
        </LegalSection>

        <LegalSection title="Independent decisions">
          <p>
            You are solely responsible for your research and decisions. Consult
            appropriately licensed financial, legal, tax and other professional
            advisers before acting. Verify information against original SEC
            filings and other authoritative sources. Never make an investment or
            other material decision solely from information displayed here.
          </p>
          <p>
            Historical filings, ownership changes and past activity do not predict
            future holdings, prices, performance or results. All investing involves
            risk, including possible loss of principal.
          </p>
        </LegalSection>

        <LegalSection title="Public data and attribution">
          <p>
            The primary source is publicly disseminated Form 13F and related data
            obtained from SEC.gov and EDGAR. The SEC states that information
            presented on SEC.gov is public information that may be copied or
            redistributed, with appropriate source citation encouraged.
          </p>
          <p>
            DeepMarkets does not claim ownership of the underlying SEC filings or
            U.S. government works. However, filings may contain material supplied
            by third parties, and names, trademarks, service marks, logos and other
            protected material remain the property of their respective owners. No
            license, affiliation or endorsement should be inferred.
          </p>
          <SourceLink href="https://www.sec.gov/about/privacy-information">
            SEC website dissemination and trademark policy
          </SourceLink>
          <SourceLink href="https://uscode.house.gov/view.xhtml?edition=2023&num=0&req=granuleid%3AUSC-2023-title17-section105">
            17 U.S.C. §105 — U.S. government works
          </SourceLink>
        </LegalSection>

        <LegalSection title="Data limitations and possible errors">
          <p>
            Source filings are prepared by third-party filers and may be inaccurate,
            incomplete, amended, delayed, duplicated, inconsistently formatted or
            subject to confidential treatment. The SEC generally preserves original
            filings alongside later corrections.
          </p>
          <p>
            DeepMarkets processes source data through automated and manual rules,
            including amendment resolution, value normalization, entity matching,
            security classification, aggregation and inferred quarter-to-quarter
            actions. These processes may introduce errors, omissions, incorrect
            matches or misleading results. Quantities and actions are not adjusted
            for stock splits or other corporate actions unless expressly stated.
            Data is historical filing data, not live market data.
          </p>
          <p>
            The website is operated in good faith and is not intended to deceive or
            mislead. Nevertheless, no representation or warranty is made that any
            content is accurate, complete, current, consistent, useful or suitable
            for a particular purpose. Errors may be corrected, data may be revised,
            and features may change without notice.
          </p>
        </LegalSection>

        <LegalSection title="No warranties">
          <p>
            To the fullest extent permitted by applicable law, the website and all
            content are provided “as is” and “as available,” without warranties of
            any kind, express, implied or statutory. This includes warranties of
            accuracy, completeness, timeliness, merchantability, fitness for a
            particular purpose, title, non-infringement, availability, security and
            freedom from harmful components.
          </p>
          <p>
            Continuous, uninterrupted, error-free or secure operation is not
            guaranteed. Access may be limited, suspended or discontinued, and
            content may be modified or removed at any time.
          </p>
        </LegalSection>

        <LegalSection title="Limitation of liability">
          <p>
            To the fullest extent permitted by applicable law, DeepMarkets, its
            operators, contributors, affiliates, service providers and licensors
            will not be responsible or liable for any loss, damage, claim, cost or
            expense arising from or related to the website, its data, any error or
            omission, unavailable service, or any decision made in reliance on the
            website.
          </p>
          <p>
            This limitation includes direct, indirect, incidental, consequential,
            special, exemplary and punitive damages; loss of profits, revenue,
            opportunity, goodwill or data; trading or investment losses; and claims
            by third parties, whether based in contract, tort, negligence, strict
            liability or any other theory, even if the possibility of harm was
            known or foreseeable.
          </p>
          <p>
            Some jurisdictions do not allow certain warranty exclusions or
            liability limitations. In those jurisdictions, these provisions apply
            only to the maximum extent legally permitted.
          </p>
        </LegalSection>

        <LegalSection title="Third-party services and links">
          <p>
            References or links to the SEC, issuers, reporting institutions or
            other third parties are provided for convenience. DeepMarkets does not
            control and is not responsible for third-party content, availability,
            privacy, security, terms, accuracy or practices. A link does not imply
            endorsement by either party.
          </p>
        </LegalSection>

        <LegalSection title="Changes and severability">
          <p>
            These disclaimers may be updated at any time without prior notice.
            Continued use after an update constitutes use subject to the revised
            disclosures. If any provision is found invalid or unenforceable, the
            remaining provisions should continue to apply to the fullest extent
            permitted by law.
          </p>
          <p className="legal-updated">Last updated: July 29, 2026.</p>
        </LegalSection>
      </div>
    </>
  );
}

function LegalSection({ title, children }) {
  return (
    <section className="panel legal-section">
      <h2>{title}</h2>
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
