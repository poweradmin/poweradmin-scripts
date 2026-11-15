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
out_tmp=$(mktemp)
trap 'rm -f "$temp_file" "$out_tmp"' EXIT

echo "Downloading TLD list from IANA..."
curl -fsSL https://data.iana.org/TLD/tlds-alpha-by-domain.txt -o "$temp_file"

if [[ "$(head -n 1 "$temp_file")" != "# Version "* ]]; then
    echo "Error: downloaded file lacks the IANA '# Version' header; keeping current $OUTPUT_FILE" >&2
    exit 1
fi

# Count TLDs (excluding header line)
tld_count=$(tail -n +2 "$temp_file" | wc -l | tr -d ' ')

if [[ -f "$OUTPUT_FILE" ]]; then
    old_count=$(sed -n 's/.* - \([0-9][0-9]*\) TLDs$/\1/p' "$OUTPUT_FILE" | head -n 1)
    # Refuse a truncated download (floor: 90% of current count)
    if [[ -n "$old_count" ]] && (( tld_count * 100 < old_count * 90 )); then
        echo "Error: downloaded list has $tld_count TLDs, current has $old_count; keeping current $OUTPUT_FILE" >&2
        exit 1
    fi
fi
current_date=$(date +%Y-%m-%d)

echo "Generating $OUTPUT_FILE with $tld_count TLDs..."

# Generate PHP file header
cat > "$out_tmp" << HEADER
<?php

/**
 * Top Level Domains list from IANA
 *
 * Updated on $current_date - $tld_count TLDs
 * Source: https://data.iana.org/TLD/tlds-alpha-by-domain.txt
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
    sed -e 's/^/        /g' >> "$out_tmp"

# Add closing bracket and special TLDs
cat >> "$out_tmp" << 'FOOTER'

    ],
    // IETF/ICANN reserved special-use TLDs (not delegated by IANA)
    'special' => [
        // RFC 2606 - testing and documentation
        'test',
        'example',
        'invalid',
        'localhost',
        // RFC 6762 - multicast DNS
        'local',
        // RFC 7686 - Tor hidden services
        'onion',
        // RFC 9476 - alternative DNS namespaces
        'alt',
        // ICANN reserved 2024 - private-use applications
        'internal',
    ],
];
FOOTER

mv "$out_tmp" "$OUTPUT_FILE"
chmod 644 "$OUTPUT_FILE"

echo "Successfully updated $OUTPUT_FILE"
