#!/bin/bash
#
# Run `composer format:all` (phpcbf over every source path) and put the committed
# production vendor/ back afterwards, whatever the outcome.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# vendor/ is committed in its no-dev form; dev installs dirty it and add untracked
# packages, some as nested git clones, hence the double -f
restore_vendor() {
    git checkout -- vendor/ && git clean -ffdq vendor/
}
trap restore_vendor EXIT

composer install --quiet

# PHP_CodeSniffer 4.x exit codes are a bitmask (Util/ExitCode.php): 1 = fixable issues
# remain, 2 = non-fixable issues remain, 4 = a file failed to fix, 16 = process error.
set +e
composer format:all
exit_code=$?
set -e

if (( exit_code & 16 )); then
    echo "phpcbf encountered a process error (exit code $exit_code)" >&2
    exit 1
fi
if (( exit_code & 4 )); then
    echo "phpcbf failed to fix some files (exit code $exit_code)" >&2
    exit 1
fi
if (( exit_code & 2 )); then
    echo "phpcbf: non-fixable issues remain (exit code $exit_code); run composer check:all and fix them by hand"
fi
