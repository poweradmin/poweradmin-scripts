#!/usr/bin/env python3
"""Roll the copyright range forward a year across the tree.

Usage:
  python3 scripts/update_copyright.py [--dry-run] [--year=YYYY]

Rewrites `2010-<previous year> Poweradmin Development Team` to end in the current
year. Only that exact pattern is touched, so a file with any other copyright line
is left alone.

Note the project convention is to bump the year only in files you actually modify;
this bulk pass is for the year rollover itself.
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

# Reading every dependency file would dominate the runtime and none of them
# carry our copyright line.
SKIP_DIRS = {'.git', 'vendor', 'node_modules', '.playwright-mcp', 'test-results',
             'playwright-report', '__pycache__', '.idea', '.vscode'}
SKIP_SUFFIXES = ('.mo', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2',
                 '.ttf', '.eot', '.zip', '.gz', '.phar', '.db', '.sqlite')


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    year_arg = next((a.split('=', 1)[1] for a in args if a.startswith('--year=')), None)

    current = int(year_arg) if year_arg else datetime.now().year
    previous = current - 1
    pattern = re.compile(rf'2010-{previous}(\s+Poweradmin Development Team)')
    replacement = rf'2010-{current}\1'

    updated = []
    for dirpath, dirnames, filenames in os.walk(poutil.ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(SKIP_SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding='utf-8') as fh:
                    content = fh.read()
            except (UnicodeDecodeError, OSError):
                continue

            if not pattern.search(content):
                continue
            rel = os.path.relpath(path, poutil.ROOT)
            updated.append(rel)
            print(f'Updating copyright in <{rel}>')
            if not dry_run:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(pattern.sub(replacement, content))

    verb = 'would update' if dry_run else 'updated'
    print(f'\n2010-{previous} -> 2010-{current}: {verb} {len(updated)} file(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
