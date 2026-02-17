#!/bin/bash

# Script: check_translation_stats.sh
# Description: Display translation statistics for all locales using msgfmt
# Usage: ./scripts/check_translation_stats.sh [--module=ModuleName]
# Example: ./scripts/check_translation_stats.sh --module=ZoneImportExport

# Parse arguments
MODULE_NAME=""
VERBOSE=false
for arg in "$@"; do
    case "$arg" in
        --module=*)
            MODULE_NAME="${arg#*=}"
            ;;
        --verbose|-v)
            VERBOSE=true
            ;;
    esac
done

if [ -n "$MODULE_NAME" ]; then
    LOCALE_PATTERN="lib/Module/$MODULE_NAME/locale/*"
    PO_SUFFIX="messages.po"
    echo "=== Translation Statistics for Module: $MODULE_NAME ==="
else
    LOCALE_PATTERN="locale/*/LC_MESSAGES"
    PO_SUFFIX="messages.po"
    echo "=== Translation Statistics for All Locales ==="
fi
echo "Generated on: $(date)"
echo ""

# Check if msgfmt is available
if ! command -v msgfmt &> /dev/null; then
    echo "Error: msgfmt command not found. Please install gettext tools."
    exit 1
fi

# Track totals for summary
total_strings=0
total_locales=0
fully_translated=0

echo "Locale | Translated | Fuzzy | Untranslated | Total | Percentage"
echo "-------|------------|-------|--------------|-------|------------"

# Process each locale
for locale_dir in $LOCALE_PATTERN; do
    if [ -n "$MODULE_NAME" ]; then
        po_file="$locale_dir/$PO_SUFFIX"
        locale_name=$(basename "$locale_dir")
    else
        po_file="$locale_dir/$PO_SUFFIX"
        locale_name=$(basename $(dirname "$locale_dir"))
    fi
    if [[ -f "$po_file" ]]; then
        true  # locale_name already set above
        
        # Get statistics from msgfmt
        stats=$(msgfmt --statistics "$po_file" 2>&1)
        
        # Parse the statistics
        translated=$(echo "$stats" | grep -o '[0-9]\+ translated' | grep -o '[0-9]\+' || echo "0")
        fuzzy=$(echo "$stats" | grep -o '[0-9]\+ fuzzy' | grep -o '[0-9]\+' || echo "0")
        untranslated=$(echo "$stats" | grep -o '[0-9]\+ untranslated' | grep -o '[0-9]\+' || echo "0")
        
        # Calculate total and percentage
        total=$((translated + fuzzy + untranslated))
        if [ $total -gt 0 ]; then
            percentage=$(awk "BEGIN {printf \"%.1f\", $translated * 100 / $total}")
        else
            percentage="0.0"
        fi
        
        # Track totals
        total_locales=$((total_locales + 1))
        if [ $total_strings -eq 0 ]; then
            total_strings=$total
        fi
        
        # Check if fully translated (95% or more)
        if (( $(echo "$percentage >= 95" | bc -l 2>/dev/null || echo 0) )); then
            fully_translated=$((fully_translated + 1))
            status="✓"
        else
            status=" "
        fi
        
        # Display results
        printf "%-7s| %-10s | %-5s | %-12s | %-5s | %6s%% %s\n" \
            "$locale_name" "$translated" "$fuzzy" "$untranslated" "$total" "$percentage" "$status"
    fi
done

echo ""
echo "=== Summary ==="
echo "Total locales: $total_locales"
echo "Total strings: $total_strings"
echo "Fully translated (≥95%): $fully_translated"
echo ""

# Optional: Show detailed msgfmt output
if [ "$VERBOSE" = true ]; then
    echo "=== Detailed msgfmt Output ==="
    for locale_dir in $LOCALE_PATTERN; do
        if [ -n "$MODULE_NAME" ]; then
            po_file="$locale_dir/$PO_SUFFIX"
            locale_name=$(basename "$locale_dir")
        else
            po_file="$locale_dir/$PO_SUFFIX"
            locale_name=$(basename $(dirname "$locale_dir"))
        fi
        if [[ -f "$po_file" ]]; then
            echo ""
            echo "[$locale_name]"
            msgfmt --statistics "$po_file" 2>&1
        fi
    done
fi

echo ""
echo "Tip: Use '$0 --verbose' to see detailed msgfmt output for each locale"
if [ -z "$MODULE_NAME" ]; then
    echo "Tip: Use '$0 --module=ModuleName' to check module translations"
fi