#!/bin/bash

# Translation Cleanup Script
#
# This script removes obsolete translations from locale files by comparing them
# against the current template (POT file). It identifies translations that are
# no longer referenced in the codebase and provides options to remove them.
#
# Usage:
#   ./scripts/cleanup_obsolete_translations.sh [options]
#
# Options:
#   --dry-run         Show what would be removed without making changes
#   --locale=LOCALE   Process only specific locale (e.g., --locale=fr_FR)
#   --backup          Create backups before making changes (default: true)
#   --no-backup       Don't create backups
#   --stats-only      Only show statistics about obsolete translations
#   --force-check     Run msgmerge first to mark obsolete entries, then clean them
#   --help, -h        Show help message
#
# Examples:
#   ./scripts/cleanup_obsolete_translations.sh --dry-run
#   ./scripts/cleanup_obsolete_translations.sh --locale=fr_FR
#   ./scripts/cleanup_obsolete_translations.sh --stats-only

set -u

# Default options
DRY_RUN=false
CREATE_BACKUP=true
STATS_ONLY=false
SPECIFIC_LOCALE=""
FORCE_CHECK=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCALE_DIR="$PROJECT_ROOT/locale"
TEMPLATE_FILE="$LOCALE_DIR/i18n-template-php.pot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to show help
show_help() {
    cat << EOF
Translation Cleanup Script

This script removes obsolete translations from locale files by comparing them
against the current template (POT file).

Usage:
  ./scripts/cleanup_obsolete_translations.sh [options]

Options:
  --dry-run         Show what would be removed without making changes
  --locale=LOCALE   Process only specific locale (e.g., --locale=fr_FR)
  --backup          Create backups before making changes (default: true)
  --no-backup       Don't create backups
  --stats-only      Only show statistics about obsolete translations
  --force-check     Run msgmerge first to mark obsolete entries, then clean them
  --help, -h        Show this help message

Examples:
  # Show what would be cleaned without making changes
  ./scripts/cleanup_obsolete_translations.sh --dry-run

  # Clean only French translations
  ./scripts/cleanup_obsolete_translations.sh --locale=fr_FR

  # Show statistics only
  ./scripts/cleanup_obsolete_translations.sh --stats-only

Prerequisites:
  - Run ./scripts/extract_strings.sh first to generate the template
  - gettext tools (msgcomm, msgattrib, msgfmt) should be installed

EOF
}

# Function to check if script is run from project root
check_run_from_project_root() {
    local script_name=$(basename "$0")
    if [[ "$0" != "./scripts/$script_name" && "$0" != "scripts/$script_name" ]]; then
        echo -e "${RED}Error: This script should be run from the project root as:${NC}"
        echo "  ./scripts/$script_name"
        echo ""
        echo "Current run path: $0"
        exit 1
    fi
}

# Function to output colored messages
output() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

error() {
    output "$RED" "Error: $1" >&2
}

success() {
    output "$GREEN" "$1"
}

warning() {
    output "$YELLOW" "Warning: $1"
}

info() {
    output "$BLUE" "$1"
}

# Function to check if required tools are available
check_dependencies() {
    local missing_tools=()
    
    for tool in msgcomm msgattrib msgfmt; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        error "Required gettext tools not found: ${missing_tools[*]}"
        error "Please install gettext tools (e.g., apt-get install gettext or brew install gettext)"
        return 1
    fi
    
    return 0
}

# Function to validate environment
validate_environment() {
    if [ ! -d "$LOCALE_DIR" ]; then
        error "Locale directory not found: $LOCALE_DIR"
        return 1
    fi
    
    if [ ! -f "$TEMPLATE_FILE" ]; then
        error "Template file not found: $TEMPLATE_FILE"
        error "Please run ./scripts/extract_strings.sh first to generate the template."
        return 1
    fi
    
    if ! check_dependencies; then
        return 1
    fi
    
    return 0
}

# Function to get list of locales to process
get_locales() {
    local locales=()
    
    if [ -n "$SPECIFIC_LOCALE" ]; then
        local locale_dir="$LOCALE_DIR/$SPECIFIC_LOCALE"
        if [ ! -d "$locale_dir" ]; then
            error "Locale directory not found: $locale_dir"
            return 1
        fi
        
        local po_file="$locale_dir/LC_MESSAGES/messages.po"
        if [ ! -f "$po_file" ]; then
            error "PO file not found: $po_file"
            return 1
        fi
        
        echo "$SPECIFIC_LOCALE"
        return 0
    fi
    
    # Find all available locales
    for dir in "$LOCALE_DIR"/*; do
        if [ -d "$dir" ] && [ "$(basename "$dir")" != "." ] && [ "$(basename "$dir")" != ".." ]; then
            local locale=$(basename "$dir")
            local po_file="$dir/LC_MESSAGES/messages.po"
            
            if [ -f "$po_file" ]; then
                locales+=("$locale")
            fi
        fi
    done
    
    if [ ${#locales[@]} -eq 0 ]; then
        error "No locale files found"
        return 1
    fi
    
    printf '%s\n' "${locales[@]}"
    return 0
}

# Function to extract msgids from template file
extract_template_msgids() {
    local temp_file=$(mktemp)
    
    # Extract all msgids from the template, excluding empty ones
    msgattrib --no-obsolete --no-fuzzy "$TEMPLATE_FILE" | \
    grep -E '^msgid ' | \
    sed 's/^msgid "//' | \
    sed 's/"$//' | \
    grep -v '^$' > "$temp_file"
    
    echo "$temp_file"
}

# Function to find obsolete translations in a PO file
find_obsolete_translations() {
    local po_file=$1
    local template_msgids_file=$2
    local temp_dir=$(mktemp -d)
    local po_msgids_file="$temp_dir/po_msgids.txt"
    local obsolete_file="$temp_dir/obsolete.txt"
    local obsolete_marked_file="$temp_dir/obsolete_marked.txt"
    
    # First, check for entries already marked as obsolete with #~
    grep "^#~ msgid" "$po_file" | sed 's/^#~ msgid "//' | sed 's/"$//' > "$obsolete_marked_file"
    
    # Also extract msgids from PO file (non-obsolete entries)
    msgattrib --no-obsolete --no-fuzzy "$po_file" | \
    grep -E '^msgid ' | \
    sed 's/^msgid "//' | \
    sed 's/"$//' | \
    grep -v '^$' > "$po_msgids_file"
    
    # Find msgids that are in PO file but not in template
    comm -23 <(sort "$po_msgids_file") <(sort "$template_msgids_file") > "$obsolete_file"
    
    # Combine both types of obsolete entries
    cat "$obsolete_marked_file" "$obsolete_file" | sort -u > "${obsolete_file}.combined"
    
    # Clean up
    rm -rf "$temp_dir"
    
    if [ -s "${obsolete_file}.combined" ]; then
        echo "${obsolete_file}.combined"
    else
        rm -f "${obsolete_file}.combined"
        echo ""
    fi
}

# Function to show statistics for a locale
show_locale_stats() {
    local locale=$1
    local po_file="$LOCALE_DIR/$locale/LC_MESSAGES/messages.po"
    local template_msgids_file=$2
    
    local obsolete_file=$(find_obsolete_translations "$po_file" "$template_msgids_file")
    local obsolete_count=0
    
    if [ -n "$obsolete_file" ]; then
        obsolete_count=$(wc -l < "$obsolete_file")
        rm -f "$obsolete_file"
    fi
    
    printf "%-12s: %d obsolete translation(s)\n" "$locale" "$obsolete_count"
    return $obsolete_count
}

# Function to show statistics for all locales
show_statistics() {
    info "Translation Statistics:"
    echo "$(printf '%.50s' "$(printf '%*s' 50 '' | tr ' ' '-')")"
    
    local template_msgids_file=$(extract_template_msgids)
    local total_obsolete=0
    
    while IFS= read -r locale; do
        show_locale_stats "$locale" "$template_msgids_file"
        total_obsolete=$((total_obsolete + $?))
    done < <(get_locales)
    
    echo "$(printf '%.50s' "$(printf '%*s' 50 '' | tr ' ' '-')")"
    echo "Total: $total_obsolete obsolete translations"
    
    rm -f "$template_msgids_file"
}

# Function to remove obsolete entries from PO file
remove_obsolete_entries() {
    local po_file=$1
    local obsolete_msgids_file=$2
    local locale=$3
    
    if [ "$CREATE_BACKUP" = true ]; then
        local backup_file="${po_file}.backup.$(date '+%Y%m%d_%H%M%S')"
        if ! cp "$po_file" "$backup_file"; then
            error "Failed to create backup: $backup_file"
            return 1
        fi
        info "  Created backup: $(basename "$backup_file")"
    fi
    
    local temp_file=$(mktemp)
    local removed_count=0
    
    # Use a more comprehensive approach to remove obsolete entries
    # This handles both #~ marked entries and entries that don't exist in template
    
    # First, remove all #~ marked obsolete entries
    grep -v "^#~" "$po_file" > "${temp_file}.no_obsolete"
    
    # Count how many #~ entries we removed
    local marked_obsolete_count=$(($(grep -c "^#~" "$po_file" || echo 0)))
    
    # Now process remaining entries to remove those not in template
    {
        # Copy header first
        sed -n '1,/^$/p' "${temp_file}.no_obsolete"
        
        # Process each message block
        awk '
        BEGIN { in_entry = 0; entry = ""; msgid = ""; }
        
        /^$/ {
            if (in_entry && entry != "") {
                if (msgid != "" && msgid != "\"\"") {
                    # Check if this msgid is in our obsolete list
                    cmd = "grep -Fxq \"" msgid "\" " obsolete_file
                    if (system(cmd) != 0) {
                        # Not in obsolete list, keep it
                        print entry
                        print ""
                    }
                } else {
                    # Keep empty msgid (header)
                    print entry
                    print ""
                }
            }
            in_entry = 0
            entry = ""
            msgid = ""
            next
        }
        
        /^msgid / {
            in_entry = 1
            msgid = substr($0, 7)
            gsub(/^"|"$/, "", msgid)
            entry = entry $0 "\n"
            next
        }
        
        {
            if (in_entry) {
                entry = entry $0 "\n"
            } else {
                print
            }
        }
        
        END {
            if (in_entry && entry != "") {
                if (msgid != "" && msgid != "\"\"") {
                    cmd = "grep -Fxq \"" msgid "\" " obsolete_file
                    if (system(cmd) != 0) {
                        print entry
                    }
                } else {
                    print entry
                }
            }
        }
        ' obsolete_file="$obsolete_msgids_file" "${temp_file}.no_obsolete"
        
    } > "$temp_file"
    
    # Count removed entries
    local original_entries=$(($(grep -c "^msgid" "$po_file" || echo 0)))
    local new_entries=$(($(grep -c "^msgid" "$temp_file" || echo 0)))
    removed_count=$((original_entries - new_entries))
    
    # Replace the original file
    if ! mv "$temp_file" "$po_file"; then
        error "Failed to update PO file: $po_file"
        rm -f "$temp_file" "${temp_file}.no_obsolete"
        return 1
    fi
    
    rm -f "${temp_file}.no_obsolete"
    
    if [ $removed_count -gt 0 ] || [ $marked_obsolete_count -gt 0 ]; then
        success "  Removed $removed_count template-obsolete + $marked_obsolete_count marked-obsolete translation(s)"
    else
        success "  No obsolete translations found"
    fi
    
    # Recompile MO file
    local mo_file="$(dirname "$po_file")/messages.mo"
    if msgfmt -o "$mo_file" "$po_file" 2>/dev/null; then
        info "  Recompiled MO file"
    else
        warning "  Failed to recompile MO file"
    fi
    
    return $((removed_count + marked_obsolete_count))
}

# Function to run msgmerge to mark obsolete entries
force_mark_obsolete() {
    local po_file=$1
    local locale=$2
    
    info "  Running msgmerge to mark obsolete entries..."
    
    local temp_file=$(mktemp)
    if msgmerge --backup=none --update "$po_file" "$TEMPLATE_FILE" 2>/dev/null; then
        info "  msgmerge completed successfully"
    else
        warning "  msgmerge had issues but continued"
    fi
}

# Function to process a single locale
process_locale() {
    local locale=$1
    local template_msgids_file=$2
    local po_file="$LOCALE_DIR/$locale/LC_MESSAGES/messages.po"
    
    info "\nProcessing locale: $locale"
    
    # If force-check is enabled, run msgmerge first to mark obsolete entries
    if [ "$FORCE_CHECK" = true ]; then
        force_mark_obsolete "$po_file" "$locale"
    fi
    
    local obsolete_file=$(find_obsolete_translations "$po_file" "$template_msgids_file")
    
    if [ -z "$obsolete_file" ]; then
        success "  No obsolete translations found."
        return 0
    fi
    
    local obsolete_count=$(wc -l < "$obsolete_file")
    warning "  Found $obsolete_count obsolete translation(s)."
    
    if [ "$DRY_RUN" = true ]; then
        info "  Obsolete translations (dry run):"
        while IFS= read -r msgid; do
            local preview
            if [ ${#msgid} -gt 60 ]; then
                preview="${msgid:0:60}..."
            else
                preview="$msgid"
            fi
            echo "    - \"$preview\""
        done < "$obsolete_file"
    else
        remove_obsolete_entries "$po_file" "$obsolete_file" "$locale"
        local removed=$?
        echo "$locale:$removed" >> /tmp/cleanup_stats.tmp
    fi
    
    rm -f "$obsolete_file"
}

# Function to show summary
show_summary() {
    if [ ! -f /tmp/cleanup_stats.tmp ]; then
        return
    fi
    
    info "\nSummary:"
    echo "$(printf '%.50s' "$(printf '%*s' 50 '' | tr ' ' '-')")"
    
    local total_cleaned=0
    
    while IFS=: read -r locale cleaned; do
        total_cleaned=$((total_cleaned + cleaned))
        if [ "$cleaned" -gt 0 ]; then
            printf "%-12s: cleaned %d translation(s)\n" "$locale" "$cleaned"
        fi
    done < /tmp/cleanup_stats.tmp
    
    echo "$(printf '%.50s' "$(printf '%*s' 50 '' | tr ' ' '-')")"
    success "Total: $total_cleaned obsolete translations removed"
    
    rm -f /tmp/cleanup_stats.tmp
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --backup)
            CREATE_BACKUP=true
            shift
            ;;
        --no-backup)
            CREATE_BACKUP=false
            shift
            ;;
        --stats-only)
            STATS_ONLY=true
            shift
            ;;
        --force-check)
            FORCE_CHECK=true
            shift
            ;;
        --locale=*)
            SPECIFIC_LOCALE="${1#*=}"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# Main execution
main() {
    check_run_from_project_root
    
    if ! validate_environment; then
        exit 1
    fi
    
    if [ "$STATS_ONLY" = true ]; then
        show_statistics
        exit 0
    fi
    
    local locales
    if ! locales=$(get_locales); then
        exit 1
    fi
    
    local locale_count=$(echo "$locales" | wc -l)
    info "Processing $locale_count locale(s)..."
    
    if [ "$DRY_RUN" = true ]; then
        warning "DRY RUN MODE - No changes will be made"
    fi
    
    local template_msgids_file=$(extract_template_msgids)
    
    # Initialize stats file
    rm -f /tmp/cleanup_stats.tmp
    
    while IFS= read -r locale; do
        process_locale "$locale" "$template_msgids_file"
    done <<< "$locales"
    
    rm -f "$template_msgids_file"
    
    if [ "$DRY_RUN" = true ]; then
        info "\nRun without --dry-run to remove obsolete translations."
    else
        show_summary
    fi
}

# Run the main function
main "$@"