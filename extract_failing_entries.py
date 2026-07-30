#!/usr/bin/env python3
"""Identify .po entries that fail msgfmt --check; emit their msgids as JSON for LLM translation.

Usage: python3 extract_failing_entries.py <locale>
Output: <tmpdir>/<locale>_failing.json - { "msgid": "", ... } ready for LLM to fill in translations
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

ROOT = poutil.ROOT


def failing_lines(po_path: str):
    """1-based line numbers where msgfmt reports a real error (warnings excluded)."""
    result = subprocess.run(
        ["msgfmt", "--check", "-o", "/dev/null", po_path],
        capture_output=True, text=True,
    )
    nums = set()
    for line in result.stderr.splitlines():
        # msgfmt also emits header hygiene warnings; those are not broken entries
        if "warning:" in line:
            continue
        m = re.search(rf"{re.escape(po_path)}:(\d+):", line)
        if m:
            nums.add(int(m.group(1)))
    return nums


def main(locale: str):
    po_path = poutil.po_path(locale)
    err_lines = failing_lines(po_path)
    if not err_lines:
        print(f"{locale}: no failing entries")
        return

    entries = poutil.parse(po_path)
    spans = poutil.line_spans(entries)

    msgids = []
    seen = set()
    for lineno in sorted(err_lines):
        entry = poutil.find_by_line(entries, lineno, spans)
        if entry is None or entry.is_header or entry.obsolete or not entry.msgid:
            continue
        if entry.msgid in seen:
            continue
        seen.add(entry.msgid)
        msgids.append(entry.msgid)

    if not msgids:
        print(f"{locale}: no failing entries")
        return

    out_path = os.path.join(tempfile.gettempdir(), f"{locale}_failing.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({m: "" for m in msgids}, f, ensure_ascii=False, indent=2)
    print(f"{locale}: {len(msgids)} unique failing msgids -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <locale>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
