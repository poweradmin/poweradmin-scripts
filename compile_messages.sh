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

LOCALE_DIR="$PROJECT_ROOT/locale"

# Check if locale directory exists
if [ ! -d "$LOCALE_DIR" ]; then
    echo "Error: Locale directory not found: $LOCALE_DIR"
    exit 1
fi

# Get list of available locales, excluding template
dirs=$(find "$LOCALE_DIR" -mindepth 1 -maxdepth 1 -type d | grep -v pot | xargs -n1 basename)

# Compile .mo files for all locales
for locale in $dirs; do
    echo "Compiling $locale locale"
    
    LOCALE_MESSAGES_DIR="$LOCALE_DIR/$locale/LC_MESSAGES"
    PO_FILE="$LOCALE_MESSAGES_DIR/messages.po"
    MO_FILE="$LOCALE_MESSAGES_DIR/messages.mo"
    
    if [ ! -f "$PO_FILE" ]; then
        echo "  Warning: PO file not found: $PO_FILE"
        continue
    fi
    
    # Compile messages
    msgfmt -o "$MO_FILE" "$PO_FILE"
    echo "  Successfully compiled to $MO_FILE"
done

echo "All message files have been compiled successfully."