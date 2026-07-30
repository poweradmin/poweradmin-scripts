#!/usr/bin/env python3
"""Repair malformed sentinel leaks in a .po file by mapping them back to msgid placeholders.

Some MT models (notably Argos Irish) mangle our ZZ<n>ZZ sentinels, leaving fragments like
ZZ0Z, Z1ZZZ, ZZ2Z. This script extracts ordered placeholders from each msgid (printf
specifiers and HTML tags) and substitutes them back wherever the corresponding sentinel
fragment appears in the msgstr.

Usage: python3 fix_sentinel_leaks.py <locale>
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TAG_RE = re.compile(r'<[^<>]+>')
_PLACEHOLDER_RE = re.compile(r'%(?:\d+\$)?[sdfucxXob%]|\$\w+|\{[^{}]+\}')


def extract_tokens(text: str):
    """Return placeholder/HTML tokens in the order they appear in `text`."""
    matches = []
    for m in _TAG_RE.finditer(text):
        matches.append((m.start(), m.group(0)))
    for m in _PLACEHOLDER_RE.finditer(text):
        matches.append((m.start(), m.group(0)))
    matches.sort(key=lambda p: p[0])
    return [t for _, t in matches]


def repair_msgstr(msgid: str, msgstr: str) -> str:
    """Replace any ZZ-leak fragments in msgstr with the matching msgid placeholder."""
    tokens = extract_tokens(msgid)
    if not tokens:
        return msgstr
    # Match a wide range of leak forms: ZZ0ZZ (correct), ZZ0Z, Z0ZZ, Z0Z, ZZ0 + ZZ
    # We want to be greedy enough to swallow weird Argos artifacts.
    def _repl(match):
        idx_str = match.group(1)
        try:
            idx = int(idx_str)
        except ValueError:
            return match.group(0)
        if idx < len(tokens):
            return tokens[idx]
        return match.group(0)

    # Order matters: longer patterns first to avoid partial overlapping matches.
    msgstr = re.sub(r'ZZ(\d+)ZZ', _repl, msgstr)
    msgstr = re.sub(r'ZZ(\d+)Z', _repl, msgstr)
    msgstr = re.sub(r'Z(\d+)ZZ+', _repl, msgstr)
    msgstr = re.sub(r'Z(\d+)Z', _repl, msgstr)
    msgstr = re.sub(r'ZZ(\d+)', _repl, msgstr)
    # Quote-wrapped digit/bullet artifacts from MT models that didn't preserve sentinels.
    # `"• 0"`, `"0"`, `"•0"` etc - the whole quoted thing replaces with the placeholder.
    msgstr = re.sub(r'"\s*•?\s*(\d+)\s*•?\s*"', _repl, msgstr)
    # Bare bullet artifacts: `• 0`, `•0`, `0•`, or `0 •`
    msgstr = re.sub(r'•\s*(\d+)', _repl, msgstr)
    msgstr = re.sub(r'(\d+)\s*•', _repl, msgstr)
    # Bare quoted digits (less aggressive than the compound; runs after the others)
    msgstr = re.sub(r'"(\d+)"', _repl, msgstr)
    return msgstr


def fix_po(po_path: str):
    entries = poutil.parse(po_path)
    repaired_count = 0

    for entry in entries:
        if entry.obsolete or not entry.msgid or not entry.msgstr:
            continue
        # Only act if msgstr clearly has a sentinel leak. Includes ZZ-pattern leaks,
        # quote-wrapped digits, and bullet artifacts from prior sentinel formats.
        if not re.search(r'Z\d+Z|ZZ\d+|"\d+"|\u2022\s*\d+|\d+\s*\u2022|"\s*\u2022\s*\d+\s*"', entry.msgstr):
            continue
        fixed = repair_msgstr(entry.msgid, entry.msgstr)
        if fixed != entry.msgstr:
            entry.msgstr = fixed
            repaired_count += 1

    poutil.write(po_path, entries)
    print(f"Repaired {repaired_count} entries in {po_path}")


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
