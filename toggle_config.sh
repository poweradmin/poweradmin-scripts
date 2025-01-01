#!/bin/bash

CONFIG_FILE="inc/config.inc.php"
BACKUP_CONFIG_FILE="inc/config.old.php"

if [ -f "$CONFIG_FILE" ]; then
    echo "Found configuration file. Creating backup"
    mv "$CONFIG_FILE" "$BACKUP_CONFIG_FILE"
elif [ -f "$BACKUP_CONFIG_FILE" ]; then
    echo "Found backup file. Restoring configuration"
    mv "$BACKUP_CONFIG_FILE" "$CONFIG_FILE"
else
    echo "Neither configuration file nor backup file found. Exiting"
fi
