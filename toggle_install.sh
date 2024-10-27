#!/bin/bash

INSTALL_DIR="../install"
BACKUP_DIR="../install.old"

if [ -d "$INSTALL_DIR" ]; then
    echo "Found 'install' directory in the parent folder. Renaming to 'install.old'"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
elif [ -d "$BACKUP_DIR" ]; then
    echo "Found 'install.old' directory in the parent folder. Renaming back to 'install'"
    mv "$BACKUP_DIR" "$INSTALL_DIR"
else
    echo "Neither 'install' nor 'install.old' directory found in the parent folder"
fi
