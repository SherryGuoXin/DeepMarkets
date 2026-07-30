import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRightLeft,
  Building2,
  ChartNoAxesCombined,
  Menu,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { api } from "../api";

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand" onClick={() => setMenuOpen(false)}>
          <img
            className="brand-mark"
            src="/icon.svg"
            alt=""
            width="40"
            height="40"
          />
          <span>
            <strong>13f-data.com</strong>
            <small>Institutional ownership research</small>
          </span>
        </NavLink>
        <button
          className="icon-button mobile-menu"
          onClick={() => setMenuOpen((value) => !value)}
          aria-label="Toggle navigation"
        >
          {menuOpen ? <X /> : <Menu />}
        </button>
        <nav className={menuOpen ? "nav nav-open" : "nav"}>
          <NavLink to="/" end onClick={() => setMenuOpen(false)}>
            <ChartNoAxesCombined size={17} /> Overview
          </NavLink>
          <NavLink to="/institutions" onClick={() => setMenuOpen(false)}>
            <Building2 size={17} /> Institutions
          </NavLink>
          <NavLink to="/securities" onClick={() => setMenuOpen(false)}>
            <ShieldCheck size={17} /> Securities
          </NavLink>
          <NavLink to="/compare" onClick={() => setMenuOpen(false)}>
            <ArrowRightLeft size={17} /> Compare
          </NavLink>
          <NavLink to="/activity" onClick={() => setMenuOpen(false)}>
            <Activity size={17} /> Activity
          </NavLink>
        </nav>
        <GlobalSearch />
      </header>
      <main className="page-shell">
        <Outlet />
      </main>
      <footer>
        <span>13f-data.com · Institutional ownership research</span>
        <Link className="footer-link" to="/disclaimers">Disclaimers</Link>
      </footer>
    </div>
  );
}

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const wrapper = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const close = (event) => {
      if (!wrapper.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      api("/api/search", { q: query.trim() })
        .then((data) => {
          setResults(data);
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const choose = (result) => {
    const href =
      result.result_type === "institution"
        ? `/institutions/${result.result_id}`
        : `/securities/${result.result_id}`;
    navigate(href);
    setQuery("");
    setOpen(false);
  };

  return (
    <div className="global-search" ref={wrapper}>
      <Search size={17} />
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => results.length && setOpen(true)}
        placeholder="Search CIK, CUSIP or name"
        aria-label="Global search"
      />
      {open && (
        <div className="search-results">
          {results.length ? (
            results.map((result) => (
              <button
                key={`${result.result_type}-${result.result_id}`}
                onClick={() => choose(result)}
              >
                <span className="search-type">{result.result_type}</span>
                <span>
                  <strong>{result.label || result.result_id}</strong>
                  <small>{result.detail}</small>
                </span>
              </button>
            ))
          ) : (
            <div className="search-empty">No matching entities</div>
          )}
        </div>
      )}
    </div>
  );
}
