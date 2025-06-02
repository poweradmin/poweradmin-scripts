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

# Function to clean up only truly obsolete translations (preserves valid ones)
cleanup_obsolete_translations() {
    local po_file=$1
    
    echo "  - Reviewing obsolete translations in $po_file"
    
    # Count obsolete translations
    local obsolete_count=$(grep -c "#~ msgid" "$po_file" || echo 0)
    echo "    Found $obsolete_count obsolete translations"
    
    if [ "$obsolete_count" -gt 0 2>/dev/null ]; then
        # Only remove obsolete entries that are empty or clearly outdated
        # Keep obsolete entries that have actual translations as they might be useful
        python3 -c "
import re
import sys

with open('$po_file', 'r') as f:
    content = f.read()

# Split content into sections
sections = re.split(r'\n\n+', content)
header = sections[0]
entries = sections[1:]

kept_obsolete = 0
removed_obsolete = 0

with open('$po_file.clean', 'w') as f:
    f.write(header + '\n\n')
    
    for entry in entries:
        # Check if this is an obsolete entry
        if '#~' in entry:
            # Check if it has a meaningful translation (not empty)
            msgstr_match = re.search(r'#~ msgstr \"(.+?)\"', entry, re.DOTALL)
            if msgstr_match and msgstr_match.group(1).strip():
                # Keep obsolete entries with actual translations - just comment them better
                entry = re.sub(r'^#~ ', '# OBSOLETE: ', entry, flags=re.MULTILINE)
                f.write(entry + '\n\n')
                kept_obsolete += 1
            else:
                # Remove empty obsolete entries
                removed_obsolete += 1
        else:
            # Keep all non-obsolete entries
            f.write(entry + '\n\n')

print(f'    Kept {kept_obsolete} obsolete entries with translations')
print(f'    Removed {removed_obsolete} empty obsolete entries')
"
        
        # Replace original with cleaned file if Python script succeeded
        if [ -f "$po_file.clean" ]; then
            mv "$po_file.clean" "$po_file"
        else
            echo "    Warning: Failed to clean obsolete translations, keeping original"
        fi
        
        # Verify results
        local new_count=$(grep -c "^msgid" "$po_file" || echo 0)
        echo "    File now has $new_count total entries"
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

# Clean up only truly obsolete translations (preserve those with actual translations)

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

# Preserve existing English translations and only add new ones
echo "  - Preserving existing English translations and adding new entries"

# First, check if the existing file has syntax errors and fix them
if ! msgfmt --check "$ENGLISH_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
    echo "  - Existing file has syntax issues, fixing before merge..."
    
    # Use sed to fix specific broken lines (safer than Python processing)
    cp "$ENGLISH_MESSAGES_DIR/messages.po" "$ENGLISH_MESSAGES_DIR/messages.po.fixing"
    
    # Fix line 7977: add missing closing quote
    sed -i.bak '7977s/^"This system is provided "$/&"/' "$ENGLISH_MESSAGES_DIR/messages.po.fixing"
    
    # Fix line 9454: add missing closing quote  
    sed -i.bak '9454s/^"use "$/&"/' "$ENGLISH_MESSAGES_DIR/messages.po.fixing"
    
    # Remove backup files created by sed
    rm -f "$ENGLISH_MESSAGES_DIR/messages.po.fixing.bak"
    
    # Test if fix worked
    if msgfmt --check "$ENGLISH_MESSAGES_DIR/messages.po.fixing" -o /dev/null 2>/dev/null; then
        mv "$ENGLISH_MESSAGES_DIR/messages.po.fixing" "$ENGLISH_MESSAGES_DIR/messages.po"
        echo "  - Applied targeted syntax fixes"
    else
        echo "  - Targeted fixes failed, keeping original file"
        rm -f "$ENGLISH_MESSAGES_DIR/messages.po.fixing"
    fi
fi

# Now merge with template to add any new strings
msgmerge --no-fuzzy-matching --quiet "$ENGLISH_MESSAGES_DIR/messages.po" "$LOCALE_DIR/$TEMPLATE" -o "$ENGLISH_MESSAGES_DIR/messages.po.merged"

# Process the merged file to ensure English translations are set properly while preserving existing ones
# Use msgen to create English translations only for empty entries, preserving existing ones
echo "  - Using msgen to create English translations for empty entries only..."

# First copy the merged file
cp "$ENGLISH_MESSAGES_DIR/messages.po.merged" "$ENGLISH_MESSAGES_DIR/messages.po.new"

# Use msgen only on a copy to get the pattern, then selectively apply
msgen "$ENGLISH_MESSAGES_DIR/messages.po.merged" -o "$ENGLISH_MESSAGES_DIR/messages.po.msgen"

# Use msgcat to merge, preserving existing non-empty translations
msgcat --use-first "$ENGLISH_MESSAGES_DIR/messages.po.merged" "$ENGLISH_MESSAGES_DIR/messages.po.msgen" -o "$ENGLISH_MESSAGES_DIR/messages.po.new"

# Clean up temporary file
rm -f "$ENGLISH_MESSAGES_DIR/messages.po.msgen"

# Use the processed file
if [ -f "$ENGLISH_MESSAGES_DIR/messages.po.new" ]; then
    mv "$ENGLISH_MESSAGES_DIR/messages.po.new" "$ENGLISH_MESSAGES_DIR/messages.po"
    rm -f "$ENGLISH_MESSAGES_DIR/messages.po.merged"
else
    echo "  - Warning: Failed to process English translations, keeping original"
    mv "$ENGLISH_MESSAGES_DIR/messages.po.merged" "$ENGLISH_MESSAGES_DIR/messages.po"
fi

# Run msgfmt --check to ensure the file is valid
if ! msgfmt --check "$ENGLISH_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
    echo "  - Warning: English file has syntax issues, attempting to fix..."
    
    # Try to fix with msgcat first
    if msgcat --no-wrap "$ENGLISH_MESSAGES_DIR/messages.po" -o "$ENGLISH_MESSAGES_DIR/messages.po.fixed" 2>/dev/null; then
        mv "$ENGLISH_MESSAGES_DIR/messages.po.fixed" "$ENGLISH_MESSAGES_DIR/messages.po"
        echo "  - Fixed with msgcat"
    else
        echo "  - msgcat failed, trying manual fix for end-of-line issues..."
        
        # Manual fix for end-of-line within string errors
        python3 -c "
import re

with open('$ENGLISH_MESSAGES_DIR/messages.po', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Fix end-of-line within string issues
# Look for strings that are missing closing quotes before newlines
content = re.sub(r'\"([^\"]*)\n([^\"]*?)\"', r'\"\1\2\"', content, flags=re.MULTILINE)

# Fix broken multiline strings
lines = content.split('\n')
fixed_lines = []
in_msgid = False
in_msgstr = False

for i, line in enumerate(lines):
    if line.startswith('msgid '):
        in_msgid = True
        in_msgstr = False
        fixed_lines.append(line)
    elif line.startswith('msgstr '):
        in_msgid = False
        in_msgstr = True
        fixed_lines.append(line)
    elif line.startswith('\"') and (in_msgid or in_msgstr):
        # This is a continuation line
        if not line.endswith('\"'):
            # Missing closing quote
            line += '\"'
        fixed_lines.append(line)
    else:
        in_msgid = False
        in_msgstr = False
        fixed_lines.append(line)

with open('$ENGLISH_MESSAGES_DIR/messages.po.fixed', 'w', encoding='utf-8') as f:
    f.write('\n'.join(fixed_lines))
"
        
        if [ -f "$ENGLISH_MESSAGES_DIR/messages.po.fixed" ]; then
            mv "$ENGLISH_MESSAGES_DIR/messages.po.fixed" "$ENGLISH_MESSAGES_DIR/messages.po"
            echo "  - Applied manual fixes"
            
            # Test if the fix worked
            if ! msgfmt --check "$ENGLISH_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                echo "  - Manual fix failed, creating fresh file from template..."
                msginit --no-translator --locale=en_EN --input="$LOCALE_DIR/$TEMPLATE" --output="$ENGLISH_MESSAGES_DIR/messages.po"
            fi
        else
            echo "  - Manual fix failed, creating fresh file from template..."
            msginit --no-translator --locale=en_EN --input="$LOCALE_DIR/$TEMPLATE" --output="$ENGLISH_MESSAGES_DIR/messages.po"
        fi
    fi
fi

# Clean up obsolete translations
cleanup_obsolete_translations "$ENGLISH_MESSAGES_DIR/messages.po"

# Skip the aggressive msgen step that overwrites all English translations
echo "  - English translations preserved and new entries added"

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
        
        # Merge with template (preserve existing translations)
        msgmerge --no-fuzzy-matching --quiet "$LOCALE_MESSAGES_DIR/messages.po" "$LOCALE_DIR/$TEMPLATE" -o "$LOCALE_MESSAGES_DIR/messages.po.tmp"
        mv "$LOCALE_MESSAGES_DIR/messages.po.tmp" "$LOCALE_MESSAGES_DIR/messages.po"
        
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
                if '#, auto-english-fallback' not in entry:
                    # Remove any existing fuzzy flag if present since we're replacing this with a concrete translation
                    entry = re.sub(r'#, fuzzy\n', '', entry)
                    
                    if '#:' in entry:
                        # Insert after the file reference line
                        entry = re.sub(r'(#:.*(\n#:.*)*)', r'\\1\n#, auto-english-fallback', entry)
                    else:
                        # Insert at the beginning of the entry
                        entry = '#, auto-english-fallback\n' + entry
                
                # Replace the empty msgstr with the English translation
                entry = re.sub(r'msgstr \"\"', 'msgstr ' + english_trans[msgid], entry)
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
                echo "  - Warning: File has syntax issues, attempting to fix..."
                
                # First try to fix common header issues (missing plural forms)
                python3 -c "
import re

with open('$LOCALE_MESSAGES_DIR/messages.po', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix missing plural forms for different locales
locale_plurals = {
    'cs': 'nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;',
    'de': 'nplurals=2; plural=(n != 1);',
    'es': 'nplurals=2; plural=(n != 1);',
    'fr': 'nplurals=2; plural=(n > 1);',
    'it': 'nplurals=2; plural=(n != 1);',
    'ja': 'nplurals=1; plural=0;',
    'lt': 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'nb': 'nplurals=2; plural=(n != 1);',
    'nl': 'nplurals=2; plural=(n != 1);',
    'pl': 'nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'pt': 'nplurals=2; plural=(n != 1);',
    'ru': 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'tr': 'nplurals=2; plural=(n != 1);',
    'zh': 'nplurals=1; plural=0;'
}

# Extract locale code from filename
locale_code = '$locale'.split('_')[0].lower()
plural_forms = locale_plurals.get(locale_code, 'nplurals=2; plural=(n != 1);')

# Fix missing Plural-Forms header
if 'Plural-Forms:' not in content:
    content = re.sub(
        r'(\"Content-Transfer-Encoding: 8bit\\\\n\")',
        r'\1\n\"Plural-Forms: ' + plural_forms + '\\\\n\"',
        content
    )

# Update Language field to correct locale code
content = re.sub(r'\"Language: en_EN\\\\n\"', '\"Language: ' + locale_code + '\\\\n\"', content)

with open('$LOCALE_MESSAGES_DIR/messages.po.headerfix', 'w', encoding='utf-8') as f:
    f.write(content)
"
                
                if [ -f "$LOCALE_MESSAGES_DIR/messages.po.headerfix" ]; then
                    mv "$LOCALE_MESSAGES_DIR/messages.po.headerfix" "$LOCALE_MESSAGES_DIR/messages.po"
                    echo "  - Applied header fixes"
                    
                    # Test if header fix worked
                    if msgfmt --check "$LOCALE_MESSAGES_DIR/messages.po" -o /dev/null 2>/dev/null; then
                        echo "  - Header fixes successful"
                    else
                        echo "  - Header fixes insufficient, trying msgcat..."
                        if msgcat --no-wrap "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po.fixed" 2>/dev/null; then
                            mv "$LOCALE_MESSAGES_DIR/messages.po.fixed" "$LOCALE_MESSAGES_DIR/messages.po"
                            echo "  - msgcat fixes applied"
                        else
                            echo "  - Warning: Could not fix syntax issues, but preserving existing translations"
                        fi
                    fi
                else
                    echo "  - Header fix failed, trying msgcat..."
                    if msgcat --no-wrap "$LOCALE_MESSAGES_DIR/messages.po" -o "$LOCALE_MESSAGES_DIR/messages.po.fixed" 2>/dev/null; then
                        mv "$LOCALE_MESSAGES_DIR/messages.po.fixed" "$LOCALE_MESSAGES_DIR/messages.po"
                        echo "  - msgcat fixes applied"
                    else
                        echo "  - Warning: Could not fix syntax issues, but preserving existing translations"
                    fi
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
        
        # Keep backup with timestamp for safety
        TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
        mv "$LOCALE_MESSAGES_DIR/messages.po.bak" "$LOCALE_MESSAGES_DIR/messages.po.backup.$TIMESTAMP"
        echo "  - Backup saved as messages.po.backup.$TIMESTAMP"
    fi
done

# Clean up temp files
rm -f "$ENGLISH_TRANS_MAP"

# Final instructions 
echo ""
echo "Translation files have been updated. To compile .mo files, run:"
echo "./scripts/compile_messages.sh"
echo ""
echo "Obsolete translations with actual content have been preserved for review."
echo ""
echo "Entries that were empty and filled with English translations are marked with '#, auto-english-fallback'."
echo "You can find them using grep: grep -r \"auto-english-fallback\" locale/"
