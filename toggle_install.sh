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

INSTALL_DIR="install"
BACKUP_DIR="install.old"

if [ -d "$INSTALL_DIR" ]; then
    echo "Found 'install' directory in the parent folder. Renaming to 'install.old'"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
elif [ -d "$BACKUP_DIR" ]; then
    echo "Found 'install.old' directory in the parent folder. Renaming back to 'install'"
    mv "$BACKUP_DIR" "$INSTALL_DIR"
else
    echo "Neither 'install' nor 'install.old' directory found in the parent folder"
fi
