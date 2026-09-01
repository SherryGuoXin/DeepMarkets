# 13fdata.net Ubuntu deployment

This runtime package contains the built React frontend, FastAPI backend, daily
EDGAR importer, production service configuration and Nginx reverse proxy. It
excludes the SQLite database, bulk SEC ZIP archives and extracted TSV files.

## Server paths

| Purpose | Path |
|---|---|
| Application releases | `/opt/13f-data/releases/` |
| Active release | `/opt/13f-data/current` |
| Python environment | `/opt/13f-data/venv` |
| SQLite database | `/srv/13f-data/data/form13f.sqlite3` |
| Runtime environment | `/etc/13f-data/13f-data.env` |
| Service logs | `journalctl -u 13f-data` |
| Daily update logs | `journalctl -u 13f-data-daily.service` |

## Upload

Upload this archive and its checksum to the Ubuntu user's home directory. Upload
the database separately and use a partial-transfer-capable tool such as
`rsync`. Never place the database inside the web root or Git repository.

After extracting the archive, verify it:

```bash
sha256sum -c 13f-data-runtime-<version>.tar.gz.sha256
tar -xzf 13f-data-runtime-<version>.tar.gz
cd 13f-data-runtime-<version>
```

Create the database directory and move the uploaded database into place:

```bash
sudo install -d -m 0750 -o root -g root /srv/13f-data/data
sudo mv ~/form13f.sqlite3 /srv/13f-data/data/form13f.sqlite3
```

Install the runtime:

```bash
sudo ./deploy/install.sh
```

The default activation runs SQLite `PRAGMA quick_check`. For a large database
whose SHA-256 was independently verified against a known-good source, the full
page scan can be skipped while retaining required-table and live-query checks:

```bash
sudo env SKIP_SQLITE_QUICK_CHECK=1 ./deploy/install.sh
```

The installer creates an unprivileged `13fdata` service account, installs
Python and Nginx, creates a virtual environment, validates the web-server
configuration, applies the production SSH policy, enables UFW for SSH/HTTP/HTTPS,
starts the application and checks `/api/health`. When a Let's Encrypt
certificate already exists, the installer preserves HTTPS and HSTS during
subsequent releases.

## HTTPS and domain

Do not expose the site as plain HTTP. Choose one of these approaches:

1. Put `13fdata.net` behind Cloudflare and route a Cloudflare Tunnel to
   `http://localhost:80`.
2. Point DNS to the instance, install Certbot, and issue a certificate for
   `13fdata.net` and `www.13fdata.net`.

If using a Cloudflare Tunnel, close public ports 80 and 443 in the Lightsail
firewall after verifying the tunnel. If using direct DNS, keep ports 80 and 443
open and restrict SSH access.

## Operations

```bash
sudo systemctl status 13f-data
sudo journalctl -u 13f-data -n 100 --no-pager
curl -H 'Host: 13fdata.net' http://127.0.0.1/api/health
```

The production service runs the database in SQLite read-only mode. API
documentation endpoints are disabled when `APP_ENV=production`.

## Daily updates

Set an SEC-compliant identity in `/etc/13f-data/13f-data.env`:

```bash
SEC_USER_AGENT=13fdata.net admin@example.com
```

`13f-data-daily.timer` runs at 10:00 PM Toronto time Monday through Friday and
retries at 7:00 AM Tuesday through Saturday. The updater stops public traffic,
drops database write access to the unprivileged `13fupdate` account, imports and
publishes incremental institution data in batches of 50, then restores database
permissions and both services on success or failure.

```bash
sudo systemctl list-timers 13f-data-daily.timer
sudo journalctl -u 13f-data-daily.service -n 100 --no-pager
```

## Database updates

Upload a new database beside the active one, validate it, stop the application,
swap filenames atomically, and restart. Do not overwrite a database while the
application is running.

## Update an existing server release

Commit first because `build_release.sh` refuses a dirty worktree. The runtime
archive excludes the SQLite database and downloaded SEC files.

On the development Mac:

```bash
git add -A
git commit -m "Describe the release"
git push origin feature/daily-edgar-updates
./deploy/build_release.sh

RELEASE_VERSION="$(git rev-parse --short HEAD)"
SERVER_IP="replace-with-current-server-ip"
scp -i LightsailDefaultKey-us-east-1.pem \
  "artifacts/13f-data-runtime-${RELEASE_VERSION}.tar.gz" \
  "artifacts/13f-data-runtime-${RELEASE_VERSION}.tar.gz.sha256" \
  "ubuntu@${SERVER_IP}:~/"
```

On Ubuntu, verify and stage the immutable release. Do not rerun `install.sh` for
a code-only release because it also reapplies SSH and firewall configuration.

```bash
RELEASE_VERSION="replace-with-release-version"
cd ~
sha256sum -c "13f-data-runtime-${RELEASE_VERSION}.tar.gz.sha256"
tar -xzf "13f-data-runtime-${RELEASE_VERSION}.tar.gz"
readlink -f /opt/13f-data/current

sudo install -d -m 0755 "/opt/13f-data/releases/${RELEASE_VERSION}"
sudo cp -a \
  "13f-data-runtime-${RELEASE_VERSION}/app" \
  "13f-data-runtime-${RELEASE_VERSION}/etl" \
  "13f-data-runtime-${RELEASE_VERSION}/VERSION" \
  "/opt/13f-data/releases/${RELEASE_VERSION}/"
sudo chown -R root:root "/opt/13f-data/releases/${RELEASE_VERSION}"
```

Confirm the daily writer is inactive before deployment. Stop the timer and
public traffic, switch the symlink, then start the application privately and
restore Nginx only after the health check passes.

```bash
sudo systemctl is-active 13f-data-daily.service
sudo systemctl stop 13f-data-daily.timer
sudo systemctl stop nginx
sudo systemctl stop 13f-data.service
sudo ln -sfn "/opt/13f-data/releases/${RELEASE_VERSION}" /opt/13f-data/current
```

For the option-only classification release, refresh only its small dimensions
and partial-quarter security materializations. This does not download filings
or start the SEC importer:

```bash
cd /opt/13f-data/current
sudo env PYTHONPATH=/opt/13f-data/current \
  /opt/13f-data/venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path

from etl.build_instruments import (
    migrate_classification_method_constraint,
    refresh_option_only_classifications,
    seed_reference_data,
)

database = Path("/srv/13f-data/data/form13f.sqlite3")
connection = sqlite3.connect(database, timeout=120)
connection.execute("PRAGMA foreign_keys = ON")
connection.execute("PRAGMA temp_store = FILE")
connection.execute("BEGIN IMMEDIATE")
migrate_classification_method_constraint(connection)
seed_reference_data(connection)
print(refresh_option_only_classifications(connection))
daily_rows = connection.execute(
    """
    UPDATE DAILY_CUSIP_QUARTER_SUMMARY
    SET SECURITY_TYPE = CASE
        WHEN CALL_VALUE_USD > 0 AND PUT_VALUE_USD = 0 THEN 'OPTION_CALL'
        WHEN PUT_VALUE_USD > 0 AND CALL_VALUE_USD = 0 THEN 'OPTION_PUT'
        ELSE 'OPTION'
    END
    WHERE TOTAL_VALUE_USD - CALL_VALUE_USD - PUT_VALUE_USD = 0
      AND (CALL_VALUE_USD > 0 OR PUT_VALUE_USD > 0)
    """
).rowcount
print(daily_rows)
connection.commit()
connection.close()
PY
```

Start and verify the private application before restoring traffic:

```bash

sudo systemctl start 13f-data.service
curl --fail http://127.0.0.1:8000/api/health
sudo systemctl start nginx
sudo systemctl start 13f-data-daily.timer
curl --fail https://13fdata.net/api/health
```

If activation fails, keep Nginx stopped, point `/opt/13f-data/current` back to
the release printed by `readlink`, restart the application, verify its private
health endpoint, and then restart Nginx.
