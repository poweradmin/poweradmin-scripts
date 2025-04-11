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

# Get the absolute path to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "Error: Failed to change to project root directory: $PROJECT_ROOT"; exit 1; }

temp_file=$(mktemp)
trap 'rm -f "$temp_file"' EXIT

curl -sSL http://data.iana.org/TLD/tlds-alpha-by-domain.txt > "$temp_file"

echo 'const TOP_LEVEL_DOMAINS = array('
tail -n +2 "$temp_file" | tr '[:upper:]' '[:lower:]' | awk '{printf "\"%s\", ", $0}' | fold -s -w 79 | sed -e 's/^/  /g'
echo ""
echo ');'
