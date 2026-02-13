#!/bin/bash
# =============================================================================
# Test 4.1.0 Migration Scripts
# =============================================================================
#
# Tests the three sql/poweradmin-*-update-to-4.1.0.sql migration scripts
# against a fresh 4.0.6 database schema for each engine.
#
# Two scenarios per engine:
#   A) Empty 4.0.6 schema (no data, just tables)
#   B) 4.0.6 schema with test data (users, templates, zones)
#
# Steps per scenario:
#   1. Drop Poweradmin tables (NOT PowerDNS tables)
#   2. Load v4.0.6 schema
#   3. Optionally insert test data
#   4. Verify v4.0.6 state
#   5. Apply 4.1.0 migration
#   6. Verify migration result
#   7. Verify existing data preserved (scenario B)
#
# Usage:
#   ./scripts/test-migration-4.1.0.sh
#   ./scripts/test-migration-4.1.0.sh --mysql
#   ./scripts/test-migration-4.1.0.sh --pgsql
#   ./scripts/test-migration-4.1.0.sh --sqlite
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TMPDIR=$(mktemp -d)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
PASS=0
FAIL=0
ERRORS=""

# Database credentials
MYSQL_USER="${MYSQL_USER:-pdns}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-poweradmin}"
MYSQL_DATABASE="${MYSQL_DATABASE:-poweradmin}"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-mariadb}"

PGSQL_USER="${PGSQL_USER:-pdns}"
PGSQL_PASSWORD="${PGSQL_PASSWORD:-poweradmin}"
PGSQL_DATABASE="${PGSQL_DATABASE:-pdns}"
PGSQL_CONTAINER="${PGSQL_CONTAINER:-postgres}"

SQLITE_CONTAINER="${SQLITE_CONTAINER:-sqlite}"
SQLITE_DB_PATH="${SQLITE_DB_PATH:-/data/pdns.db}"

cleanup() {
    rm -rf "$TMPDIR"
}
trap cleanup EXIT

log_pass() {
    echo -e "  ${GREEN}PASS${NC}: $1"
    PASS=$((PASS + 1))
}

log_fail() {
    echo -e "  ${RED}FAIL${NC}: $1"
    FAIL=$((FAIL + 1))
    ERRORS="$ERRORS\n  - $1"
}

log_info() {
    echo -e "  ${BLUE}INFO${NC}: $1"
}

log_warn() {
    echo -e "  ${YELLOW}WARN${NC}: $1"
}

# ============================================================================
# Pre-flight checks
# ============================================================================
preflight() {
    echo -e "${BLUE}=== Pre-flight checks ===${NC}"

    if git rev-parse v4.0.6 >/dev/null 2>&1; then
        log_pass "Git tag v4.0.6 exists"
    else
        log_fail "Git tag v4.0.6 not found"
        echo "Cannot proceed without v4.0.6 tag."
        exit 1
    fi

    for engine in mysql pgsql sqlite; do
        local file="$PROJECT_DIR/sql/poweradmin-${engine}-update-to-4.1.0.sql"
        if [ -f "$file" ]; then
            log_pass "Migration file exists: poweradmin-${engine}-update-to-4.1.0.sql"
        else
            log_fail "Migration file missing: poweradmin-${engine}-update-to-4.1.0.sql"
        fi
    done

    for container in "$MYSQL_CONTAINER" "$PGSQL_CONTAINER" "$SQLITE_CONTAINER"; do
        if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
            log_pass "Container running: $container"
        else
            log_fail "Container not running: $container"
        fi
    done

    echo ""
}

# ============================================================================
# Extract v4.0.6 schemas
# ============================================================================
extract_schemas() {
    echo -e "${BLUE}=== Extracting v4.0.6 schemas ===${NC}"

    for engine in mysql pgsql sqlite; do
        git show "v4.0.6:sql/poweradmin-${engine}-db-structure.sql" > "$TMPDIR/v406-${engine}.sql" 2>/dev/null
        if [ -s "$TMPDIR/v406-${engine}.sql" ]; then
            log_pass "Extracted v4.0.6 ${engine} schema"
        else
            log_fail "Failed to extract v4.0.6 ${engine} schema"
        fi
    done

    echo ""
}

# ============================================================================
# Common verification (works for all engines)
# ============================================================================
verify_migration_result() {
    local engine=$1
    local scenario=$2  # "empty" or "with-data"
    local query_fn=$3  # function name to run queries

    log_info "Verifying migration result ($scenario)..."

    # Check new tables
    for table in oidc_user_links saml_user_links username_recovery_requests; do
        local exists=$($query_fn "table_exists" "$table")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] New table: $table"
        else
            log_fail "[$engine/$scenario] Missing table: $table"
        fi
    done

    # Check auth_method column
    local has_auth=$($query_fn "column_exists" "users" "auth_method")
    if [ "$has_auth" = "1" ]; then
        log_pass "[$engine/$scenario] users.auth_method column added"
    else
        log_fail "[$engine/$scenario] users.auth_method column missing"
    fi

    # Check new permissions
    local perm_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "27" ]; then
        log_pass "[$engine/$scenario] perm_items count = 27"
    else
        log_fail "[$engine/$scenario] perm_items count = $perm_count (expected 27)"
    fi

    for perm_id in 65 67 68; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_items WHERE id=$perm_id;")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] Permission id=$perm_id exists"
        else
            log_fail "[$engine/$scenario] Permission id=$perm_id missing"
        fi
    done

    # Check new templates
    local templ_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ;")
    if [ "$templ_count" = "5" ]; then
        log_pass "[$engine/$scenario] perm_templ count = 5"
    else
        log_fail "[$engine/$scenario] perm_templ count = $templ_count (expected 5)"
    fi

    for templ in "Zone Manager" "DNS Editor" "Read Only" "No Access"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='$templ';")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] Template: $templ"
        else
            log_fail "[$engine/$scenario] Missing template: $templ"
        fi
    done

    # Check performance indexes
    for idx in idx_log_zones_zone_id idx_users_perm_templ idx_perm_templ_items_templ_id idx_perm_templ_items_perm_id; do
        local exists=$($query_fn "index_exists" "$idx")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] Index: $idx"
        else
            log_fail "[$engine/$scenario] Missing index: $idx"
        fi
    done

    # Check data preservation (scenario B only)
    if [ "$scenario" = "with-data" ]; then
        local user_count=$($query_fn "query" "SELECT COUNT(*) FROM users;")
        if [ "$user_count" -ge "1" ]; then
            log_pass "[$engine/$scenario] Users preserved ($user_count)"
        else
            log_fail "[$engine/$scenario] Users lost after migration"
        fi

        local auth_default=$($query_fn "query" "SELECT auth_method FROM users LIMIT 1;")
        if [ "$auth_default" = "sql" ]; then
            log_pass "[$engine/$scenario] Existing user auth_method = 'sql'"
        else
            log_fail "[$engine/$scenario] Existing user auth_method = '$auth_default' (expected 'sql')"
        fi

        local admin_templ=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ_items WHERE templ_id=1 AND perm_id=53;")
        if [ "$admin_templ" = "1" ]; then
            log_pass "[$engine/$scenario] Administrator template preserved"
        else
            log_fail "[$engine/$scenario] Administrator template data lost"
        fi
    fi
}

# ============================================================================
# MySQL helpers
# ============================================================================

mysql_exec() {
    docker exec -i "$MYSQL_CONTAINER" mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$@" 2>/dev/null
}

mysql_raw_query() {
    docker exec -i "$MYSQL_CONTAINER" mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -e "$1" "$MYSQL_DATABASE" 2>/dev/null | tr -d ' \t\r\n'
}

mysql_helper() {
    local cmd=$1
    shift
    case $cmd in
        query)
            mysql_raw_query "$1"
            ;;
        table_exists)
            mysql_raw_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$MYSQL_DATABASE' AND table_name='$1';"
            ;;
        column_exists)
            mysql_raw_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='$MYSQL_DATABASE' AND table_name='$1' AND column_name='$2';"
            ;;
        index_exists)
            mysql_raw_query "SELECT IF(COUNT(*)>=1,1,0) FROM information_schema.statistics WHERE table_schema='$MYSQL_DATABASE' AND index_name='$1';"
            ;;
    esac
}

mysql_drop_poweradmin_tables() {
    mysql_exec "$MYSQL_DATABASE" <<'EOSQL'
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS zone_template_sync, records_zone_templ, zones, zone_templ_records, zone_templ,
    user_agreements, user_mfa, user_preferences, api_keys, login_attempts, password_reset_tokens,
    perm_templ_items, perm_templ, users, perm_items, log_users, log_zones, migrations,
    oidc_user_links, saml_user_links, username_recovery_requests;
SET FOREIGN_KEY_CHECKS = 1;
EOSQL
}

mysql_insert_test_data() {
    mysql_exec "$MYSQL_DATABASE" <<'EOSQL'
INSERT INTO `users` (`id`, `username`, `password`, `fullname`, `email`, `description`, `perm_templ`, `active`, `use_ldap`)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0);
EOSQL
}

test_mysql() {
    local scenario=$1  # "empty" or "with-data"

    echo -e "${BLUE}=== MySQL/MariaDB Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables..."
    mysql_drop_poweradmin_tables

    log_info "Loading v4.0.6 schema..."
    if mysql_exec "$MYSQL_DATABASE" < "$TMPDIR/v406-mysql.sql"; then
        log_pass "[mysql/$scenario] v4.0.6 schema loaded"
    else
        log_fail "[mysql/$scenario] Failed to load v4.0.6 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        mysql_insert_test_data
        local user_count=$(mysql_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[mysql/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.0.6 state
    local perm_count=$(mysql_raw_query "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "24" ]; then
        log_pass "[mysql/$scenario] v4.0.6 baseline: perm_items=24"
    else
        log_fail "[mysql/$scenario] v4.0.6 baseline: perm_items=$perm_count (expected 24)"
    fi

    local has_auth=$(mysql_helper column_exists users auth_method)
    if [ "$has_auth" = "0" ]; then
        log_pass "[mysql/$scenario] v4.0.6 baseline: no auth_method column"
    else
        log_fail "[mysql/$scenario] v4.0.6 baseline: auth_method already exists"
    fi

    # Apply migration
    log_info "Applying 4.1.0 migration..."
    local migration_output
    migration_output=$(mysql_exec "$MYSQL_DATABASE" < "$PROJECT_DIR/sql/poweradmin-mysql-update-to-4.1.0.sql" 2>&1) || true

    if [ -n "$migration_output" ]; then
        log_warn "Migration output: $migration_output"
    fi

    # Verify result
    verify_migration_result "mysql" "$scenario" "mysql_helper"

    # Check PowerDNS tables intact (separate database for MySQL)
    local pdns_domains=$(docker exec -i "$MYSQL_CONTAINER" mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='pdns' AND table_name='domains';" 2>/dev/null | tr -d ' \t\r\n')
    if [ "$pdns_domains" = "1" ]; then
        log_pass "[mysql/$scenario] PowerDNS tables intact"
    else
        log_fail "[mysql/$scenario] PowerDNS tables affected!"
    fi

    echo ""
}

# ============================================================================
# PostgreSQL helpers
# ============================================================================

pgsql_exec() {
    docker exec -i -e PGPASSWORD="$PGSQL_PASSWORD" "$PGSQL_CONTAINER" psql -U "$PGSQL_USER" -d "$PGSQL_DATABASE" "$@" 2>/dev/null
}

pgsql_raw_query() {
    docker exec -i -e PGPASSWORD="$PGSQL_PASSWORD" "$PGSQL_CONTAINER" psql -U "$PGSQL_USER" -d "$PGSQL_DATABASE" -tAc "$1" 2>/dev/null | tr -d ' \t\r\n'
}

pgsql_helper() {
    local cmd=$1
    shift
    case $cmd in
        query)
            pgsql_raw_query "$1"
            ;;
        table_exists)
            pgsql_raw_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='$1';"
            ;;
        column_exists)
            pgsql_raw_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='$1' AND column_name='$2';"
            ;;
        index_exists)
            pgsql_raw_query "SELECT CASE WHEN COUNT(*)>=1 THEN 1 ELSE 0 END FROM pg_indexes WHERE indexname='$1';"
            ;;
    esac
}

pgsql_drop_poweradmin_tables() {
    pgsql_exec <<'EOSQL'
DROP TABLE IF EXISTS zone_template_sync, records_zone_templ, zones, zone_templ_records, zone_templ,
    user_agreements, user_mfa, user_preferences, api_keys, login_attempts, password_reset_tokens,
    perm_templ_items, perm_templ, users, perm_items, log_users, log_zones, migrations,
    oidc_user_links, saml_user_links, username_recovery_requests CASCADE;

DROP SEQUENCE IF EXISTS api_keys_id_seq, log_users_id_seq1, log_zones_id_seq1,
    login_attempts_id_seq, perm_items_id_seq, perm_templ_id_seq, perm_templ_items_id_seq,
    records_zone_templ_id_seq, user_mfa_id_seq, users_id_seq, zone_templ_id_seq,
    zone_templ_records_id_seq, zones_id_seq CASCADE;
EOSQL
}

pgsql_insert_test_data() {
    pgsql_exec <<'EOSQL'
INSERT INTO users (id, username, password, fullname, email, description, perm_templ, active, use_ldap)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0);
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));
EOSQL
}

test_pgsql() {
    local scenario=$1

    echo -e "${BLUE}=== PostgreSQL Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables and sequences..."
    pgsql_drop_poweradmin_tables

    log_info "Loading v4.0.6 schema..."
    if pgsql_exec < "$TMPDIR/v406-pgsql.sql" > /dev/null; then
        log_pass "[pgsql/$scenario] v4.0.6 schema loaded"
    else
        log_fail "[pgsql/$scenario] Failed to load v4.0.6 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        pgsql_insert_test_data
        local user_count=$(pgsql_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[pgsql/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.0.6 state
    local perm_count=$(pgsql_raw_query "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "24" ]; then
        log_pass "[pgsql/$scenario] v4.0.6 baseline: perm_items=24"
    else
        log_fail "[pgsql/$scenario] v4.0.6 baseline: perm_items=$perm_count (expected 24)"
    fi

    local has_auth=$(pgsql_helper column_exists users auth_method)
    if [ "$has_auth" = "0" ]; then
        log_pass "[pgsql/$scenario] v4.0.6 baseline: no auth_method column"
    else
        log_fail "[pgsql/$scenario] v4.0.6 baseline: auth_method already exists"
    fi

    # Apply migration
    log_info "Applying 4.1.0 migration..."
    local migration_output
    migration_output=$(pgsql_exec < "$PROJECT_DIR/sql/poweradmin-pgsql-update-to-4.1.0.sql" 2>&1) || true

    if echo "$migration_output" | grep -qi "error"; then
        log_warn "Migration had errors:"
        echo "$migration_output" | grep -i "error" | head -5 | while read -r line; do
            log_warn "  $line"
        done
    fi

    # Verify result
    verify_migration_result "pgsql" "$scenario" "pgsql_helper"

    echo ""
}

# ============================================================================
# SQLite helpers
# ============================================================================

sqlite_exec() {
    docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" "$@" 2>/dev/null
}

sqlite_raw_query() {
    docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" "$1" 2>/dev/null | tr -d ' \t\r\n'
}

sqlite_helper() {
    local cmd=$1
    shift
    case $cmd in
        query)
            sqlite_raw_query "$1"
            ;;
        table_exists)
            sqlite_raw_query "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$1';"
            ;;
        column_exists)
            sqlite_raw_query "SELECT COUNT(*) FROM pragma_table_info('$1') WHERE name='$2';"
            ;;
        index_exists)
            sqlite_raw_query "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='$1';"
            ;;
    esac
}

sqlite_drop_poweradmin_tables() {
    sqlite_exec <<'EOSQL'
DROP TABLE IF EXISTS zone_template_sync;
DROP TABLE IF EXISTS records_zone_templ;
DROP TABLE IF EXISTS zones;
DROP TABLE IF EXISTS zone_templ_records;
DROP TABLE IF EXISTS zone_templ;
DROP TABLE IF EXISTS user_agreements;
DROP TABLE IF EXISTS user_mfa;
DROP TABLE IF EXISTS user_preferences;
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS login_attempts;
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS perm_templ_items;
DROP TABLE IF EXISTS perm_templ;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS perm_items;
DROP TABLE IF EXISTS log_users;
DROP TABLE IF EXISTS log_zones;
DROP TABLE IF EXISTS migrations;
DROP TABLE IF EXISTS oidc_user_links;
DROP TABLE IF EXISTS saml_user_links;
DROP TABLE IF EXISTS username_recovery_requests;
EOSQL
}

sqlite_insert_test_data() {
    sqlite_exec <<'EOSQL'
INSERT INTO users (id, username, password, fullname, email, description, perm_templ, active, use_ldap)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0);
EOSQL
}

test_sqlite() {
    local scenario=$1

    echo -e "${BLUE}=== SQLite Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables..."
    sqlite_drop_poweradmin_tables

    log_info "Loading v4.0.6 schema..."
    if docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" < "$TMPDIR/v406-sqlite.sql" > /dev/null 2>&1; then
        log_pass "[sqlite/$scenario] v4.0.6 schema loaded"
    else
        log_fail "[sqlite/$scenario] Failed to load v4.0.6 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        sqlite_insert_test_data
        local user_count=$(sqlite_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[sqlite/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.0.6 state
    local perm_count=$(sqlite_raw_query "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "24" ]; then
        log_pass "[sqlite/$scenario] v4.0.6 baseline: perm_items=24"
    else
        log_fail "[sqlite/$scenario] v4.0.6 baseline: perm_items=$perm_count (expected 24)"
    fi

    local has_auth=$(sqlite_helper column_exists users auth_method)
    if [ "$has_auth" = "0" ]; then
        log_pass "[sqlite/$scenario] v4.0.6 baseline: no auth_method column"
    else
        log_fail "[sqlite/$scenario] v4.0.6 baseline: auth_method already exists"
    fi

    # Apply migration
    log_info "Applying 4.1.0 migration..."
    local migration_output
    migration_output=$(docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" < "$PROJECT_DIR/sql/poweradmin-sqlite-update-to-4.1.0.sql" 2>&1) || true

    if [ -n "$migration_output" ]; then
        log_warn "Migration output: $migration_output"
    fi

    # Verify result
    verify_migration_result "sqlite" "$scenario" "sqlite_helper"

    # Check PowerDNS tables (shared DB for SQLite)
    local pdns_domains=$(sqlite_raw_query "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='domains';")
    if [ "$pdns_domains" = "1" ]; then
        log_pass "[sqlite/$scenario] PowerDNS tables intact"
    else
        log_warn "[sqlite/$scenario] PowerDNS domains table not in this database (may be separate)"
    fi

    echo ""
}

# ============================================================================
# Restore
# ============================================================================
restore_databases() {
    local engine=$1
    echo -e "${BLUE}=== Restoring $engine database ===${NC}"

    case $engine in
        mysql)
            mysql_drop_poweradmin_tables
            log_info "Loading current schema..."
            mysql_exec "$MYSQL_DATABASE" < "$PROJECT_DIR/sql/poweradmin-mysql-db-structure.sql"
            ;;
        pgsql)
            pgsql_drop_poweradmin_tables
            log_info "Loading current schema..."
            pgsql_exec < "$PROJECT_DIR/sql/poweradmin-pgsql-db-structure.sql" > /dev/null
            ;;
        sqlite)
            sqlite_drop_poweradmin_tables
            log_info "Loading current schema..."
            docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" < "$PROJECT_DIR/sql/poweradmin-sqlite-db-structure.sql" > /dev/null
            ;;
    esac

    log_pass "$engine database restored to current schema"
    echo ""
}

# ============================================================================
# Main
# ============================================================================
main() {
    local test_mysql=false
    local test_pgsql=false
    local test_sqlite=false
    local test_all=true

    while [[ $# -gt 0 ]]; do
        case $1 in
            --mysql) test_mysql=true; test_all=false; shift ;;
            --pgsql) test_pgsql=true; test_all=false; shift ;;
            --sqlite) test_sqlite=true; test_all=false; shift ;;
            *) echo "Usage: $0 [--mysql] [--pgsql] [--sqlite]"; exit 1 ;;
        esac
    done

    if [ "$test_all" = true ]; then
        test_mysql=true
        test_pgsql=true
        test_sqlite=true
    fi

    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Test 4.1.0 Migration Scripts${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""

    preflight
    extract_schemas

    # Test each engine with both scenarios
    if [ "$test_mysql" = true ]; then
        test_mysql "empty"
        test_mysql "with-data"
        restore_databases mysql
    fi

    if [ "$test_pgsql" = true ]; then
        test_pgsql "empty"
        test_pgsql "with-data"
        restore_databases pgsql
    fi

    if [ "$test_sqlite" = true ]; then
        test_sqlite "empty"
        test_sqlite "with-data"
        restore_databases sqlite
    fi

    # Import test data back
    echo -e "${BLUE}=== Restoring test data ===${NC}"
    if [ -f "$PROJECT_DIR/.devcontainer/scripts/import-test-data.sh" ]; then
        bash "$PROJECT_DIR/.devcontainer/scripts/import-test-data.sh" --clean
    else
        log_warn "import-test-data.sh not found, skipping test data restore"
    fi
    echo ""

    # Summary
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Migration Test Summary${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo -e "  ${GREEN}Passed: $PASS${NC}"
    echo -e "  ${RED}Failed: $FAIL${NC}"

    if [ $FAIL -gt 0 ]; then
        echo -e "\n${RED}Failures:${NC}"
        echo -e "$ERRORS"
        echo ""
        exit 1
    else
        echo -e "\n${GREEN}All migration tests passed!${NC}"
        echo ""
        exit 0
    fi
}

main "$@"
