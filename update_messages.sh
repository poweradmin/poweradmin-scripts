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

# Check if both scripts exist
EXTRACT_SCRIPT="$SCRIPT_DIR/extract_strings.sh"
MERGE_SCRIPT="$SCRIPT_DIR/merge_messages.sh"
COMPILE_SCRIPT="$SCRIPT_DIR/compile_messages.sh"

for script in "$EXTRACT_SCRIPT" "$MERGE_SCRIPT" "$COMPILE_SCRIPT"; do
    if [ ! -f "$script" ]; then
        echo "Error: Required script not found: $script"
        exit 1
    fi
done

# Execute scripts
echo "Extracting strings..."
"$EXTRACT_SCRIPT"

echo "Merging messages..."
"$MERGE_SCRIPT"

echo "Compiling messages..."
"$COMPILE_SCRIPT"

echo "Update completed successfully."