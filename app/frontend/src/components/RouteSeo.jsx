import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { applySeo } from "../seoMetadata";

const SITE_NAME = "13fdata.net";
const SITE_URL = "https://13fdata.net";

const STATIC_PAGES = {
  "/": {
    title: "SEC Form 13F Institutional Holdings & Ownership | 13fdata.net",
    description:
      "Explore SEC Form 13F filings, institutional holdings, reported portfolio values, securities ownership and quarter-to-quarter position changes.",
    keywords: ["13F data", "institutional ownership", "SEC filings database"],
  },
  "/institutions": {
    title: "Institutional Investors & SEC 13F Holdings | 13fdata.net",
    description:
      "Rank and filter institutional investment managers by SEC Form 13F portfolio value, holdings and quarterly reporting changes.",
    keywords: ["institution rankings", "13F investment managers", "institution portfolios"],
  },
  "/latest-filings": {
    title: "Latest SEC Form 13F Filings | 13fdata.net",
    description:
      "See the most recently filed institutional Form 13F reports, including filing date, report period, reported assets and holding count.",
    keywords: ["latest 13F filings", "recent institutional filings", "SEC 13F updates"],
  },
  "/securities": {
    title: "Securities Held by Institutions in SEC 13F Filings | 13fdata.net",
    description:
      "Find securities reported in SEC Form 13F filings and compare institutional value, investors and quarterly reporting changes.",
    keywords: ["CUSIP holdings", "institutional securities", "security ownership"],
  },
  "/compare": {
    title: "Compare SEC Form 13F Holdings by Quarter | 13fdata.net",
    description:
      "Compare institutional portfolios and security ownership between SEC Form 13F reporting quarters, including reported value and position changes.",
    keywords: ["13F quarter comparison", "portfolio changes", "ownership history"],
  },
  "/activity": {
    title: "Quarterly 13F Position Changes | 13fdata.net",
    description:
      "Explore newly reported, no-longer-reported and changed positions in institutional SEC Form 13F filings.",
    keywords: ["newly reported institutional positions", "13F reporting changes", "institutional holdings changes"],
  },
  "/disclaimers": {
    title: "Website Disclaimer | 13fdata.net",
    description:
      "Read the 13fdata.net legal disclaimer, SEC Form 13F data limitations, methodology risks, warranty exclusions and terms of informational use.",
    keywords: ["13F data disclaimer", "SEC filing limitations"],
    noIndex: false,
  },
};

export function RouteSeo() {
  const { pathname } = useLocation();

  useEffect(() => {
    const normalizedPath = pathname !== "/" ? pathname.replace(/\/+$/, "") : "/";
    const serverSeo = readServerSeo(normalizedPath);
    const seo = serverSeo || seoForPath(normalizedPath);
    const canonicalUrl = serverSeo?.canonicalUrl
      || `${SITE_URL}${normalizedPath === "/" ? "" : normalizedPath}`;

    applySeo({ ...seo, canonicalUrl });
  }, [pathname]);

  return null;
}

function readServerSeo(pathname) {
  const element = document.getElementById("server-route-seo");
  if (!element) return null;
  try {
    const seo = JSON.parse(element.textContent);
    const url = new URL(seo.canonicalUrl);
    const canonicalPath = url.pathname !== "/" ? url.pathname.replace(/\/+$/, "") : "/";
    return canonicalPath === pathname ? seo : null;
  } catch {
    return null;
  }
}

function seoForPath(pathname) {
  if (STATIC_PAGES[pathname]) return STATIC_PAGES[pathname];

  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "institutions" && parts[1]) {
    const cik = decodeURIComponent(parts[1]);
    return {
      title: `CIK ${cik} Institutional 13F Holdings | ${SITE_NAME}`,
      description:
        `Review SEC Form 13F holdings, reported portfolio value, securities, allocation and quarterly activity for institutional manager CIK ${cik}.`,
      keywords: [`CIK ${cik}`, "institution profile", "institution holdings history"],
    };
  }
  if (parts[0] === "securities" && parts[1]) {
    const cusip = decodeURIComponent(parts[1]);
    return {
      title: `CUSIP ${cusip} Institutional Ownership | ${SITE_NAME}`,
      description:
        `Review institutional ownership, reported holding value, investment managers and quarterly SEC Form 13F history for CUSIP ${cusip}.`,
      keywords: [`CUSIP ${cusip}`, "security holders", "institutional ownership history"],
    };
  }
  if (parts[0] === "relationships" && parts[1] && parts[2]) {
    const cik = decodeURIComponent(parts[1]);
    const cusip = decodeURIComponent(parts[2]);
    return {
      title: `CIK ${cik} × CUSIP ${cusip} 13F History | ${SITE_NAME}`,
      description:
        `Track the SEC Form 13F holding relationship between institutional manager CIK ${cik} and security CUSIP ${cusip} across reported quarters.`,
      keywords: [`CIK ${cik}`, `CUSIP ${cusip}`, "institution security relationship"],
    };
  }

  return {
    title: `SEC Form 13F Data | ${SITE_NAME}`,
    description:
      "Explore institutional investors, securities, reported holdings and ownership changes from SEC Form 13F filings.",
    keywords: ["13F research"],
    noIndex: true,
  };
}
