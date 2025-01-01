#!/bin/bash

set -euo pipefail

LIB_DIR="../lib"

IMPORTANT_STRING="Poweradmin, a friendly web-based admin tool for PowerDNS."

find "$LIB_DIR" -type f -name "*.php" | while read -r file; do
    # Check if the file contains the important string
    if ! grep -qF "$IMPORTANT_STRING" "$file"; then
        echo "File without important string: $file"
    fi
done
