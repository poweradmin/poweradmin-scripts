#!/bin/bash

set -euo pipefail

YEAR=$(date "+%Y")
VERSION=$(grep VERSION ../lib/Version.php | cut -d "'" -f2)
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

find "${CODE_DIR}" -name "*.php" | xargs xgettext \
    --no-wrap \
    -L PHP \
    --copyright-holder="Poweradmin Development Team" \
    --msgid-bugs-address="edmondas@girkantas.lt" \
    -o "${PHP_POT}" \
    --package-name=Poweradmin \
    --package-version="${VERSION}"

find "${HELPERS_DIR}" -name "*.php" | xargs xgettext \
    --no-wrap \
    -L PHP \
    --copyright-holder="Poweradmin Development Team" \
    --msgid-bugs-address="edmondas@girkantas.lt" \
    -o "${HELPERS_POT}" \
    --package-name=Poweradmin \
    --package-version="${VERSION}"

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


find "$TEMPLATES_DIR" -name "*.html" | while read -r file; do
    process_file "$file" >> "${HTML_POT}"
done
msguniq "${HTML_POT}" --output="${HTML_POT}"

find "$INSTALL_DIR" -name "*.html" | while read -r file; do
    process_file "$file" >> "${INSTALL_POT}"
done
msguniq "${INSTALL_POT}" --output="${INSTALL_POT}"

msgfmt --check "${PHP_POT}" || { echo "Error in PHP strings"; exit 1; }
msgfmt --check "${HTML_POT}" || { echo "Error in HTML strings"; exit 1; }
msgfmt --check "${INSTALL_POT}" || { echo "Error in install strings"; exit 1; }
msgfmt --check "${HELPERS_POT}" || { echo "Error in helpers strings"; exit 1; }

msgcat --width=80 "${PHP_POT}" "${HTML_POT}" "${INSTALL_POT}" "${HELPERS_POT}" | msguniq --output="${OUTPUT_POT}"

echo "Template generation complete."