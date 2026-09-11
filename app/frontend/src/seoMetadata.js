const SITE_NAME = "13fdata.net";
const SITE_URL = "https://13fdata.net";
const BASE_KEYWORDS = [
  "SEC Form 13F", "13F filings", "institutional holdings",
  "institutional investors", "securities", "investment managers",
  "portfolio holdings", "SEC EDGAR",
];

export function applySeo(seo) {
  const canonicalUrl = seo.canonicalUrl;
  document.title = seo.title;
  setMeta("name", "description", seo.description);
  setMeta("name", "keywords", [...BASE_KEYWORDS, ...(seo.keywords || [])].join(", "));
  setMeta("name", "robots", seo.noIndex ? "noindex, nofollow" : "index, follow");
  setMeta("property", "og:type", "website");
  setMeta("property", "og:site_name", SITE_NAME);
  setMeta("property", "og:title", seo.title);
  setMeta("property", "og:description", seo.description);
  setMeta("property", "og:url", canonicalUrl);
  setMeta("name", "twitter:card", "summary");
  setMeta("name", "twitter:title", seo.title);
  setMeta("name", "twitter:description", seo.description);
  let canonical = document.head.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement("link");
    canonical.rel = "canonical";
    document.head.appendChild(canonical);
  }
  canonical.href = canonicalUrl;

  const structuredData = seo.structuredData || {
    "@context": "https://schema.org",
    "@type": seo.pageType || "WebPage",
    name: seo.title,
    description: seo.description,
    url: canonicalUrl,
    isPartOf: { "@type": "WebSite", name: SITE_NAME, url: SITE_URL },
    about: {
      "@type": "Dataset",
      name: "SEC Form 13F institutional holdings",
      description: "Institutional holdings, reported values, quantities and quarter-over-quarter changes derived from public SEC Form 13F filings.",
      creator: {
        "@type": "Organization",
        name: "U.S. Securities and Exchange Commission",
        url: "https://www.sec.gov/",
      },
    },
  };
  let schema = document.getElementById("route-seo-schema");
  if (!schema) {
    schema = document.createElement("script");
    schema.id = "route-seo-schema";
    schema.type = "application/ld+json";
    document.head.appendChild(schema);
  }
  schema.textContent = JSON.stringify(structuredData);
}

function setMeta(attribute, key, content) {
  let element = document.head.querySelector(`meta[${attribute}="${key}"]`);
  if (!element) {
    element = document.createElement("meta");
    element.setAttribute(attribute, key);
    document.head.appendChild(element);
  }
  element.setAttribute("content", content);
}
