#!/usr/bin/env python3
"""Fallback step: any entry that fails msgfmt --check gets its English msgid copied to msgstr.

Used after fix_sentinel_leaks.py for the rare entries (~3-5% of file) where MT corruption
is unrecoverable. English fallback keeps the .po valid for shipping; translator can refine
those specific entries later.

Usage: python3 fallback_to_english.py <locale>
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def msgfmt_errors(po_path: str):
    """Return set of line numbers where msgfmt reports format-spec errors."""
    result = subprocess.run(
        ["msgfmt", "--check", "-o", "/dev/null", po_path],
        capture_output=True, text=True,
    )
    line_nums = set()
    for line in result.stderr.splitlines():
        # msgfmt also emits header hygiene warnings; those are not broken entries
        if "warning:" in line:
            continue
        m = re.search(rf"{re.escape(po_path)}:(\d+):", line)
        if m:
            line_nums.add(int(m.group(1)))
    return line_nums


def nplurals_for(entries) -> int:
    """Read nplurals from the Plural-Forms header. Defaults to 2 when absent."""
    for entry in entries:
        if entry.is_header:
            m = re.search(r'Plural-Forms:\s*nplurals=(\d+)', entry.msgstr)
            if m:
                return int(m.group(1))
            break
    return 2


def fix_po(po_path: str):
    error_lines = msgfmt_errors(po_path)
    if not error_lines:
        print(f"No errors in {po_path}")
        return

    print(f"Found {len(error_lines)} failing entries in {po_path}; falling back to English msgid")

    entries = poutil.parse(po_path)
    spans = poutil.line_spans(entries)
    nplurals = nplurals_for(entries)

    fixed = 0
    seen = set()
    for lineno in sorted(error_lines):
        entry = poutil.find_by_line(entries, lineno, spans)
        if entry is None or entry.obsolete or not entry.msgid or entry.is_header:
            continue
        if id(entry) in seen:
            continue
        seen.add(id(entry))

        if entry.msgid_plural:
            # nplurals=1 locales (Thai, Malay) carry a single form
            for n in range(nplurals):
                entry.set_plural(n, entry.msgid if n == 0 or nplurals == 1 else entry.msgid_plural)
        else:
            entry.msgstr = entry.msgid
        fixed += 1

    if fixed:
        poutil.backup(po_path)
        poutil.write(po_path, entries)
    print(f"Replaced {fixed} entries with English msgid in {po_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <locale>", file=sys.stderr)
        sys.exit(1)
    locale = sys.argv[1]
    po_path = os.path.join(ROOT, f"locale/{locale}/LC_MESSAGES/messages.po")
    if not os.path.exists(po_path):
        print(f"Not found: {po_path}", file=sys.stderr)
        sys.exit(1)
    fix_po(po_path)
