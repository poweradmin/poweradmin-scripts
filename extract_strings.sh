#!/bin/bash

# Make the script more resilient by not failing immediately on errors
set -u

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

cd "$(dirname "$0")/.." || exit 1

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
    --package-version="${VERSION}"

# Skip if helpers directory doesn't exist
if [ -d "${HELPERS_DIR}" ]; then
    find "${HELPERS_DIR}" -name "*.php" | xargs xgettext \
        --no-wrap \
        -L PHP \
        --copyright-holder="Poweradmin Development Team" \
        --msgid-bugs-address="edmondas@girkantas.lt" \
        -o "${HELPERS_POT}" \
        --package-name=Poweradmin \
        --package-version="${VERSION}"
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
    echo "$1" | sed 's/"/\\"/g'
}

extract_translations() {
    local file="$1"
    local line_number=0

    while IFS= read -r line; do
        ((line_number++))
        while [[ $line =~ \{%[[:space:]]*trans[[:space:]]*%\}([^{]*)\{%[[:space:]]*endtrans[[:space:]]*%\} ]]; do
            local translation="${BASH_REMATCH[1]}"
            translation=$(echo "$translation" | xargs)
            escaped_translation=$(escape_string "$translation")
            echo "#: $file:$line_number"
            echo "msgid \"$escaped_translation\""
            echo "msgstr \"\""
            echo
            line=${line#*"${BASH_REMATCH[0]}"}
            [[ -z "$line" ]] && break
        done
    done < "$file"
}

process_file() {
    local file_path="$1"

    if [[ ! -f "$file_path" ]]; then
        echo "Error: File not found: $file_path" >&2
        return 1
    fi

    extract_translations "$file_path"
}


# Process templates if directory exists
if [ -d "$TEMPLATES_DIR" ]; then
    find "$TEMPLATES_DIR" -name "*.html" | while read -r file; do
        process_file "$file" >> "${HTML_POT}"
    done
    msguniq "${HTML_POT}" --output="${HTML_POT}"
else
    echo "Warning: Templates directory ${TEMPLATES_DIR} not found, skipping"
    touch "${HTML_POT}"  # Create empty file
fi

# Process install templates if directory exists
if [ -d "$INSTALL_DIR" ]; then
    find "$INSTALL_DIR" -name "*.html" | while read -r file; do
        process_file "$file" >> "${INSTALL_POT}"
    done
    msguniq "${INSTALL_POT}" --output="${INSTALL_POT}"
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

# Combine all POT files, creating parent directory if needed
mkdir -p "$(dirname "${OUTPUT_POT}")"
msgcat --width=80 "${PHP_POT}" "${HTML_POT}" "${INSTALL_POT}" "${HELPERS_POT}" | msguniq --output="${OUTPUT_POT}" || true

echo "Template generation complete."