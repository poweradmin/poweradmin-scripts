#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "Error: Failed to change to project root directory: $PROJECT_ROOT"; exit 1; }

TARGET="data/public_suffix_list.dat"
tmp_file=$(mktemp)
trap 'rm -f "$tmp_file"' EXIT

count_entries() {
    grep -cEv '^[[:space:]]*(//|$)' "$1" || true
}

echo "Downloading public suffix list..."
curl -fsSL https://publicsuffix.org/list/public_suffix_list.dat -o "$tmp_file"

if ! grep -q '^// ===BEGIN ICANN DOMAINS===' "$tmp_file"; then
    echo "Error: downloaded file lacks the ICANN DOMAINS marker; keeping current $TARGET" >&2
    exit 1
fi

new_count=$(count_entries "$tmp_file")
if [[ -f "$TARGET" ]]; then
    old_count=$(count_entries "$TARGET")
    # Refuse a truncated download (floor: 80% of current entries)
    if (( new_count * 100 < old_count * 80 )); then
        echo "Error: downloaded list has $new_count entries, current has $old_count; keeping current $TARGET" >&2
        exit 1
    fi
fi

mv "$tmp_file" "$TARGET"
chmod 644 "$TARGET"

if git diff --quiet -- "$TARGET"; then
    echo "No changes in $TARGET"
    exit 0
fi

git add "$TARGET"
git commit -m "chore: update public_suffix_list.dat" "$TARGET"
