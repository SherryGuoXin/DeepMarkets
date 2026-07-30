#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root: sudo ./deploy/install.sh" >&2
  exit 1
fi

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PACKAGE_ROOT/VERSION")"
RELEASE_ROOT="/opt/13f-data"
RELEASE_DIR="$RELEASE_ROOT/releases/$VERSION"
DATA_DIR="/srv/13f-data/data"
DATABASE="$DATA_DIR/form13f.sqlite3"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl ca-certificates

if ! id -u 13fdata >/dev/null 2>&1; then
  useradd --system --home /nonexistent --shell /usr/sbin/nologin 13fdata
fi

install -d -m 0755 "$RELEASE_ROOT/releases"
install -d -m 0750 -o root -g 13fdata "$DATA_DIR"
install -d -m 0750 -o root -g 13fdata /etc/13f-data

rm -rf "$RELEASE_DIR"
install -d -m 0755 "$RELEASE_DIR"
cp -a "$PACKAGE_ROOT/app" "$RELEASE_DIR/app"
cp "$PACKAGE_ROOT/VERSION" "$RELEASE_DIR/VERSION"
chown -R root:root "$RELEASE_DIR"

if [[ ! -x "$RELEASE_ROOT/venv/bin/python" ]]; then
  python3 -m venv "$RELEASE_ROOT/venv"
fi
"$RELEASE_ROOT/venv/bin/pip" install --upgrade pip
"$RELEASE_ROOT/venv/bin/pip" install -r "$RELEASE_DIR/app/backend/requirements.txt"

ln -sfn "$RELEASE_DIR" "$RELEASE_ROOT/current"

if [[ ! -f /etc/13f-data/13f-data.env ]]; then
  install -m 0640 -o root -g 13fdata \
    "$PACKAGE_ROOT/deploy/13f-data.env.example" \
    /etc/13f-data/13f-data.env
fi

install -m 0644 "$PACKAGE_ROOT/deploy/13f-data.service" \
  /etc/systemd/system/13f-data.service
install -m 0644 "$PACKAGE_ROOT/deploy/nginx-13f-data.conf" \
  /etc/nginx/sites-available/13f-data
ln -sfn /etc/nginx/sites-available/13f-data /etc/nginx/sites-enabled/13f-data
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl daemon-reload
systemctl enable 13f-data.service nginx

if [[ -f "$DATABASE" ]]; then
  "$PACKAGE_ROOT/deploy/activate.sh"
else
  systemctl stop 13f-data.service 2>/dev/null || true
  systemctl restart nginx
  echo
  echo "Runtime installed, but the database is not present."
  echo "Upload it to: $DATABASE"
  echo "Then run: sudo $PACKAGE_ROOT/deploy/activate.sh"
fi
