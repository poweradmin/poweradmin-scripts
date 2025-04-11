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
LIB_DIR="$PROJECT_ROOT/lib"

IMPORTANT_STRING="Poweradmin, a friendly web-based admin tool for PowerDNS."

find "$LIB_DIR" -type f -name "*.php" | while read -r file; do
    # Check if the file contains the important string
    if ! grep -qF "$IMPORTANT_STRING" "$file"; then
        echo "File without important string: $file"
    fi
done
