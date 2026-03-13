#!/bin/bash
# =============================================================================
# Test 4.1.x to 4.2.0 Migration Scripts
# =============================================================================
#
# Tests the three sql/poweradmin-*-update-to-4.2.0.sql migration scripts
# against a fresh 4.1.x database schema for each engine.
#
# Two scenarios per engine:
#   A) Empty 4.1.x schema (no data, just tables)
#   B) 4.1.x schema with test data (users, templates, zones)
#
# Steps per scenario:
#   1. Drop Poweradmin tables (NOT PowerDNS tables)
#   2. Load v4.1.x schema
#   3. Optionally insert test data
#   4. Verify v4.1.x state
#   5. Apply 4.2.0 migration
#   6. Verify migration result
#   7. Verify existing data preserved (scenario B)
#
# Usage:
#   ./scripts/test-migration-4.1.x-to-4.2.0.sh
#   ./scripts/test-migration-4.1.x-to-4.2.0.sh --mysql
#   ./scripts/test-migration-4.1.x-to-4.2.0.sh --pgsql
#   ./scripts/test-migration-4.1.x-to-4.2.0.sh --sqlite
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

    if git rev-parse v4.1.1 >/dev/null 2>&1; then
        log_pass "Git tag v4.1.1 exists"
    else
        log_fail "Git tag v4.1.1 not found"
        echo "Cannot proceed without v4.1.1 tag."
        exit 1
    fi

    for engine in mysql pgsql sqlite; do
        local file="$PROJECT_DIR/sql/poweradmin-${engine}-update-to-4.2.0.sql"
        if [ -f "$file" ]; then
            log_pass "Migration file exists: poweradmin-${engine}-update-to-4.2.0.sql"
        else
            log_fail "Migration file missing: poweradmin-${engine}-update-to-4.2.0.sql"
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
# Extract v4.1.1 schemas
# ============================================================================
extract_schemas() {
    echo -e "${BLUE}=== Extracting v4.1.1 schemas ===${NC}"

    for engine in mysql pgsql sqlite; do
        git show "v4.1.1:sql/poweradmin-${engine}-db-structure.sql" > "$TMPDIR/v41x-${engine}.sql" 2>/dev/null
        if [ -s "$TMPDIR/v41x-${engine}.sql" ]; then
            log_pass "Extracted v4.1.1 ${engine} schema"
        else
            log_fail "Failed to extract v4.1.1 ${engine} schema"
        fi
    done

    echo ""
}

# ============================================================================
# Common verification (works for all engines)
# ============================================================================
verify_v41x_baseline() {
    local engine=$1
    local scenario=$2
    local query_fn=$3

    log_info "Verifying v4.1.1 baseline ($scenario)..."

    # Check perm_items count (should be 27 in v4.1.1)
    local perm_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "27" ]; then
        log_pass "[$engine/$scenario] v4.1.1 baseline: perm_items=27"
    else
        log_fail "[$engine/$scenario] v4.1.1 baseline: perm_items=$perm_count (expected 27)"
    fi

    # Check perm_templ count (should be 5 in v4.1.1)
    local templ_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ;")
    if [ "$templ_count" = "5" ]; then
        log_pass "[$engine/$scenario] v4.1.1 baseline: perm_templ=5"
    else
        log_fail "[$engine/$scenario] v4.1.1 baseline: perm_templ=$templ_count (expected 5)"
    fi

    # Check that old template names exist (will be renamed by migration)
    for templ in "DNS Editor" "Read Only" "No Access"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='$templ';")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] v4.1.1 baseline: template '$templ' exists"
        else
            log_fail "[$engine/$scenario] v4.1.1 baseline: template '$templ' missing"
        fi
    done

    # Check no template_type column yet
    local has_templ_type=$($query_fn "column_exists" "perm_templ" "template_type")
    if [ "$has_templ_type" = "0" ]; then
        log_pass "[$engine/$scenario] v4.1.1 baseline: no template_type column"
    else
        log_fail "[$engine/$scenario] v4.1.1 baseline: template_type already exists"
    fi

    # Check no group tables yet
    for table in user_groups user_group_members zones_groups log_groups record_comment_links; do
        local exists=$($query_fn "table_exists" "$table")
        if [ "$exists" = "0" ]; then
            log_pass "[$engine/$scenario] v4.1.1 baseline: no $table table"
        else
            log_fail "[$engine/$scenario] v4.1.1 baseline: $table already exists"
        fi
    done

    # Check no user_enforce_mfa permission
    local has_mfa_perm=$($query_fn "query" "SELECT COUNT(*) FROM perm_items WHERE name='user_enforce_mfa';")
    if [ "$has_mfa_perm" = "0" ]; then
        log_pass "[$engine/$scenario] v4.1.1 baseline: no user_enforce_mfa permission"
    else
        log_fail "[$engine/$scenario] v4.1.1 baseline: user_enforce_mfa already exists"
    fi
}

verify_migration_result() {
    local engine=$1
    local scenario=$2
    local query_fn=$3

    log_info "Verifying migration result ($scenario)..."

    # --- New tables ---
    for table in user_groups user_group_members zones_groups log_groups record_comment_links; do
        local exists=$($query_fn "table_exists" "$table")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] New table: $table"
        else
            log_fail "[$engine/$scenario] Missing table: $table"
        fi
    done

    # --- Template renames ---
    # Old names should be gone
    for old_templ in "DNS Editor" "Read Only" "No Access"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='$old_templ';")
        if [ "$exists" = "0" ]; then
            log_pass "[$engine/$scenario] Old template renamed: $old_templ"
        else
            log_fail "[$engine/$scenario] Old template still exists: $old_templ"
        fi
    done

    # New names should exist (user type)
    for new_templ in "Editor" "Viewer" "Guest"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='$new_templ';")
        if [ "$exists" -ge "1" ]; then
            log_pass "[$engine/$scenario] Renamed template exists: $new_templ"
        else
            log_fail "[$engine/$scenario] Renamed template missing: $new_templ"
        fi
    done

    # --- template_type column ---
    local has_templ_type=$($query_fn "column_exists" "perm_templ" "template_type")
    if [ "$has_templ_type" = "1" ]; then
        log_pass "[$engine/$scenario] perm_templ.template_type column added"
    else
        log_fail "[$engine/$scenario] perm_templ.template_type column missing"
    fi

    # --- Permission count (27 + user_enforce_mfa = 28) ---
    local perm_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_items;")
    if [ "$perm_count" = "28" ]; then
        log_pass "[$engine/$scenario] perm_items count = 28"
    else
        log_fail "[$engine/$scenario] perm_items count = $perm_count (expected 28)"
    fi

    # --- user_enforce_mfa permission ---
    local has_mfa=$($query_fn "query" "SELECT COUNT(*) FROM perm_items WHERE name='user_enforce_mfa';")
    if [ "$has_mfa" = "1" ]; then
        log_pass "[$engine/$scenario] Permission: user_enforce_mfa"
    else
        log_fail "[$engine/$scenario] Missing permission: user_enforce_mfa"
    fi

    # --- Template count (5 user + 5 group = 10) ---
    local templ_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ;")
    if [ "$templ_count" = "10" ]; then
        log_pass "[$engine/$scenario] perm_templ count = 10"
    else
        log_fail "[$engine/$scenario] perm_templ count = $templ_count (expected 10)"
    fi

    # --- Group-type templates ---
    for group_templ in "Administrators" "Zone Managers" "Editors" "Viewers" "Guests"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='$group_templ' AND template_type='group';")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] Group template: $group_templ"
        else
            log_fail "[$engine/$scenario] Missing group template: $group_templ"
        fi
    done

    # --- Default user groups ---
    local group_count=$($query_fn "query" "SELECT COUNT(*) FROM user_groups;")
    if [ "$group_count" = "5" ]; then
        log_pass "[$engine/$scenario] user_groups count = 5"
    else
        log_fail "[$engine/$scenario] user_groups count = $group_count (expected 5)"
    fi

    for group_name in "Administrators" "Zone Managers" "Editors" "Viewers" "Guests"; do
        local exists=$($query_fn "query" "SELECT COUNT(*) FROM user_groups WHERE name='$group_name';")
        if [ "$exists" = "1" ]; then
            log_pass "[$engine/$scenario] Default group: $group_name"
        else
            log_fail "[$engine/$scenario] Missing default group: $group_name"
        fi
    done

    # --- Group template permissions ---
    # Administrators group template should have user_is_ueberuser permission
    local admin_perm=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ_items pti JOIN perm_templ pt ON pti.templ_id=pt.id JOIN perm_items pi ON pti.perm_id=pi.id WHERE pt.name='Administrators' AND pt.template_type='group' AND pi.name='user_is_ueberuser';")
    if [ "$admin_perm" = "1" ]; then
        log_pass "[$engine/$scenario] Administrators group has user_is_ueberuser"
    else
        log_fail "[$engine/$scenario] Administrators group missing user_is_ueberuser"
    fi

    # Zone Managers group template should have multiple permissions
    local zm_perm_count=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ_items pti JOIN perm_templ pt ON pti.templ_id=pt.id WHERE pt.name='Zone Managers' AND pt.template_type='group';")
    if [ "$zm_perm_count" = "11" ]; then
        log_pass "[$engine/$scenario] Zone Managers group has 11 permissions"
    else
        log_fail "[$engine/$scenario] Zone Managers group has $zm_perm_count permissions (expected 11)"
    fi

    # --- Data preservation (scenario B only) ---
    if [ "$scenario" = "with-data" ]; then
        local user_count=$($query_fn "query" "SELECT COUNT(*) FROM users;")
        if [ "$user_count" -ge "1" ]; then
            log_pass "[$engine/$scenario] Users preserved ($user_count)"
        else
            log_fail "[$engine/$scenario] Users lost after migration"
        fi

        local auth_method=$($query_fn "query" "SELECT auth_method FROM users WHERE username='admin';")
        if [ "$auth_method" = "sql" ]; then
            log_pass "[$engine/$scenario] Existing user auth_method = 'sql'"
        else
            log_fail "[$engine/$scenario] Existing user auth_method = '$auth_method' (expected 'sql')"
        fi

        # Check that Administrator template is preserved (user type)
        local admin_templ=$($query_fn "query" "SELECT COUNT(*) FROM perm_templ WHERE name='Administrator' AND template_type='user';")
        if [ "$admin_templ" = "1" ]; then
            log_pass "[$engine/$scenario] Administrator user template preserved"
        else
            log_fail "[$engine/$scenario] Administrator user template lost"
        fi

        # Check admin user's template assignment still valid
        local admin_perm_templ=$($query_fn "query" "SELECT perm_templ FROM users WHERE username='admin';")
        if [ "$admin_perm_templ" = "1" ]; then
            log_pass "[$engine/$scenario] Admin user template assignment preserved"
        else
            log_fail "[$engine/$scenario] Admin user template assignment = '$admin_perm_templ' (expected 1)"
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
    oidc_user_links, saml_user_links, username_recovery_requests,
    user_groups, user_group_members, zones_groups, log_groups, record_comment_links;
SET FOREIGN_KEY_CHECKS = 1;
EOSQL
}

mysql_insert_test_data() {
    mysql_exec "$MYSQL_DATABASE" <<'EOSQL'
INSERT INTO `users` (`id`, `username`, `password`, `fullname`, `email`, `description`, `perm_templ`, `active`, `use_ldap`, `auth_method`)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0, 'sql');
EOSQL
}

test_mysql() {
    local scenario=$1

    echo -e "${BLUE}=== MySQL/MariaDB Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables..."
    mysql_drop_poweradmin_tables

    log_info "Loading v4.1.1 schema..."
    if mysql_exec "$MYSQL_DATABASE" < "$TMPDIR/v41x-mysql.sql"; then
        log_pass "[mysql/$scenario] v4.1.1 schema loaded"
    else
        log_fail "[mysql/$scenario] Failed to load v4.1.1 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        mysql_insert_test_data
        local user_count=$(mysql_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[mysql/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.1.1 state
    verify_v41x_baseline "mysql" "$scenario" "mysql_helper"

    # Apply migration
    log_info "Applying 4.2.0 migration..."
    local migration_output
    migration_output=$(mysql_exec "$MYSQL_DATABASE" < "$PROJECT_DIR/sql/poweradmin-mysql-update-to-4.2.0.sql" 2>&1) || true

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
    oidc_user_links, saml_user_links, username_recovery_requests,
    user_groups, user_group_members, zones_groups, log_groups, record_comment_links CASCADE;

DROP SEQUENCE IF EXISTS api_keys_id_seq, log_users_id_seq1, log_zones_id_seq1,
    login_attempts_id_seq, perm_items_id_seq, perm_templ_id_seq, perm_templ_items_id_seq,
    records_zone_templ_id_seq, user_mfa_id_seq, users_id_seq, zone_templ_id_seq,
    zone_templ_records_id_seq, zones_id_seq,
    log_groups_id_seq, log_groups_id_seq1, user_groups_id_seq, user_group_members_id_seq, zones_groups_id_seq CASCADE;
EOSQL
}

pgsql_insert_test_data() {
    pgsql_exec <<'EOSQL'
INSERT INTO users (id, username, password, fullname, email, description, perm_templ, active, use_ldap, auth_method)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0, 'sql');
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));
EOSQL
}

test_pgsql() {
    local scenario=$1

    echo -e "${BLUE}=== PostgreSQL Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables and sequences..."
    pgsql_drop_poweradmin_tables

    log_info "Loading v4.1.1 schema..."
    if pgsql_exec < "$TMPDIR/v41x-pgsql.sql" > /dev/null; then
        log_pass "[pgsql/$scenario] v4.1.1 schema loaded"
    else
        log_fail "[pgsql/$scenario] Failed to load v4.1.1 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        pgsql_insert_test_data
        local user_count=$(pgsql_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[pgsql/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.1.1 state
    verify_v41x_baseline "pgsql" "$scenario" "pgsql_helper"

    # Apply migration
    log_info "Applying 4.2.0 migration..."
    local migration_output
    migration_output=$(pgsql_exec < "$PROJECT_DIR/sql/poweradmin-pgsql-update-to-4.2.0.sql" 2>&1) || true

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
DROP TABLE IF EXISTS user_group_members;
DROP TABLE IF EXISTS zones_groups;
DROP TABLE IF EXISTS user_groups;
DROP TABLE IF EXISTS log_groups;
DROP TABLE IF EXISTS record_comment_links;
EOSQL
}

sqlite_insert_test_data() {
    sqlite_exec <<'EOSQL'
INSERT INTO users (id, username, password, fullname, email, description, perm_templ, active, use_ldap, auth_method)
VALUES (1, 'admin', '$2y$10$test_hash_here', 'Administrator', 'admin@example.com', 'Test admin', 1, 1, 0, 'sql');
EOSQL
}

test_sqlite() {
    local scenario=$1

    echo -e "${BLUE}=== SQLite Migration Test ($scenario) ===${NC}"

    log_info "Dropping Poweradmin tables..."
    sqlite_drop_poweradmin_tables

    log_info "Loading v4.1.1 schema..."
    if docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" < "$TMPDIR/v41x-sqlite.sql" > /dev/null 2>&1; then
        log_pass "[sqlite/$scenario] v4.1.1 schema loaded"
    else
        log_fail "[sqlite/$scenario] Failed to load v4.1.1 schema"
        return 1
    fi

    if [ "$scenario" = "with-data" ]; then
        log_info "Inserting test data..."
        sqlite_insert_test_data
        local user_count=$(sqlite_raw_query "SELECT COUNT(*) FROM users;")
        log_pass "[sqlite/$scenario] Test data inserted ($user_count users)"
    fi

    # Verify v4.1.1 state
    verify_v41x_baseline "sqlite" "$scenario" "sqlite_helper"

    # Apply migration
    log_info "Applying 4.2.0 migration..."
    local migration_output
    migration_output=$(docker exec -i "$SQLITE_CONTAINER" sqlite3 "$SQLITE_DB_PATH" < "$PROJECT_DIR/sql/poweradmin-sqlite-update-to-4.2.0.sql" 2>&1) || true

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
    echo -e "${BLUE}  Test 4.1.x to 4.2.0 Migration Scripts${NC}"
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
