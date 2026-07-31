#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this command as root: sudo ./deploy/activate.sh" >&2
  exit 1
fi

DATABASE="/srv/13f-data/data/form13f.sqlite3"
SKIP_QUICK_CHECK="${SKIP_SQLITE_QUICK_CHECK:-0}"
if [[ ! -f "$DATABASE" ]]; then
  echo "Database not found: $DATABASE" >&2
  exit 1
fi

chown root:13fdata "$DATABASE"
chmod 0640 "$DATABASE"

python3 - "$DATABASE" "$SKIP_QUICK_CHECK" <<'PY'
import sqlite3
import sys

database = sys.argv[1]
skip_quick_check = sys.argv[2] == "1"
connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    if not skip_quick_check:
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
    for table in sorted(required):
        connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
finally:
    connection.close()
PY

if [[ "$SKIP_QUICK_CHECK" == "1" ]]; then
  echo "Skipped SQLite quick_check for an externally hash-verified database."
fi

systemctl restart 13f-data.service
systemctl restart nginx
sleep 2
if [[ -f /etc/letsencrypt/live/13fdata.net/fullchain.pem ]]; then
  curl --fail --silent --show-error \
    --resolve 13fdata.net:443:127.0.0.1 \
    https://13fdata.net/api/health
else
  curl --fail --silent --show-error \
    -H "Host: 13fdata.net" \
    http://127.0.0.1/api/health
fi
echo
echo "Database validated and 13fdata.net activated."
