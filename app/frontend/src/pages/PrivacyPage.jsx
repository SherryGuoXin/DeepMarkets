import { ExternalLink } from "lucide-react";

const LAST_UPDATED = "November 14, 2026";

export function PrivacyPage() {
  return (
    <article className="panel legal-document">
      <header className="legal-document-header">
        <span className="eyebrow">Legal</span>
        <h1>Privacy Policy</h1>
        <p className="legal-effective">Last updated: {LAST_UPDATED}</p>
      </header>

      <div className="legal-notice">
        <strong>Privacy overview</strong>
        <p>
          This policy describes the limited technical information used to
          operate 13fdata.net and the advertising services that may appear on
          the Website.
        </p>
      </div>

      <div className="legal-body">
        <PrivacySection number="1" title="Information handled by the Website">
          <p>
            The Website does not require an account and does not ask visitors
            to submit personal financial information. Web servers and security
            services may process ordinary request information such as IP
            address, browser and device details, requested pages, timestamps
            and diagnostic or security events.
          </p>
        </PrivacySection>

        <PrivacySection number="2" title="Google advertising">
          <p>
            The Website uses Google AdSense. Google and its advertising
            partners may use cookies, local storage or similar technologies to
            deliver, limit, personalize and measure advertising, subject to
            applicable consent choices and Google settings.
          </p>
          <p>
            Learn more about how Google uses information in advertising and
            how to control advertising choices through the links below.
          </p>
          <div className="legal-sources" aria-label="Google privacy resources">
            <PrivacyLink href="https://policies.google.com/technologies/ads">
              Google advertising technologies
            </PrivacyLink>
            <PrivacyLink href="https://myadcenter.google.com/">
              Google My Ad Center
            </PrivacyLink>
          </div>
        </PrivacySection>

        <PrivacySection number="3" title="Consent choices">
          <p>
            Where required, visitors may be shown a consent message before
            advertising technologies are used. Available choices may include
            accepting, rejecting or managing advertising purposes. Browser
            controls may also be used to delete or block cookies, although
            doing so can affect site or advertising functionality.
          </p>
        </PrivacySection>

        <PrivacySection number="4" title="Communications">
          <p>
            If you contact 13fdata.net by email, the submitted address and
            message are used to review and respond to the inquiry and to
            maintain necessary correspondence records.
          </p>
        </PrivacySection>

        <PrivacySection number="5" title="Third-party services and retention">
          <p>
            Hosting, security, content-delivery and advertising providers may
            process technical information under their own terms and privacy
            policies. Operational records are retained only as reasonably
            needed for security, diagnostics, legal obligations and reliable
            service operation.
          </p>
        </PrivacySection>

        <PrivacySection number="6" title="Questions and updates">
          <p>
            Privacy questions may be sent to i13fdata@hotmail.com. This policy
            may be updated as the Website, its providers or applicable
            requirements change. The current version and update date will be
            posted on this page.
          </p>
        </PrivacySection>
      </div>
    </article>
  );
}

function PrivacySection({ number, title, children }) {
  return (
    <section className="legal-section">
      <h2><span>{number}.</span> {title}</h2>
      {children}
    </section>
  );
}

function PrivacyLink({ href, children }) {
  return (
    <a className="legal-source" href={href} target="_blank" rel="noreferrer">
      {children} <ExternalLink size={13} />
    </a>
  );
}
