#!/bin/bash

# Make the script more resilient by not failing immediately on errors
set -u

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

# Enable debugging if DEBUG is set
if [ "${DEBUG:-0}" = "1" ]; then
    set -x
fi

YEAR=$(date "+%Y")

# Safer version determination
if [ -f "lib/Version.php" ]; then
    VERSION=$(grep VERSION lib/Version.php | cut -d "'" -f2 || echo "unknown")
else
    VERSION="unknown"
    echo "Warning: Unable to determine version. Using '$VERSION'"
fi

CODE_DIR="lib"

TEMPLATES_DIR="templates"
MODULE_TEMPLATES_DIR="lib/Module"
INSTALL_DIR="install/templates"
HELPERS_DIR="install/helpers"
OUTPUT_POT="locale/i18n-template-php.pot"

TEMP_DIR=$(mktemp -d)

PHP_POT="${TEMP_DIR}/php_strings.pot"
HTML_POT="${TEMP_DIR}/html_strings.pot"
INSTALL_POT="${TEMP_DIR}/install_strings.pot"
HELPERS_POT="${TEMP_DIR}/helpers_strings.pot"

cleanup() {
    rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

# Check script is run from project root
check_run_from_project_root

# Get the absolute path to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "Error: Failed to change to project root directory: $PROJECT_ROOT"; exit 1; }

# Create directory if not exists
mkdir -p "$(dirname "${OUTPUT_POT}")"

# Check if directories exist
if [ ! -d "${CODE_DIR}" ]; then
    echo "Error: Directory ${CODE_DIR} not found"
    exit 1
fi

find "${CODE_DIR}" -name "*.php" | xargs xgettext \
    --no-wrap \
    -L PHP \
    --copyright-holder="Poweradmin Development Team" \
    --msgid-bugs-address="edmondas@girkantas.lt" \
    -o "${PHP_POT}" \
    --package-name=Poweradmin \
    --package-version="${VERSION}" \
    --from-code=UTF-8

# Skip if helpers directory doesn't exist
if [ -d "${HELPERS_DIR}" ]; then
    find "${HELPERS_DIR}" -name "*.php" | xargs xgettext \
        --no-wrap \
        -L PHP \
        --copyright-holder="Poweradmin Development Team" \
        --msgid-bugs-address="edmondas@girkantas.lt" \
        -o "${HELPERS_POT}" \
        --package-name=Poweradmin \
        --package-version="${VERSION}" \
        --from-code=UTF-8
    
    # Fix the headers in helpers POT file too
    if [ -s "${HELPERS_POT}" ]; then
        sed -i.bak '
            s/SOME DESCRIPTIVE TITLE/Poweradmin translation template/;
            s/Language: /Language: en_EN/;
            s/PACKAGE/Poweradmin/;
            s/(C) YEAR/(C) '"${YEAR}"'/;
            s/CHARSET/UTF-8/;
            /Plural-Forms:/d
        ' "${HELPERS_POT}" && rm "${HELPERS_POT}.bak"
    fi
else
    echo "Warning: Helpers directory ${HELPERS_DIR} not found, skipping"
    touch "${HELPERS_POT}"  # Create empty file
fi

sed -i.bak '
    s/SOME DESCRIPTIVE TITLE/Poweradmin translation template/;
    s/Language: /Language: en_EN/;
    s/PACKAGE/Poweradmin/;
    s/(C) YEAR/(C) '"${YEAR}"'/;
    s/CHARSET/UTF-8/;
    /Plural-Forms:/d
' "${PHP_POT}" && rm "${PHP_POT}.bak"

cat > "${HTML_POT}" << EOF
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
EOF

cat > "${INSTALL_POT}" << EOF
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
EOF

escape_string() {
    # Escape double quotes and handle single quotes properly for gettext
    echo "$1" | sed 's/"/\\"/g'
}

extract_translations() {
    local file="$1"
    
    # More direct approach with Python that handles all edge cases
    python3 -c "
import re
import sys

def extract_translations(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Match all trans blocks with regex that supports special chars
    pattern = re.compile(r'{%\s*trans\s*%}(.*?){%\s*endtrans\s*%}', re.DOTALL)
    
    # Find line numbers for each match
    lines = content.split('\\n')
    match_line_nums = {}
    
    for i, line in enumerate(lines, 1):
        matches = pattern.findall(line)
        for match in matches:
            # Trim whitespace and skip empty translations
            trans_text = match.strip()
            if trans_text:
                # Escape double quotes for gettext
                escaped = trans_text.replace('\"', '\\\\\"')
                # Store with line number
                print(f'#: {file_path}:{i}')
                print(f'msgid \"{escaped}\"')
                print(f'msgstr \"\"')
                print('')

extract_translations('$file')
"
}

process_file() {
    local file_path="$1"
    local output_file="$2"

    if [[ ! -f "$file_path" ]]; then
        echo "Error: File not found: $file_path" >&2
        return 1
    fi

    extract_translations "$file_path" > "${TEMP_DIR}/single_file.pot"
    
    # Check if file has valid content before appending
    if [ -s "${TEMP_DIR}/single_file.pot" ]; then
        cat "${TEMP_DIR}/single_file.pot" >> "$output_file"
    fi
}


# Process templates if directory exists
if [ -d "$TEMPLATES_DIR" ]; then
    # Create a temp file for processing with proper PO header (required by msguniq)
    TEMP_HTML_POT="${TEMP_DIR}/temp_html.pot"
    cat > "${TEMP_HTML_POT}" << TMPEOF
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"

TMPEOF

    find "$TEMPLATES_DIR" \( -name "*.html" -o -name "*.html.twig" \) | while read -r file; do
        process_file "$file" "${TEMP_HTML_POT}"
    done

    # Also scan module template directories
    if [ -d "$MODULE_TEMPLATES_DIR" ]; then
        find "$MODULE_TEMPLATES_DIR" -path "*/templates/*.html" | while read -r file; do
            process_file "$file" "${TEMP_HTML_POT}"
        done
    fi

    # Use msguniq to deduplicate and write to final HTML POT
    if [ -s "${TEMP_HTML_POT}" ]; then
        msguniq "${TEMP_HTML_POT}" --force-po -o "${HTML_POT}" || cp "${TEMP_HTML_POT}" "${HTML_POT}"
    fi
else
    echo "Warning: Templates directory ${TEMPLATES_DIR} not found, skipping"
    touch "${HTML_POT}"  # Create empty file
fi

# Process install templates if directory exists
if [ -d "$INSTALL_DIR" ]; then
    # Create a temp file for processing with proper PO header (required by msguniq)
    TEMP_INSTALL_POT="${TEMP_DIR}/temp_install.pot"
    cat > "${TEMP_INSTALL_POT}" << TMPEOF
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"

TMPEOF

    find "$INSTALL_DIR" \( -name "*.html" -o -name "*.html.twig" \) | while read -r file; do
        process_file "$file" "${TEMP_INSTALL_POT}"
    done

    # Use msguniq to deduplicate and write to final install POT
    if [ -s "${TEMP_INSTALL_POT}" ]; then
        msguniq "${TEMP_INSTALL_POT}" --force-po -o "${INSTALL_POT}" || cp "${TEMP_INSTALL_POT}" "${INSTALL_POT}"
    fi
else
    echo "Warning: Install directory ${INSTALL_DIR} not found, skipping"
    touch "${INSTALL_POT}"  # Create empty file
fi

# Check POT files with msgfmt - safely handle empty files
for pot_file in "${PHP_POT}" "${HTML_POT}" "${INSTALL_POT}" "${HELPERS_POT}"; do
    if [ -s "${pot_file}" ]; then
        if ! msgfmt --check "${pot_file}" -o /dev/null 2>/dev/null; then
            echo "Error in ${pot_file##*/}"
            # Just warn, don't exit
        fi
    else
        # Create an empty but valid POT file if it doesn't exist
        if [ ! -f "${pot_file}" ]; then
            cat > "${pot_file}" << EOF
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
EOF
        fi
    fi
done

# Process each POT file with msguniq separately before combining
# Skip the pre-processing steps as they're now handled in the individual file processing sections

# Combine all extracted strings into a single POT file
mkdir -p "$(dirname "${OUTPUT_POT}")"

# Create a fresh POT file with proper headers
cat > "${OUTPUT_POT}" << EOF
# Poweradmin translation template.
# Copyright (C) ${YEAR} Poweradmin Development Team
# This file is distributed under the same license as the Poweradmin package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: Poweradmin ${VERSION}\n"
"Report-Msgid-Bugs-To: edmondas@girkantas.lt\n"
"POT-Creation-Date: $(date "+%Y-%m-%d %H:%M%z")\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: en_EN\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
EOF

# Function to safely append a POT file to the combined output
# Extract strings only, not headers
safe_append_pot() {
    local source="$1"
    local target="$2"
    
    if [ -s "$source" ]; then
        # Process each msgid/msgstr group in the file, skipping headers
        # We look for lines starting with "#:" and collect everything up to the next empty line
        awk '
        BEGIN { in_record = 0; }
        /^#:/ { 
            in_record = 1; 
            record = $0; 
            next; 
        }
        in_record && /^$/ { 
            print record; 
            in_record = 0; 
            record = ""; 
            print ""; 
            next; 
        }
        in_record { 
            record = record "\n" $0; 
        }
        ' "$source" | grep -v "Project-Id-Version" >> "$target"
    fi
}

# Append strings from each POT file to the combined file
safe_append_pot "${PHP_POT}" "${OUTPUT_POT}"
safe_append_pot "${HTML_POT}" "${OUTPUT_POT}"
safe_append_pot "${INSTALL_POT}" "${OUTPUT_POT}"
safe_append_pot "${HELPERS_POT}" "${OUTPUT_POT}"

# Use msguniq to remove any duplicates
FINAL_POT="${TEMP_DIR}/final.pot"
msguniq "${OUTPUT_POT}" --output="${FINAL_POT}" --force-po && cp "${FINAL_POT}" "${OUTPUT_POT}" || echo "Warning: Failed to deduplicate the final POT file"

echo "Template generation complete."