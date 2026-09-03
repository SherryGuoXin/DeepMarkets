export function money(value, compact = true) {
  if (value === null || value === undefined) return "—";
  const absolute = Math.abs(Number(value));
  const sign = Number(value) < 0 ? "−" : "";
  if (compact) {
    const levels = [
      [1e12, "T"],
      [1e9, "B"],
      [1e6, "M"],
      [1e3, "K"],
    ];
    const level = levels.find(([size]) => absolute >= size);
    if (level) {
      return `${sign}$${(absolute / level[0]).toFixed(absolute / level[0] >= 100 ? 0 : 1)}${level[1]}`;
    }
  }
  return `${sign}${new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(absolute)}`;
}

export function number(value, compact = false) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 0,
  }).format(value);
}

export function percent(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function signedPercent(value) {
  if (value === null || value === undefined) return "—";
  const normalized = Number(value) * 100;
  return `${normalized > 0 ? "+" : ""}${normalized.toFixed(1)}%`;
}

export function titleCase(value) {
  return value
    ? value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : "—";
}

export function actionLabel(action) {
  const labels = {
    NEW: "Newly reported",
    ADDED: "Reported shares increased",
    REDUCED: "Reported shares decreased",
    EXITED: "No longer reported",
    UNCHANGED: "Reported shares unchanged",
    UNKNOWN: "Not comparable",
  };
  return labels[action] || titleCase(action);
}

export function date(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}
