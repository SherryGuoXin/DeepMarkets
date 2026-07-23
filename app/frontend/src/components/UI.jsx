import {
  AlertCircle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpDown,
  Database,
  Info,
  LoaderCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { titleCase } from "../format";

export function PageHeader({ eyebrow, title, description, back, actions }) {
  return (
    <div className="page-header">
      <div>
        {back && (
          <Link className="back-link" to={back}>
            <ArrowLeft size={15} /> Back
          </Link>
        )}
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="header-actions">{actions}</div>}
    </div>
  );
}

export function SectionHeader({ title, description, action }) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function MetricCard({ label, value, detail, tone, icon: Icon }) {
  return (
    <div className={`metric-card ${tone ? `metric-${tone}` : ""}`}>
      <div className="metric-label">
        <span>{label}</span>
        {Icon && <Icon size={17} />}
      </div>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

export function QuarterSelect({ quarters, value, onChange, compact = false }) {
  return (
    <label className={compact ? "field field-compact" : "field"}>
      {!compact && <span>Report quarter</span>}
      <select
        value={value || ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {quarters.map((quarter) => (
          <option key={quarter.quarter_id} value={quarter.quarter_id}>
            {quarter.quarter_label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ActionBadge({ action }) {
  const normalized = action || "UNCHANGED";
  return (
    <span className={`action-badge action-${normalized.toLowerCase()}`}>
      {titleCase(normalized)}
    </span>
  );
}

export function LoadingState({ label = "Loading analytical data" }) {
  return (
    <div className="state-card">
      <LoaderCircle className="spin" size={24} />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error }) {
  return (
    <div className="state-card state-error">
      <AlertCircle size={24} />
      <div>
        <strong>Unable to load this view</strong>
        <span>{error?.message || "An unexpected error occurred."}</span>
      </div>
    </div>
  );
}

export function EmptyState({ title = "No data for this selection", detail }) {
  return (
    <div className="state-card">
      <Database size={24} />
      <div>
        <strong>{title}</strong>
        {detail && <span>{detail}</span>}
      </div>
    </div>
  );
}

export function DataNotice({ children }) {
  return (
    <div className="data-notice">
      <Info size={17} />
      <span>{children}</span>
    </div>
  );
}

export function Pager({ page, hasMore, onChange }) {
  return (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>
        Previous
      </button>
      <span>Page {page}</span>
      <button disabled={!hasMore} onClick={() => onChange(page + 1)}>
        Next
      </button>
    </div>
  );
}

export function Tabs({ items, value, onChange }) {
  return (
    <div className="tabs">
      {items.map((item) => (
        <button
          key={item.value}
          className={value === item.value ? "active" : ""}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function SortableHeader({
  label,
  field,
  sortBy,
  direction,
  onSort,
  numeric = false,
}) {
  const active = sortBy === field;
  const Icon = active ? (direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <th className={numeric ? "numeric" : ""}>
      <button
        className={`sort-header ${active ? "active" : ""}`}
        onClick={() => onSort(field)}
        title={`Sort by ${label}`}
      >
        <span>{label}</span>
        <Icon size={12} />
      </button>
    </th>
  );
}
