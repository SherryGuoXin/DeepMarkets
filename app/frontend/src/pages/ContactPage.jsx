import { Mail } from "lucide-react";

export function ContactPage() {
  return (
    <section className="panel contact-panel">
      <span className="eyebrow">Contact</span>
      <h1>Contact us</h1>
      <p>
        If you have any questions or would like custom development, please email us.
      </p>
      <a
        className="primary-button contact-email-button"
        href="mailto:i13fdata@hotmail.com"
        aria-label="Email 13fdata.net"
      >
        <Mail size={16} /> Email us
      </a>
    </section>
  );
}
