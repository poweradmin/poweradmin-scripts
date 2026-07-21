#!/usr/bin/env bash
#
# e2e-sweep.sh - one-command orchestrator for full Playwright e2e sweeps.
#
# Runs one Playwright sweep per database instance in parallel, each against its
# own isolated container, and prints a merged pass/fail summary. Every long
# command is wrapped in caffeinate so macOS does not sleep mid-sweep.
#
# Copyright 2010-2026 Poweradmin Development Team

set -euo pipefail

# Resolve the main repo root from this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if git -C "$PROJECT_ROOT" rev-parse --show-toplevel >/dev/null 2>&1; then
    PROJECT_ROOT="$(git -C "$PROJECT_ROOT" rev-parse --show-toplevel)"
fi
cd "$PROJECT_ROOT"

# Instance topology: label -> port. Regular instances use direct SQL mode.
# Kept as case lookups so the script runs on macOS stock bash 3.2 (no assoc arrays).
sql_port() {
    case "$1" in
        mysql) echo 8080 ;; pgsql) echo 8081 ;; sqlite) echo 8082 ;; *) echo "" ;;
    esac
}
api_port() {
    case "$1" in
        mysql) echo 8083 ;; pgsql) echo 8084 ;; sqlite) echo 8085 ;; *) echo "" ;;
    esac
}
SUBFOLDER_PORT=8086

# Defaults (overridable via flags).
DBS="mysql,pgsql,sqlite"
RUN_API=0
RUN_SUBFOLDER=0
WORKERS=2
WORKERS_SET=0
FOLDERS_OVERRIDE=""
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: ./scripts/e2e-sweep.sh [options]

  --dbs a,b,c     Databases to sweep: mysql,pgsql,sqlite (default: all three)
  --api           Also sweep the API-backend instances (8083-8085, develop only)
  --subfolder     Also sweep the subfolder instance (8086)
  --workers N     Playwright workers per instance (default: 2; use 1 for sqlite)
  --folders "a b" Test folders to run on regular instances
                  (default: every playwright/tests/* folder except subfolder)
  --dry-run       Print the execution plan and exit without side effects
  -h, --help      Show this help
EOF
}

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dbs)        DBS="$2"; shift 2 ;;
        --api)        RUN_API=1; shift ;;
        --subfolder)  RUN_SUBFOLDER=1; shift ;;
        --workers)    WORKERS="$2"; WORKERS_SET=1; shift 2 ;;
        --folders)    FOLDERS_OVERRIDE="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if ! [[ "$WORKERS" =~ ^[0-9]+$ ]] || [[ "$WORKERS" -lt 1 ]]; then
    echo "Error: --workers must be a positive integer" >&2
    exit 2
fi

# --- Resolve the folder list for regular instances ---
declare -a REGULAR_FOLDERS=()
if [[ -n "$FOLDERS_OVERRIDE" ]]; then
    for f in $FOLDERS_OVERRIDE; do
        if [[ "$f" == */* ]]; then
            REGULAR_FOLDERS+=("$f")
        else
            REGULAR_FOLDERS+=("playwright/tests/$f")
        fi
    done
else
    for d in playwright/tests/*/; do
        name="$(basename "$d")"
        [[ "$name" == "subfolder" ]] && continue
        REGULAR_FOLDERS+=("playwright/tests/$name")
    done
fi

# --- Build the instance plan: parallel arrays of label / port / kind ---
declare -a INST_LABEL=() INST_PORT=() INST_KIND=()
IFS=',' read -r -a SELECTED_DBS <<< "$DBS"
for db in "${SELECTED_DBS[@]}"; do
    db="$(echo "$db" | tr -d '[:space:]')"
    [[ -z "$db" ]] && continue
    sp="$(sql_port "$db")"
    if [[ -z "$sp" ]]; then
        echo "Error: unknown database '$db' (expected mysql, pgsql or sqlite)" >&2
        exit 2
    fi
    INST_LABEL+=("$db"); INST_PORT+=("$sp"); INST_KIND+=("sql")
    if [[ "$RUN_API" -eq 1 ]]; then
        INST_LABEL+=("$db-api"); INST_PORT+=("$(api_port "$db")"); INST_KIND+=("sql")
    fi
done
if [[ "$RUN_SUBFOLDER" -eq 1 ]]; then
    INST_LABEL+=("subfolder"); INST_PORT+=("$SUBFOLDER_PORT"); INST_KIND+=("subfolder")
fi

if [[ ${#INST_PORT[@]} -eq 0 ]]; then
    echo "Error: no instances selected" >&2
    exit 2
fi

# Populate the global FARGS array with folder args for a given instance kind.
FARGS=()
folders_for() {
    if [[ "$1" == "subfolder" ]]; then
        FARGS=("playwright/tests/subfolder")
    else
        FARGS=("${REGULAR_FOLDERS[@]}")
    fi
}

LOG_ROOT="$PROJECT_ROOT/playwright-sweep-logs"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$LOG_ROOT/$TIMESTAMP"

# --- Print the plan ---
print_plan() {
    echo "Poweradmin e2e sweep plan"
    echo "  repo root : $PROJECT_ROOT"
    echo "  workers   : $WORKERS per instance"
    echo "  log dir   : $LOG_DIR"
    echo "  instances :"
    for i in "${!INST_PORT[@]}"; do
        folders_for "${INST_KIND[$i]}"
        printf '    - %-12s port %s  (%s test folder(s))\n' \
            "${INST_LABEL[$i]}" "${INST_PORT[$i]}" "${#FARGS[@]}"
    done
    echo "  regular test folders:"
    printf '    %s\n' "${REGULAR_FOLDERS[@]}"
}

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "=== DRY RUN (no side effects) ==="
    print_plan
    echo
    echo "Would, in order:"
    echo "  1. Preflight GET http://localhost:<port>/login (200 expected) for each instance"
    echo "  2. .devcontainer/scripts/import-test-data.sh --clean   (reset DBs once)"
    echo "  3. ./scripts/toggle_install.sh                          (install -> install.old)"
    echo "  4. Launch parallel sweeps, one per instance, e.g.:"
    for i in "${!INST_PORT[@]}"; do
        folders_for "${INST_KIND[$i]}"
        echo "       caffeinate -i -s env BASE_URL=http://localhost:${INST_PORT[$i]} \\"
        echo "         npx playwright test ${FARGS[*]} --workers=$WORKERS \\"
        echo "         > $LOG_DIR/sweep-${INST_PORT[$i]}.log 2>&1"
    done
    echo "  5. Wait for all jobs, parse logs, print merged summary"
    echo "  6. ./scripts/toggle_install.sh                          (install.old -> install, always)"
    exit 0
fi

# --- Install toggle helpers (state-aware; toggle only when needed) ---
INSTALL_TOGGLED=0

install_off() {
    if [[ -d "$PROJECT_ROOT/install" ]]; then
        echo ">> Disabling installer (install -> install.old)"
        ./scripts/toggle_install.sh
        INSTALL_TOGGLED=1
    fi
}

restore_install() {
    if [[ "$INSTALL_TOGGLED" -eq 1 && -d "$PROJECT_ROOT/install.old" && ! -d "$PROJECT_ROOT/install" ]]; then
        echo ">> Restoring installer (install.old -> install)"
        ./scripts/toggle_install.sh || true
    fi
}
trap restore_install EXIT

# --- Preflight: every selected instance must answer 200 on /login ---
echo ">> Preflight: checking instances are up"
declare -a DEAD=()
for i in "${!INST_PORT[@]}"; do
    port="${INST_PORT[$i]}"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$port/login" || true)"
    if [[ "$code" == "200" ]]; then
        printf '   ok   %-12s port %s\n' "${INST_LABEL[$i]}" "$port"
    else
        printf '   DEAD %-12s port %s (HTTP %s)\n' "${INST_LABEL[$i]}" "$port" "${code:-none}"
        DEAD+=("${INST_LABEL[$i]} ($port)")
    fi
done
if [[ ${#DEAD[@]} -gt 0 ]]; then
    echo "Error: the following instances are not answering on /login:" >&2
    printf '  - %s\n' "${DEAD[@]}" >&2
    exit 1
fi

# --- Reset DBs once and disable the installer ---
mkdir -p "$LOG_DIR"
echo ">> Resetting databases (import-test-data.sh --clean)"
caffeinate -i -s .devcontainer/scripts/import-test-data.sh --clean
install_off

# --- Launch one sweep per instance in parallel ---
run_instance() {
    local label="$1" port="$2" kind="$3" logfile="$4"
    folders_for "$kind"
    # SQLite is single-writer: measured residual lock timeouts at workers=2,
    # so its instances default to 1 unless --workers was given explicitly
    local workers="$WORKERS"
    case "$label" in
        sqlite*) [[ "$WORKERS_SET" -eq 0 ]] && workers=1 ;;
    esac
    local start end rc
    start="$(date +%s)"
    set +e
    caffeinate -i -s env BASE_URL="http://localhost:$port" \
        npx playwright test "${FARGS[@]}" --workers="$workers" > "$logfile" 2>&1
    rc=$?
    set -e
    end="$(date +%s)"
    echo "$rc" > "$logfile.rc"
    echo "$((end - start))" > "$logfile.dur"
}

echo ">> Launching ${#INST_PORT[@]} parallel sweep(s); logs in $LOG_DIR"
declare -a PIDS=() LOGS=()
for i in "${!INST_PORT[@]}"; do
    logfile="$LOG_DIR/sweep-${INST_PORT[$i]}.log"
    LOGS+=("$logfile")
    run_instance "${INST_LABEL[$i]}" "${INST_PORT[$i]}" "${INST_KIND[$i]}" "$logfile" &
    PIDS+=("$!")
    printf '   started %-12s port %s -> %s\n' \
        "${INST_LABEL[$i]}" "${INST_PORT[$i]}" "$logfile"
done

# --- Wait for all sweeps ---
for pid in "${PIDS[@]}"; do
    wait "$pid" || true
done

# --- Parse each log and build the summary ---
strip_ansi() { sed $'s/\x1b\\[[0-9;]*[a-zA-Z]//g'; }

extract_count() {
    # $1 = keyword (passed|failed|skipped|flaky), $2 = text
    echo "$2" | grep -oE "[0-9]+ $1" | grep -oE '^[0-9]+' | tail -1
}

overall_fail=0
printf '\n%-14s %-6s %8s %8s %8s %8s %10s %s\n' \
    "INSTANCE" "PORT" "PASSED" "FAILED" "SKIPPED" "FLAKY" "DURATION" "RESULT"
printf '%s\n' "--------------------------------------------------------------------------------------"
for i in "${!INST_PORT[@]}"; do
    logfile="$LOG_DIR/sweep-${INST_PORT[$i]}.log"
    rc="$(cat "$logfile.rc" 2>/dev/null || echo 1)"
    dur="$(cat "$logfile.dur" 2>/dev/null || echo 0)"
    # Look at the tail where Playwright prints its run totals.
    tail_txt="$(tail -n 40 "$logfile" 2>/dev/null | strip_ansi)"
    passed="$(extract_count passed "$tail_txt")";  passed="${passed:-0}"
    failed="$(extract_count failed "$tail_txt")";  failed="${failed:-0}"
    skipped="$(extract_count skipped "$tail_txt")"; skipped="${skipped:-0}"
    flaky="$(extract_count flaky "$tail_txt")";    flaky="${flaky:-0}"

    if [[ "$rc" -eq 0 && "$failed" -eq 0 ]]; then
        result="PASS"
    else
        result="FAIL"
        overall_fail=1
    fi
    printf '%-14s %-6s %8s %8s %8s %8s %9dm%02ds %s\n' \
        "${INST_LABEL[$i]}" "${INST_PORT[$i]}" \
        "$passed" "$failed" "$skipped" "$flaky" \
        $((dur / 60)) $((dur % 60)) "$result"
done
printf '%s\n' "--------------------------------------------------------------------------------------"
echo "Logs: $LOG_DIR"

if [[ "$overall_fail" -eq 0 ]]; then
    echo "RESULT: PASS"
    exit 0
else
    echo "RESULT: FAIL"
    exit 1
fi
