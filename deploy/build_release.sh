#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Commit tracked changes before building a versioned release." >&2
  exit 1
fi

VERSION="$(git rev-parse --short HEAD)"
ARTIFACT_DIR="$PROJECT_ROOT/artifacts"
STAGING_DIR="$ARTIFACT_DIR/.staging/13f-data-runtime-$VERSION"
ARCHIVE="$ARTIFACT_DIR/13f-data-runtime-$VERSION.tar.gz"

rm -rf "$ARTIFACT_DIR/.staging"
mkdir -p "$STAGING_DIR/app/frontend" "$STAGING_DIR/deploy"

npm --prefix app/frontend ci
npm --prefix app/frontend run build

cp -a app/backend "$STAGING_DIR/app/backend"
cp -a app/frontend/dist "$STAGING_DIR/app/frontend/dist"
cp -a deploy/13f-data.env.example "$STAGING_DIR/deploy/"
cp -a deploy/13f-data.service "$STAGING_DIR/deploy/"
cp -a deploy/nginx-13f-data.conf "$STAGING_DIR/deploy/"
cp -a deploy/install.sh "$STAGING_DIR/deploy/"
cp -a deploy/activate.sh "$STAGING_DIR/deploy/"
cp -a deploy/DEPLOYMENT.md "$STAGING_DIR/"
printf '%s\n' "$VERSION" > "$STAGING_DIR/VERSION"

find "$STAGING_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGING_DIR" -type f -name '*.pyc' -delete
chmod 0755 "$STAGING_DIR/deploy/install.sh" "$STAGING_DIR/deploy/activate.sh"

tar -C "$ARTIFACT_DIR/.staging" -czf "$ARCHIVE" \
  "13f-data-runtime-$VERSION"
(
  cd "$ARTIFACT_DIR"
  shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)

echo "$ARCHIVE"
echo "$ARCHIVE.sha256"
