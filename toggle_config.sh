#!/bin/bash

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

CONFIG_FILE="config/settings.php"
BACKUP_CONFIG_FILE="config/settings.old.php"

if [ -f "$CONFIG_FILE" ]; then
    echo "Found configuration file. Creating backup"
    mv "$CONFIG_FILE" "$BACKUP_CONFIG_FILE"
elif [ -f "$BACKUP_CONFIG_FILE" ]; then
    echo "Found backup file. Restoring configuration"
    mv "$BACKUP_CONFIG_FILE" "$CONFIG_FILE"
else
    echo "Neither configuration file nor backup file found. Exiting"
fi
