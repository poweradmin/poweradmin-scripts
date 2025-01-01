#!/bin/bash

set -euo pipefail

temp_file=$(mktemp)
trap 'rm -f "$temp_file"' EXIT

curl -sSL http://data.iana.org/TLD/tlds-alpha-by-domain.txt > "$temp_file"

echo 'const TOP_LEVEL_DOMAINS = array('
tail -n +2 "$temp_file" | tr '[:upper:]' '[:lower:]' | awk '{printf "\"%s\", ", $0}' | fold -s -w 79 | sed -e 's/^/  /g'
echo ""
echo ');'
