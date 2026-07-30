# 13f-data.com Ubuntu deployment

This runtime package contains the built React frontend, FastAPI backend,
production service configuration and Nginx reverse proxy. It intentionally
excludes the SQLite database, ETL programs, SEC ZIP archives and extracted TSV
files.

## Server paths

| Purpose | Path |
|---|---|
| Application releases | `/opt/13f-data/releases/` |
| Active release | `/opt/13f-data/current` |
| Python environment | `/opt/13f-data/venv` |
| SQLite database | `/srv/13f-data/data/form13f.sqlite3` |
| Runtime environment | `/etc/13f-data/13f-data.env` |
| Service logs | `journalctl -u 13f-data` |

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

The installer creates an unprivileged `13fdata` service account, installs
Python and Nginx, creates a virtual environment, validates the web-server
configuration, starts the application and checks `/api/health`.

## HTTPS and domain

Do not expose the site as plain HTTP. Choose one of these approaches:

1. Put `13f-data.com` behind Cloudflare and route a Cloudflare Tunnel to
   `http://localhost:80`.
2. Point DNS to the instance, install Certbot, and issue a certificate for
   `13f-data.com` and `www.13f-data.com`.

If using a Cloudflare Tunnel, close public ports 80 and 443 in the Lightsail
firewall after verifying the tunnel. If using direct DNS, keep ports 80 and 443
open and restrict SSH access.

## Operations

```bash
sudo systemctl status 13f-data
sudo journalctl -u 13f-data -n 100 --no-pager
curl -H 'Host: 13f-data.com' http://127.0.0.1/api/health
```

The production service runs the database in SQLite read-only mode. API
documentation endpoints are disabled when `APP_ENV=production`.

## Database updates

Upload a new database beside the active one, validate it, stop the application,
swap filenames atomically, and restart. Do not overwrite a database while the
application is running.
