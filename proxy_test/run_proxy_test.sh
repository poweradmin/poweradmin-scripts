#!/usr/bin/env bash
# Automated localhost integration test for issue #1188 fixes:
#   - HTTP_PROXY routes outbound requests through the configured proxy.
#   - NO_PROXY exact-host entries bypass the proxy.
#   - NO_PROXY CIDR entries (the new behavior) bypass the proxy.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROXY_PORT=18888
TARGET_PORT=19999
PROXY_LOG=/tmp/proxy.log
TARGET_LOG=/tmp/target.log
PROXY_PID=
TARGET_PID=

cleanup() {
    [[ -n "$PROXY_PID"  ]] && kill "$PROXY_PID"  2>/dev/null
    [[ -n "$TARGET_PID" ]] && kill "$TARGET_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT

start_stubs() {
    : > "$PROXY_LOG"
    : > "$TARGET_LOG"
    PROXY_PORT="$PROXY_PORT"  PROXY_LOG="$PROXY_LOG"  python3 "$SCRIPT_DIR/proxy_stub.py"  >/tmp/proxy_stub.out  2>&1 &
    PROXY_PID=$!
    TARGET_PORT="$TARGET_PORT" TARGET_LOG="$TARGET_LOG" python3 "$SCRIPT_DIR/target_stub.py" >/tmp/target_stub.out 2>&1 &
    TARGET_PID=$!
    # Wait for both ports to accept connections.
    for _ in $(seq 1 50); do
        if (echo > "/dev/tcp/127.0.0.1/$PROXY_PORT") 2>/dev/null \
           && (echo > "/dev/tcp/127.0.0.1/$TARGET_PORT") 2>/dev/null; then
            return 0
        fi
        sleep 0.1
    done
    echo "stubs failed to bind ports" >&2
    return 1
}

reset_logs() {
    : > "$PROXY_LOG"
    : > "$TARGET_LOG"
}

run_case() {
    local label="$1"; shift
    local url="$1"; shift
    # Remaining args are KEY=VALUE env pairs.

    reset_logs
    local out
    out=$(env -i PATH="$PATH" "$@" php "$SCRIPT_DIR/proxy_harness.php" "$url" 2>&1)
    local body proxy_lines target_lines
    body=$(printf '%s\n' "$out" | awk -F: '/^BODY:/{ $1=""; sub(/^ +/,""); print }')
    proxy_lines=$(wc -l < "$PROXY_LOG"  | tr -d ' ')
    target_lines=$(wc -l < "$TARGET_LOG" | tr -d ' ')

    printf '== %s ==\n' "$label"
    printf 'env: %s\n' "$*"
    printf 'url: %s\n' "$url"
    printf 'body: %s\n' "$body"
    printf 'proxy_log_lines=%s target_log_lines=%s\n' "$proxy_lines" "$target_lines"
    printf '\n'

    # Echo expectations as env so the caller can grep.
    printf '%s\n' "$body|$proxy_lines|$target_lines"
}

assert_eq() {
    local got="$1" want="$2" label="$3"
    if [[ "$got" == "$want" ]]; then
        printf '  PASS %s (got %s)\n' "$label" "$got"
        return 0
    fi
    printf '  FAIL %s: want %s, got %s\n' "$label" "$want" "$got"
    return 1
}

main() {
    start_stubs || exit 1
    local fail=0

    # Case 1: HTTP_PROXY set, no NO_PROXY -> request must hit the proxy.
    local result body proxy target
    result=$(run_case "1. HTTP_PROXY routes through proxy" \
        "http://127.0.0.1:$TARGET_PORT/case1" \
        "http_proxy=http://127.0.0.1:$PROXY_PORT" | tail -n1)
    IFS='|' read -r body proxy target <<<"$result"
    assert_eq "$body"   "FROM_PROXY!"  "case1.body"   || fail=1
    assert_eq "$proxy"  "1"            "case1.proxy"  || fail=1
    assert_eq "$target" "0"            "case1.target" || fail=1

    # Case 2: NO_PROXY=127.0.0.1 -> request must bypass proxy.
    result=$(run_case "2. NO_PROXY exact host bypasses proxy" \
        "http://127.0.0.1:$TARGET_PORT/case2" \
        "http_proxy=http://127.0.0.1:$PROXY_PORT" \
        "NO_PROXY=127.0.0.1" | tail -n1)
    IFS='|' read -r body proxy target <<<"$result"
    assert_eq "$body"   "FROM_TARGET!" "case2.body"   || fail=1
    assert_eq "$proxy"  "0"            "case2.proxy"  || fail=1
    assert_eq "$target" "1"            "case2.target" || fail=1

    # Case 3: NO_PROXY=127.0.0.0/8 -> CIDR matching must bypass proxy.
    result=$(run_case "3. NO_PROXY CIDR bypasses proxy (new in ad9509e07)" \
        "http://127.0.0.1:$TARGET_PORT/case3" \
        "http_proxy=http://127.0.0.1:$PROXY_PORT" \
        "NO_PROXY=127.0.0.0/8" | tail -n1)
    IFS='|' read -r body proxy target <<<"$result"
    assert_eq "$body"   "FROM_TARGET!" "case3.body"   || fail=1
    assert_eq "$proxy"  "0"            "case3.proxy"  || fail=1
    assert_eq "$target" "1"            "case3.target" || fail=1

    # Case 4: NO_PROXY=127.0.0.1:9999 with non-matching port -> proxy used.
    result=$(run_case "4. NO_PROXY host:port mismatch keeps proxying" \
        "http://127.0.0.1:$TARGET_PORT/case4" \
        "http_proxy=http://127.0.0.1:$PROXY_PORT" \
        "NO_PROXY=127.0.0.1:9999" | tail -n1)
    IFS='|' read -r body proxy target <<<"$result"
    assert_eq "$body"   "FROM_PROXY!"  "case4.body"   || fail=1
    assert_eq "$proxy"  "1"            "case4.proxy"  || fail=1
    assert_eq "$target" "0"            "case4.target" || fail=1

    if (( fail == 0 )); then
        printf '\nALL TESTS PASSED\n'
        return 0
    fi
    printf '\nFAILURES PRESENT\n'
    return 1
}

main "$@"
