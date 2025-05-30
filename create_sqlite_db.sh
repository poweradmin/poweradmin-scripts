#!/bin/bash

set -euo pipefail

# Check if the script is being run from the project root
check_run_from_project_root() {
    local script_name=$(basename "$0")
    if [[ "$0" != "./scripts/$script_name" && "$0" != "scripts/$script_name" ]]; then
        echo "Error: This script should be run from the project root as:"
        echo "  ./scripts/$script_name"
        echo ""
        echo "Current run path: $0"
        exit 1
    fi
}

# Check script is run from project root
check_run_from_project_root

DB_PATH="../../db"
DB_FILE="powerdns.db"
SQLITE_BIN=sqlite3
SCHEMA_FILE="../sql/pdns/47/schema.sqlite3.sql"

# Check if schema file exists
if ! command -v $SQLITE_BIN &> /dev/null; then
    echo "Error: sqlite3 is not installed"
    exit 1
fi

# Check if schema file exists
if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Error: Schema file not found: $SCHEMA_FILE"
    exit 1
fi

# Check if directory exists
if [ ! -d "$DB_PATH" ]; then
    mkdir -p "$DB_PATH"
fi

# Check if db file exists
if [ -e "$DB_PATH/$DB_FILE" ]; then
    echo "Error: database file <$DB_PATH/$DB_FILE> already exists!"
    exit 1
fi

# Import db schema and data
"$SQLITE_BIN" "$DB_PATH/$DB_FILE" < "$SCHEMA_FILE"

# Change access rights
chmod 777 $DB_PATH
chmod 666 $DB_PATH/$DB_FILE
