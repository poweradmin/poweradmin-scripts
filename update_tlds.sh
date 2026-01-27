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

OUTPUT_FILE="data/tlds.php"
temp_file=$(mktemp)
trap 'rm -f "$temp_file"' EXIT

echo "Downloading TLD list from IANA..."
curl -sSL http://data.iana.org/TLD/tlds-alpha-by-domain.txt > "$temp_file"

# Count TLDs (excluding header line)
tld_count=$(tail -n +2 "$temp_file" | wc -l | tr -d ' ')
current_date=$(date +%Y-%m-%d)

echo "Generating $OUTPUT_FILE with $tld_count TLDs..."

# Generate PHP file header
cat > "$OUTPUT_FILE" << HEADER
<?php

/**
 * Top Level Domains list from IANA
 *
 * Updated on $current_date - $tld_count TLDs
 * Source: http://data.iana.org/TLD/tlds-alpha-by-domain.txt
 *
 * Do not edit manually - use scripts/update_tlds.sh to regenerate
 */

return [
    'tlds' => [
HEADER

# Convert TLDs to PHP array format (lowercase, quoted, wrapped at ~75 chars)
tail -n +2 "$temp_file" | tr '[:upper:]' '[:lower:]' | \
    awk '{printf "'\''%s'\'', ", $0}' | \
    fold -s -w 75 | \
    sed -e 's/^/        /g' >> "$OUTPUT_FILE"

# Add closing bracket and special TLDs
cat >> "$OUTPUT_FILE" << 'FOOTER'

    ],
    // RFC 2606 special TLDs for testing and documentation
    // http://tools.ietf.org/html/rfc2606#section-2
    'special' => [
        'test',
        'example',
        'invalid',
        'localhost',
    ],
];
FOOTER

echo "Successfully updated $OUTPUT_FILE"
