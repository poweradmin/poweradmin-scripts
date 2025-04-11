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

# Check required commands
for cmd in msgmerge msgen msgcat msgattrib msguniq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: '$cmd' command not found"
        exit 1
    fi
done

# Check script is run from project root
check_run_from_project_root

# Get the absolute path to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LOCALE_DIR="$PROJECT_ROOT/locale"
TEMPLATE="i18n-template-php.pot"

# Function to clean up obsolete translations (removes them)
cleanup_obsolete_translations() {
    local po_file=$1
    
    echo "  - Cleaning up obsolete translations in $po_file"
    
    # Count obsolete translations
    local obsolete_count=$(grep -c "#~ msgid" "$po_file" || echo 0)
    echo "    Found $obsolete_count obsolete translations"
    
    if [ "$obsolete_count" -gt 0 2>/dev/null ]; then
        # Remove all obsolete entries
        msgattrib --no-obsolete "$po_file" -o "$po_file.clean"
        
        # Replace original with cleaned file
        mv "$po_file.clean" "$po_file"
        
        # Verify results
        local new_count=$(grep -c "^msgid" "$po_file" || echo 0)
        echo "    Cleaned file now has $new_count total entries"
    fi
}

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

# Much simpler approach - regenerate template with extract_strings.sh first
echo "Regenerating template file with extract_strings.sh..."
if [ -x "$SCRIPT_DIR/extract_strings.sh" ]; then
    (cd "$PROJECT_ROOT" && ./scripts/extract_strings.sh)
    # Additional deduplication with msguniq
    echo "Deduplicating template file with msguniq..."
    TEMP_POT=$(mktemp)
    msguniq --force-po "$LOCALE_DIR/$TEMPLATE" > "$TEMP_POT" 2>/dev/null || echo "Warning: msguniq failed"
    cp "$TEMP_POT" "$LOCALE_DIR/$TEMPLATE"
    rm -f "$TEMP_POT"
    
    # Fix any syntax issues that might prevent merging
    echo "Fixing any potential syntax issues in template file..."
    msgfmt --check "$LOCALE_DIR/$TEMPLATE" -o /dev/null 2>/dev/null || {
        echo "Template has syntax issues. Creating simplified version..."
        
        TEMP_DIR=$(mktemp -d)
        HEADER_FILE="$TEMP_DIR/header.pot"
        ENTRIES_FILE="$TEMP_DIR/entries.pot"
        
        # Extract header
        sed -n '1,/^$/p' "$LOCALE_DIR/$TEMPLATE" > "$HEADER_FILE"
        
        # Create a simplified template with just valid entries
        echo "" > "$ENTRIES_FILE"
        grep -a "^msgid" "$LOCALE_DIR/$TEMPLATE" | grep -v 'msgid ""' | sort -u | while read -r msgid_line; do
            echo "$msgid_line" >> "$ENTRIES_FILE" 
            echo 'msgstr ""' >> "$ENTRIES_FILE"
            echo "" >> "$ENTRIES_FILE"
        done
        
        # Combine header and entries
        cat "$HEADER_FILE" "$ENTRIES_FILE" > "$LOCALE_DIR/$TEMPLATE"
        
        # Clean up
        rm -rf "$TEMP_DIR"
    }
else
    echo "Warning: extract_strings.sh not found or not executable"
fi

# Clean up obsolete translations by default with no command line options

# Get list of available locales, excluding template
dirs=$(ls "$LOCALE_DIR" | grep -v pot)

# First process the English locale to ensure it has matching msgid/msgstr values
ENGLISH_LOCALE="en_EN"
echo "Updating $ENGLISH_LOCALE locale (ensuring matching translations)"

ENGLISH_MESSAGES_DIR="$LOCALE_DIR/$ENGLISH_LOCALE/LC_MESSAGES"
if [ ! -d "$ENGLISH_MESSAGES_DIR" ]; then
    echo "Error: English locale directory $ENGLISH_MESSAGES_DIR not found"
    exit 1
fi

# Create backup before merging
cp "$ENGLISH_MESSAGES_DIR/messages.po" "$ENGLISH_MESSAGES_DIR/messages.po.bak"

# Use a simpler approach to ensure English has matching translations
# Create a fresh English translation file from the template
msginit --no-translator --locale=en_EN --input="$LOCALE_DIR/$TEMPLATE" --output="$ENGLISH_MESSAGES_DIR/messages.po.new"

# Now make sure all msgstr entries match their msgid
msgfilter --keep-header -i "$ENGLISH_MESSAGES_DIR/messages.po.new" -o "$ENGLISH_MESSAGES_DIR/messages.po" cat

# Run msgfmt --check to ensure the file is valid
if ! msgfmt --check "$ENGLISH_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
    echo "  - Warning: English file has syntax issues, fixing with msgcat..."
    msgcat --no-wrap "$ENGLISH_MESSAGES_DIR/messages.po" -o "$ENGLISH_MESSAGES_DIR/messages.po.fixed"
    mv "$ENGLISH_MESSAGES_DIR/messages.po.fixed" "$ENGLISH_MESSAGES_DIR/messages.po"
fi

# Clean up obsolete translations
cleanup_obsolete_translations "$ENGLISH_MESSAGES_DIR/messages.po"

# Ensure all msgstr values match msgid values for the English locale
echo "  - Setting all English translations to match their msgid values..."
msgen "$ENGLISH_MESSAGES_DIR/messages.po" -o "$ENGLISH_MESSAGES_DIR/messages.po.en"
mv "$ENGLISH_MESSAGES_DIR/messages.po.en" "$ENGLISH_MESSAGES_DIR/messages.po"

# Show statistics
old_trans=$(grep -c "^msgstr" "$ENGLISH_MESSAGES_DIR/messages.po.bak" || echo 0)
new_trans=$(grep -c "^msgstr" "$ENGLISH_MESSAGES_DIR/messages.po" || echo 0)
comm_trans=$(grep -c "#~ " "$ENGLISH_MESSAGES_DIR/messages.po" || echo 0)

echo "  - Old translations: $old_trans"
echo "  - New translations: $new_trans"
echo "  - Commented translations: $comm_trans"

# Clean up temporary files
rm -f "$ENGLISH_MESSAGES_DIR/messages.po.bak" "$ENGLISH_MESSAGES_DIR/messages.po.new"

# Extract the English translations to use as fallback for other languages
# Create a mapping of msgid to msgstr from the English file
echo "Creating English translation map for fallbacks..."
ENGLISH_TRANS_MAP=$(mktemp)
awk '
    BEGIN { in_msgid = 0; in_msgstr = 0; msgid = ""; msgstr = ""; }
    
    /^msgid "/ {
        if (msgid != "" && msgstr != "") {
            print msgid "\t" msgstr;
        }
        msgid = substr($0, 7);
        in_msgid = 1;
        in_msgstr = 0;
        msgstr = "";
        next;
    }
    
    /^msgstr "/ {
        msgstr = substr($0, 8);
        in_msgid = 0;
        in_msgstr = 1;
        next;
    }
    
    /^"/ {
        if (in_msgid) msgid = msgid "\n" $0;
        if (in_msgstr) msgstr = msgstr "\n" $0;
        next;
    }
    
    /^$/ {
        if (msgid != "" && msgstr != "") {
            print msgid "\t" msgstr;
            msgid = "";
            msgstr = "";
        }
        in_msgid = 0;
        in_msgstr = 0;
    }
    
    END {
        if (msgid != "" && msgstr != "") {
            print msgid "\t" msgstr;
        }
    }
' "$ENGLISH_MESSAGES_DIR/messages.po" > "$ENGLISH_TRANS_MAP"

# Update every other locale using English as fallback
for locale in $dirs; do
    if [ "$locale" != "$ENGLISH_LOCALE" ]; then
        echo "Updating $locale locale"

        LOCALE_MESSAGES_DIR="$LOCALE_DIR/$locale/LC_MESSAGES"
        if [ ! -d "$LOCALE_MESSAGES_DIR" ]; then
            echo "Error: Directory $LOCALE_MESSAGES_DIR not found"
            exit 1
        fi

        # Create backup before merging
        cp "$LOCALE_MESSAGES_DIR/messages.po" "$LOCALE_MESSAGES_DIR/messages.po.bak"
        
        # Merge with template
        msgmerge --backup=none -N -U "$LOCALE_MESSAGES_DIR/messages.po" "$LOCALE_DIR/$TEMPLATE"
        
        # Process to add English translations as fallback for empty msgstr and mark them for easy finding later
        TEMP_PO=$(mktemp)
        python3 -c "
import sys
import re

# Load English translations as fallback
english_trans = {}
with open('$ENGLISH_TRANS_MAP', 'r') as f:
    for line in f:
        if '\t' in line:
            msgid, msgstr = line.split('\t', 1)
            english_trans[msgid.strip()] = msgstr.strip()

# Process current PO file
with open('$LOCALE_MESSAGES_DIR/messages.po', 'r') as f:
    content = f.read()

# Make a backup of the file
with open('$LOCALE_MESSAGES_DIR/messages.po.bak2', 'w') as f:
    f.write(content)

# Split into entries
entries = re.split(r'\n\n+', content)
header = entries[0]
entries = entries[1:]

# Track number of fallbacks added
fallback_count = 0

# Process each entry
with open('$TEMP_PO', 'w') as f:
    f.write(header + '\n\n')
    
    for entry in entries:
        msgid_match = re.search(r'msgid (\".*?\"(\n\".*?\")*)', entry, re.DOTALL)
        msgstr_match = re.search(r'msgstr (\".*?\"(\n\".*?\")*)', entry, re.DOTALL)
        
        if msgid_match and msgstr_match:
            msgid = msgid_match.group(1)
            msgstr = msgstr_match.group(1)
            
            # If msgstr is empty (just \"\") and we have an English translation, use it
            if (msgstr.strip() == '\"\"' or msgstr == '\"\"') and msgid in english_trans:
                # Add a special translator comment to mark this as an auto-filled English fallback
                if not '#, auto-english-fallback' in entry:
                    if '#:' in entry:
                        # Insert after the file reference line
                        entry = re.sub(r'(#:.*(\n#:.*)*)', r'\\1\n#, auto-english-fallback', entry)
                    else:
                        # Insert at the beginning of the entry
                        entry = '#, auto-english-fallback\n' + entry
                
                # Replace the empty msgstr with the English translation
                entry = entry.replace('msgstr \"\"', 'msgstr ' + english_trans[msgid])
                fallback_count += 1
        
        f.write(entry + '\n\n')

# Output statistics
print(f'  - Added {fallback_count} English fallbacks with auto-english-fallback marker')
"
        # If the Python script worked, use the result
        if [ -s "$TEMP_PO" ]; then
            mv "$TEMP_PO" "$LOCALE_MESSAGES_DIR/messages.po"
            
            # Run msgfmt --check to ensure the file is valid
            if ! msgfmt --check "$LOCALE_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                echo "  - Warning: File has syntax issues, fixing with msgcat..."
                msgcat --no-wrap "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po.fixed"
                mv "$LOCALE_MESSAGES_DIR/messages.po.fixed" "$LOCALE_MESSAGES_DIR/messages.po"
                
                # If msgcat didn't fix it, try a more aggressive approach
                if ! msgfmt --check "$LOCALE_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                    echo "  - Warning: Still has syntax issues, creating from scratch..."
                    # Create a new PO file from the template and keep existing translations
                    msginit --no-translator --locale="$locale" --input="$LOCALE_DIR/$TEMPLATE" --output="$LOCALE_MESSAGES_DIR/messages.po.new"
                    # Merge with existing translations
                    msgmerge --no-wrap "$LOCALE_MESSAGES_DIR/messages.po.new" "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po"
                    rm -f "$LOCALE_MESSAGES_DIR/messages.po.new"
                fi
            fi
        else
            echo "  - Warning: Failed to process with Python, falling back to original file"
            rm -f "$TEMP_PO"
            
            # Still try to fix the original file if needed
            if ! msgfmt --check "$LOCALE_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                echo "  - Warning: Original file has syntax issues, fixing with msgcat..."
                msgcat --no-wrap "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po.fixed"
                mv "$LOCALE_MESSAGES_DIR/messages.po.fixed" "$LOCALE_MESSAGES_DIR/messages.po"
                
                # If msgcat didn't fix it, try a more aggressive approach
                if ! msgfmt --check "$LOCALE_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                    echo "  - Warning: Still has syntax issues, creating from scratch..."
                    # Create a new PO file from the template and keep existing translations
                    msginit --no-translator --locale="$locale" --input="$LOCALE_DIR/$TEMPLATE" --output="$LOCALE_MESSAGES_DIR/messages.po.new"
                    # Merge with existing translations
                    msgmerge --no-wrap "$LOCALE_MESSAGES_DIR/messages.po.new" "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po"
                    rm -f "$LOCALE_MESSAGES_DIR/messages.po.new"
                fi
            fi
        fi
        
        # Compare number of translations before and after merge
        old_trans=$(grep -c "^msgstr" "$LOCALE_MESSAGES_DIR/messages.po.bak" || echo 0)
        new_trans=$(grep -c "^msgstr" "$LOCALE_MESSAGES_DIR/messages.po" || echo 0)
        comm_trans=$(grep -c "#~ " "$LOCALE_MESSAGES_DIR/messages.po" || echo 0)
        
        echo "  - Old translations: $old_trans"
        echo "  - New translations: $new_trans"
        echo "  - Commented translations: $comm_trans"
        
        # Clean up obsolete translations
        cleanup_obsolete_translations "$LOCALE_MESSAGES_DIR/messages.po"
        
        # Remove backup
        rm -f "$LOCALE_MESSAGES_DIR/messages.po.bak"
    fi
done

# Clean up temp files
rm -f "$ENGLISH_TRANS_MAP"

# Final instructions 
echo ""
echo "Translation files have been updated. To compile .mo files, run:"
echo "./scripts/compile_messages.sh"
echo ""
echo "All obsolete translations have been removed for cleaner files."
echo ""
echo "Entries that were empty and filled with English translations are marked with '#, auto-english-fallback'."
echo "You can find them using grep: grep -r \"auto-english-fallback\" locale/"
