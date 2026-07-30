#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this command as root: sudo ./deploy/activate.sh" >&2
  exit 1
fi

DATABASE="/srv/13f-data/data/form13f.sqlite3"
if [[ ! -f "$DATABASE" ]]; then
  echo "Database not found: $DATABASE" >&2
  exit 1
fi

chown root:13fdata "$DATABASE"
chmod 0640 "$DATABASE"

python3 - "$DATABASE" <<'PY'
import sqlite3
import sys

database = sys.argv[1]
connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite quick_check failed: {result}")
    required = {
        "CIK",
        "CUSIP",
        "QUARTER",
        "CIK_INSTRUMENT_QUARTER",
        "CIK_QUARTER_SUMMARY",
        "CUSIP_QUARTER_SUMMARY",
    }
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = sorted(required - existing)
    if missing:
        raise SystemExit(f"Database is missing required tables: {', '.join(missing)}")
finally:
    connection.close()
PY

systemctl restart 13f-data.service
systemctl restart nginx
sleep 2
curl --fail --silent --show-error \
  -H "Host: 13f-data.com" \
  http://127.0.0.1/api/health
echo
echo "Database validated and 13f-data.com activated."
