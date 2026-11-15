#!/bin/bash
#
# Create a fresh SQLite database holding both the PowerDNS schema and the
# Poweradmin tables, ready for the installer.
#
# Usage: ./scripts/create_sqlite_db.sh <db-file> [pdns-schema-version]
#
#   <db-file>              path of the database to create; must not exist yet
#   [pdns-schema-version]  directory under sql/pdns/ (default: the newest one)

set -euo pipefail

usage() {
    sed -n '6,9p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-1}"
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage 0
[[ $# -ge 1 && $# -le 2 ]] || usage

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_FILE="$1"
# Resolve against the caller's cwd before anything changes directory
[[ "$DB_FILE" == /* ]] || DB_FILE="$PWD/$DB_FILE"

if [[ $# -eq 2 ]]; then
    PDNS_VERSION="$2"
else
    PDNS_VERSION="$(find "$PROJECT_ROOT/sql/pdns" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort -n | tail -1)"
fi

PDNS_SCHEMA="$PROJECT_ROOT/sql/pdns/$PDNS_VERSION/schema.sqlite3.sql"
POWERADMIN_SCHEMA="$PROJECT_ROOT/sql/poweradmin-sqlite-db-structure.sql"

if ! command -v sqlite3 > /dev/null; then
    echo "Error: sqlite3 is not installed" >&2
    exit 1
fi

for schema in "$PDNS_SCHEMA" "$POWERADMIN_SCHEMA"; do
    if [[ ! -f "$schema" ]]; then
        echo "Error: schema file not found: $schema" >&2
        exit 1
    fi
done

if [[ -e "$DB_FILE" ]]; then
    echo "Error: database file already exists: $DB_FILE" >&2
    exit 1
fi

mkdir -p "$(dirname "$DB_FILE")"

# Build in a temp file so a failed import never leaves a half-created database behind
TMP_DB="$(mktemp "$(dirname "$DB_FILE")/.create_sqlite_db.XXXXXX")"
trap 'rm -f "$TMP_DB"' EXIT

sqlite3 -bail "$TMP_DB" < "$PDNS_SCHEMA"
sqlite3 -bail "$TMP_DB" < "$POWERADMIN_SCHEMA"

chmod 664 "$TMP_DB"
mv "$TMP_DB" "$DB_FILE"
trap - EXIT

echo "Created $DB_FILE (PowerDNS schema $PDNS_VERSION + Poweradmin tables)"
echo "The web server user needs write access to the file and its directory."
