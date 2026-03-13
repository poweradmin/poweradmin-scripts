#!/bin/bash

# Script: pre-release-check.sh
# Description: Pre-release checklist - auto-detects branch and runs relevant checks
# Usage: ./scripts/pre-release-check.sh [--fix]
#
# Works on all branches: release/3.x, release/4.0.x, release/4.1.x, master, develop
# Checks are adapted based on what files and features exist on the current branch.

set -euo pipefail

# Check if the script is being run from the project root
check_run_from_project_root() {
    local script_name
    script_name=$(basename "$0")
    if [[ "$0" != "./scripts/$script_name" && "$0" != "scripts/$script_name" ]]; then
        echo "Error: This script should be run from the project root as:"
        echo "  ./scripts/$script_name"
        exit 1
    fi
}

check_run_from_project_root

FIX_MODE=false
for arg in "$@"; do
    case "$arg" in
        --fix) FIX_MODE=true ;;
        --help|-h)
            echo "Usage: ./scripts/pre-release-check.sh [--fix]"
            echo ""
            echo "Options:"
            echo "  --fix    Automatically fix what can be fixed"
            echo "  --help   Show this help message"
            exit 0
            ;;
    esac
done

PASS=0
FAIL=0
WARN=0

pass() { PASS=$((PASS + 1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  [FAIL] $1"; }
warn() { WARN=$((WARN + 1)); echo "  [WARN] $1"; }
info() { echo "  [INFO] $1"; }

# Detect branch
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")

# Detect minimum PHP version from composer.json
MIN_PHP=""
if [[ -f composer.json ]]; then
    MIN_PHP=$(python3 -c "import json; d=json.load(open('composer.json')); print(d.get('require',{}).get('php',''))" 2>/dev/null || echo "")
fi

# Determine lowest compat target
COMPAT_TARGET=""
if [[ -f composer.json ]]; then
    if composer run-script --list 2>/dev/null | grep -q "compat:8.1"; then
        COMPAT_TARGET="8.1"
    elif composer run-script --list 2>/dev/null | grep -q "compat:8.2"; then
        COMPAT_TARGET="8.2"
    fi
fi

echo "============================================"
echo "  Pre-release checklist"
echo "  Branch: $BRANCH"
echo "  PHP:    $MIN_PHP"
echo "  Date:   $(date +%Y-%m-%d)"
echo "============================================"
echo ""

# -----------------------------------------------
# 1. Branch and git state
# -----------------------------------------------
echo "1. Branch and git state"

case "$BRANCH" in
    release/*|master|develop)
        pass "On recognized branch ($BRANCH)" ;;
    *)
        warn "On unrecognized branch ($BRANCH)" ;;
esac

if git diff --quiet && git diff --cached --quiet; then
    pass "Working tree is clean"
else
    fail "Uncommitted changes detected"
fi

echo ""

# -----------------------------------------------
# 2. Code quality
# -----------------------------------------------
echo "2. Code quality"

if command -v composer &> /dev/null; then
    echo "  Running unit tests..."
    if composer tests --quiet 2>/dev/null; then
        pass "Unit tests pass"
    else
        fail "Unit tests failed (run: composer tests)"
    fi

    echo "  Running code style check..."
    if composer check:all --quiet 2>/dev/null; then
        pass "Code style check passes"
    else
        fail "Code style issues found (run: composer format:all)"
    fi

    echo "  Running static analysis..."
    if composer analyse:all --quiet 2>/dev/null; then
        pass "Static analysis passes"
    else
        warn "Static analysis has findings (run: composer analyse:all)"
    fi

    if [[ -n "$COMPAT_TARGET" ]]; then
        echo "  Running PHP $COMPAT_TARGET compatibility check..."
        if composer "compat:$COMPAT_TARGET" --quiet 2>/dev/null; then
            pass "PHP $COMPAT_TARGET compatibility OK"
        else
            fail "PHP $COMPAT_TARGET compatibility issues found"
        fi
    fi
else
    warn "composer not found, skipping code quality checks"
fi

echo ""

# -----------------------------------------------
# 3. Translations
# -----------------------------------------------
echo "3. Translations"

if command -v msgfmt &> /dev/null; then
    # Check main locale translations
    all_translated=true
    locale_count=0
    for po_file in locale/*/LC_MESSAGES/messages.po; do
        [[ -f "$po_file" ]] || continue
        locale_name=$(basename "$(dirname "$(dirname "$po_file")")")

        # Skip en_EN - it's intentionally untranslated
        [[ "$locale_name" == "en_EN" ]] && continue

        stats=$(msgfmt --statistics "$po_file" 2>&1)
        fuzzy=$(echo "$stats" | grep -o '[0-9]\+ fuzzy' | grep -o '[0-9]\+' || echo "0")
        untranslated=$(echo "$stats" | grep -o '[0-9]\+ untranslated' | grep -o '[0-9]\+' || echo "0")
        locale_count=$((locale_count + 1))

        if [[ "$fuzzy" -gt 0 || "$untranslated" -gt 0 ]]; then
            fail "$locale_name: $fuzzy fuzzy, $untranslated untranslated"
            all_translated=false
        fi
    done

    if $all_translated; then
        pass "All $locale_count locales fully translated"
    fi

    # Check module translations if modules exist
    if [[ -d lib/Module ]]; then
        for module_dir in lib/Module/*/locale; do
            [[ -d "$module_dir" ]] || continue
            module_name=$(basename "$(dirname "$module_dir")")
            for po_file in "$module_dir"/*/messages.po; do
                [[ -f "$po_file" ]] || continue
                locale_name=$(basename "$(dirname "$po_file")")
                [[ "$locale_name" == "en_EN" ]] && continue

                stats=$(msgfmt --statistics "$po_file" 2>&1)
                fuzzy=$(echo "$stats" | grep -o '[0-9]\+ fuzzy' | grep -o '[0-9]\+' || echo "0")
                untranslated=$(echo "$stats" | grep -o '[0-9]\+ untranslated' | grep -o '[0-9]\+' || echo "0")

                if [[ "$fuzzy" -gt 0 || "$untranslated" -gt 0 ]]; then
                    fail "$module_name/$locale_name: $fuzzy fuzzy, $untranslated untranslated"
                fi
            done
        done
    fi

    # Check .pot is up to date (compare ignoring timestamps)
    if [[ -x scripts/extract_strings.sh && -f locale/i18n-template-php.pot ]]; then
        pot_before=$(grep -v "^\"POT-Creation-Date:" locale/i18n-template-php.pot | md5 -q 2>/dev/null || grep -v "^\"POT-Creation-Date:" locale/i18n-template-php.pot | md5sum | cut -d' ' -f1)
        ./scripts/extract_strings.sh > /dev/null 2>&1
        pot_after=$(grep -v "^\"POT-Creation-Date:" locale/i18n-template-php.pot | md5 -q 2>/dev/null || grep -v "^\"POT-Creation-Date:" locale/i18n-template-php.pot | md5sum | cut -d' ' -f1)

        if [[ "$pot_before" == "$pot_after" ]]; then
            pass ".pot template is up to date"
        else
            fail ".pot template is outdated (run: ./scripts/extract_strings.sh)"
            if $FIX_MODE; then
                info "Fixed: .pot regenerated"
            fi
        fi

        # Restore original to avoid dirty tree from timestamp-only change
        git checkout locale/i18n-template-php.pot 2>/dev/null || true
    fi

    # Check .po files are in sync with .pot template (no missing entries)
    if command -v msgmerge &> /dev/null && [[ -f locale/i18n-template-php.pot ]]; then
        po_out_of_sync=false
        for po_file in locale/*/LC_MESSAGES/messages.po; do
            [[ -f "$po_file" ]] || continue
            locale_name=$(basename "$(dirname "$(dirname "$po_file")")")
            [[ "$locale_name" == "en_EN" ]] && continue

            # Merge to temp file and compare msgid count
            tmp_merged=$(mktemp)
            msgmerge --quiet "$po_file" locale/i18n-template-php.pot -o "$tmp_merged" 2>/dev/null

            orig_count=$(grep -c '^msgid ' "$po_file" || echo 0)
            merged_count=$(grep -c '^msgid ' "$tmp_merged" || echo 0)
            rm -f "$tmp_merged"

            if [[ "$merged_count" -gt "$orig_count" ]]; then
                new_entries=$((merged_count - orig_count))
                fail "$locale_name: $new_entries strings missing from .pot template (run: msgmerge --update)"
                po_out_of_sync=true
            fi
        done

        if ! $po_out_of_sync; then
            pass "All .po files in sync with .pot template"
        elif $FIX_MODE; then
            for po_file in locale/*/LC_MESSAGES/messages.po; do
                [[ -f "$po_file" ]] || continue
                locale_name=$(basename "$(dirname "$(dirname "$po_file")")")
                [[ "$locale_name" == "en_EN" ]] && continue
                msgmerge --update --quiet "$po_file" locale/i18n-template-php.pot 2>/dev/null
            done
            info "Fixed: all .po files merged with .pot template"
        fi
    fi

    # Check .mo files are compiled and up to date
    mo_outdated=false
    for po_file in locale/*/LC_MESSAGES/messages.po; do
        [[ -f "$po_file" ]] || continue
        mo_file="${po_file%.po}.mo"
        if [[ ! -f "$mo_file" ]]; then
            fail "Missing .mo file: $mo_file"
            mo_outdated=true
        elif [[ "$po_file" -nt "$mo_file" ]]; then
            fail "Outdated .mo file: $mo_file"
            mo_outdated=true
        fi
    done

    if ! $mo_outdated; then
        pass "All .mo files are up to date"
    elif $FIX_MODE; then
        for po_file in locale/*/LC_MESSAGES/messages.po; do
            mo_file="${po_file%.po}.mo"
            msgfmt "$po_file" -o "$mo_file"
        done
        info "Fixed: all .mo files recompiled"
    fi
else
    warn "msgfmt not found, skipping translation checks"
fi

echo ""

# -----------------------------------------------
# 4. Data files
# -----------------------------------------------
echo "4. Data files"

check_file_age() {
    local file="$1"
    local label="$2"
    local update_cmd="$3"
    local max_days="${4:-30}"

    if [[ -f "$file" ]]; then
        file_date=$(stat -f "%Sm" -t "%Y-%m-%d" "$file" 2>/dev/null || stat -c "%y" "$file" 2>/dev/null | cut -d' ' -f1)
        days_old=$(( ($(date +%s) - $(date -j -f "%Y-%m-%d" "$file_date" +%s 2>/dev/null || date -d "$file_date" +%s 2>/dev/null)) / 86400 ))

        if [[ $days_old -lt $max_days ]]; then
            pass "$label is recent ($file_date)"
        else
            warn "$label is $days_old days old ($file_date)"
            info "Update with: $update_cmd"
        fi
    fi
}

# Public suffix list (all branches)
check_file_age "data/public_suffix_list.dat" "Public suffix list" "./scripts/update_public_suffix.sh"

# TLD list - different locations depending on branch
if [[ -f data/tlds.php ]]; then
    check_file_age "data/tlds.php" "TLD list" "./scripts/update_tlds.sh"
elif [[ -f lib/Domain/Model/TopLevelDomain.php ]]; then
    tld_date=$(grep -o "Updated on [0-9-]*" lib/Domain/Model/TopLevelDomain.php | grep -o "[0-9-]*" || true)
    if [[ -n "$tld_date" ]]; then
        days_old=$(( ($(date +%s) - $(date -j -f "%Y-%m-%d" "$tld_date" +%s 2>/dev/null || date -d "$tld_date" +%s 2>/dev/null)) / 86400 ))
        if [[ $days_old -lt 30 ]]; then
            pass "TLD list is recent ($tld_date, in TopLevelDomain.php)"
        else
            warn "TLD list is $days_old days old ($tld_date, in TopLevelDomain.php)"
            info "Update with: ./scripts/update_tlds.sh"
        fi
    else
        warn "Could not determine TLD list age from TopLevelDomain.php"
    fi
fi

# RDAP servers
if [[ -f lib/Module/Rdap/data/rdap_servers.php ]]; then
    check_file_age "lib/Module/Rdap/data/rdap_servers.php" "RDAP servers" "./scripts/update_rdap_servers.php" 90
elif [[ -f data/rdap_servers.php ]]; then
    check_file_age "data/rdap_servers.php" "RDAP servers" "./scripts/update_rdap_servers.php" 90
elif [[ -f data/rdap_servers.json ]]; then
    check_file_age "data/rdap_servers.json" "RDAP servers" "./scripts/update_rdap_servers.php" 90
fi

# WHOIS servers
if [[ -f lib/Module/Whois/data/whois_servers.php ]]; then
    check_file_age "lib/Module/Whois/data/whois_servers.php" "WHOIS servers" "./scripts/update_whois_servers.php" 90
elif [[ -f data/whois_servers.php ]]; then
    check_file_age "data/whois_servers.php" "WHOIS servers" "./scripts/update_whois_servers.php" 90
elif [[ -f data/whois_servers.json ]]; then
    check_file_age "data/whois_servers.json" "WHOIS servers" "./scripts/update_whois_servers.php" 90
fi

echo ""

# -----------------------------------------------
# 5. Dependencies
# -----------------------------------------------
echo "5. Dependencies"

if [[ -f composer.lock ]]; then
    lock_date=$(git log -1 --format="%ai" -- composer.lock 2>/dev/null | cut -d' ' -f1)
    if [[ -n "$lock_date" ]]; then
        info "composer.lock last updated: $lock_date"
    fi

    if command -v composer &> /dev/null; then
        if composer validate --no-check-publish --quiet 2>/dev/null; then
            pass "composer.json is valid"
        else
            fail "composer.json validation failed"
        fi
    fi
else
    warn "composer.lock not found"
fi

echo ""

# -----------------------------------------------
# 6. Security
# -----------------------------------------------
echo "6. Security"

# Check for install directory
if [[ -d install ]]; then
    warn "install/ directory exists (remove before production deployment)"
else
    pass "No install/ directory"
fi

# Check no sensitive files are tracked
sensitive_found=false
for f in inc/config.inc.php config/app.php config/settings.php .env; do
    if git ls-files --error-unmatch "$f" &> /dev/null 2>&1; then
        fail "Sensitive file tracked in git: $f"
        sensitive_found=true
    fi
done
if ! $sensitive_found; then
    pass "No sensitive files tracked"
fi

echo ""

# -----------------------------------------------
# 7. Version
# -----------------------------------------------
echo "7. Version"

version=""
if [[ -f lib/Version.php ]]; then
    version=$(grep "VERSION" lib/Version.php | grep -o "'[0-9][^']*'" | tr -d "'" | head -1 || true)
fi

if [[ -n "$version" ]]; then
    info "Current version: $version"

    latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "none")
    info "Latest tag: $latest_tag"

    if [[ "$latest_tag" != "v$version" && "$latest_tag" != "$version" ]]; then
        info "Version $version has not been tagged yet"
    fi
else
    warn "Could not determine version from lib/Version.php"
fi

echo ""

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo "============================================"
echo "  Summary: $PASS passed, $FAIL failed, $WARN warnings"
echo "============================================"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "Fix failing checks before release."
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo ""
    echo "Review warnings before release."
    exit 0
else
    echo ""
    echo "All checks passed. Ready for release."
    exit 0
fi
