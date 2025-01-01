#!/bin/bash

set -euo pipefail

# Check required commands
for cmd in msgmerge msgen msgcat; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: '$cmd' command not found"
        exit 1
    fi
done

LOCALE_DIR="../locale"
TEMPLATE="i18n-template-php.pot"

# Check if locale directory exists
if [ ! -d "$LOCALE_DIR" ]; then
    echo "Error: Locale directory not found: $LOCALE_DIR"
    exit 1
fi

# Check if template file exists
if [ ! -f "$LOCALE_DIR/$TEMPLATE" ]; then
    echo "Error: Template file not found: $LOCALE_DIR/$TEMPLATE"
    exit 1
fi

# Get list of available locales, excluding template
dirs=$(ls "$LOCALE_DIR" | grep -v pot)

# Update every messages.mo for every locale
for locale in $dirs; do
    echo "Updating $locale locale"

    cd "$LOCALE_DIR/$locale/LC_MESSAGES" || {
        echo "Error: Failed to change directory to $LOCALE_DIR/$locale/LC_MESSAGES"
        exit 1
    }

    msgmerge --backup=none -N -U messages.po "../../$TEMPLATE"

    msgen "../../$TEMPLATE" > default.po
    msgcat --use-first messages.po default.po -o messages.po

    # Clean up temporary file
    rm -f default.po

    cd "../../" || exit 1
done
