#!/usr/bin/env python3
"""Identify .po entries that fail msgfmt --check; emit their msgids as JSON for LLM translation.

Usage: python3 extract_failing_entries.py <locale>
Output: /tmp/<locale>_failing.json - { "msgid": "", ... } ready for LLM to fill in translations
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def failing_lines(po_path: str):
    """Returns set of 1-based line numbers where msgfmt reports any error."""
    result = subprocess.run(
        ["msgfmt", "--check", "-o", "/dev/null", po_path],
        capture_output=True, text=True,
    )
    nums = set()
    for line in result.stderr.splitlines():
        m = re.search(rf"{re.escape(po_path)}:(\d+):", line)
        if m:
            nums.add(int(m.group(1)))
    return nums


def find_entry_around(lines, target_line):
    """Find the msgid block for the entry containing target_line (0-based bounds returned)."""
    idx = target_line - 1
    start = idx
    # Walk back to first msgid (not msgid_plural)
    while start > 0:
        if lines[start].startswith("msgid ") and not lines[start].startswith("msgid_plural"):
            break
        start -= 1
    end = idx
    while end < len(lines) - 1 and lines[end + 1].strip():
        end += 1
    return start, end


def extract_msgid(lines, msgid_start):
    m = re.match(r'^msgid\s+"(.*)"$', lines[msgid_start])
    if not m:
        return None
    parts = [m.group(1)]
    i = msgid_start + 1
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('"') and s.endswith('"'):
            parts.append(s[1:-1])
            i += 1
        else:
            break
    text = "".join(parts)
    return text.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')


def main(locale: str):
    po_path = os.path.join(ROOT, f"locale/{locale}/LC_MESSAGES/messages.po")
    err_lines = failing_lines(po_path)
    if not err_lines:
        print(f"{locale}: no failing entries")
        return

    with open(po_path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    msgids = []
    seen = set()
    for tl in sorted(err_lines):
        start, _ = find_entry_around(lines, tl)
        msgid = extract_msgid(lines, start)
        if msgid and msgid not in seen:
            seen.add(msgid)
            msgids.append(msgid)

    out = {m: "" for m in msgids}
    out_path = f"/tmp/{locale}_failing.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"{locale}: {len(msgids)} unique failing msgids -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <locale>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
