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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def msgfmt_errors(po_path: str):
    """Return set of line numbers where msgfmt reports format-spec errors."""
    result = subprocess.run(
        ["msgfmt", "--check", "-o", "/dev/null", po_path],
        capture_output=True, text=True,
    )
    line_nums = set()
    for line in result.stderr.splitlines():
        m = re.search(rf"{re.escape(po_path)}:(\d+):", line)
        if m:
            line_nums.add(int(m.group(1)))
    return line_nums


def find_entry_around(lines: list, target_line: int):
    """Given a 1-based line number, find the start + end of the entry that contains it.
    Returns (start_index, end_index) in the 0-based lines list, or (None, None) if unfound.
    """
    idx = target_line - 1
    # Walk back to msgid line (start of entry)
    start = idx
    while start > 0:
        if lines[start].startswith("msgid ") and not lines[start].startswith("msgid_plural"):
            break
        start -= 1
    # Walk back further past comments to entry top
    entry_start = start
    while entry_start > 0 and (lines[entry_start - 1].startswith("#") or not lines[entry_start - 1].strip()):
        if not lines[entry_start - 1].strip():
            break
        entry_start -= 1
    # Walk forward to find the end of msgstr block
    end = idx
    while end < len(lines) - 1 and lines[end + 1].strip():
        end += 1
    return start, end


def extract_msgid_text(lines, msgid_start):
    """Concatenate the msgid (possibly multi-line) starting at given line."""
    parts = []
    line = lines[msgid_start]
    m = re.match(r'^msgid\s+"(.*)"$', line)
    if not m:
        return None
    parts.append(m.group(1))
    i = msgid_start + 1
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('"') and s.endswith('"'):
            parts.append(s[1:-1])
            i += 1
        else:
            break
    return "".join(parts)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _detect_nplurals(lines: list) -> int:
    """Read the Plural-Forms header to find nplurals=N. Defaults to 2 if absent/malformed."""
    for line in lines[:30]:
        m = re.search(r'Plural-Forms:\s*nplurals=(\d+)', line)
        if m:
            return int(m.group(1))
    return 2


def replace_msgstr_with_msgid(lines, entry_start, entry_end, msgid_text):
    """Replace the msgstr block with a clean single-line form.

    For plural entries (msgid_plural present), replace msgstr[N] lines by index using
    English singular for [0] and English plural for [1+]. For regular entries, one
    msgstr line.
    """
    # Detect plural entry by scanning forward from entry_start
    is_plural = False
    plural_msgid = None
    for i in range(entry_start, entry_end + 1):
        if lines[i].startswith("msgid_plural"):
            is_plural = True
            m = re.match(r'^msgid_plural\s+"(.*)"$', lines[i])
            if m:
                parts = [m.group(1)]
                j = i + 1
                while j < len(lines):
                    s = lines[j].strip()
                    if s.startswith('"') and s.endswith('"'):
                        parts.append(s[1:-1])
                        j += 1
                    else:
                        break
                plural_msgid = "".join(parts)
            break

    # Find first msgstr-line index
    msgstr_idx = None
    for i in range(entry_start, entry_end + 1):
        if lines[i].startswith("msgstr"):
            msgstr_idx = i
            break
    if msgstr_idx is None:
        return lines

    if is_plural:
        # Count existing msgstr[N] lines to preserve plural-form count
        n = 0
        for i in range(msgstr_idx, entry_end + 1):
            if re.match(r'^msgstr\[\d+\]', lines[i]):
                n += 1
        # If the file declares nplurals=1 (e.g. Thai, Malay), only emit msgstr[0]
        nplurals = _detect_nplurals(lines)
        if nplurals == 1:
            n = 1
        else:
            n = max(n, 2)
        new_lines = []
        for k in range(n):
            text = msgid_text if k == 0 else (plural_msgid or msgid_text)
            new_lines.append(f'msgstr[{k}] "{_escape(text)}"')
    else:
        new_lines = [f'msgstr "{_escape(msgid_text)}"']

    # Cut the old msgstr region (including continuation lines and any msgstr[N] siblings).
    out = lines[:msgstr_idx] + new_lines
    i = msgstr_idx
    while i <= entry_end:
        if lines[i].startswith("msgstr") or lines[i].strip().startswith('"'):
            i += 1
            continue
        break
    out.extend(lines[i:])
    return out


def fix_po(po_path: str):
    error_lines = msgfmt_errors(po_path)
    if not error_lines:
        print(f"No errors in {po_path}")
        return

    print(f"Found {len(error_lines)} failing entries in {po_path}; falling back to English msgid")
    with open(po_path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")

    fixed = 0
    # Process from bottom up so line numbers stay valid as we replace.
    for target_line in sorted(error_lines, reverse=True):
        entry_start, entry_end = find_entry_around(lines, target_line)
        if entry_start is None:
            continue
        msgid_text = extract_msgid_text(lines, entry_start)
        if not msgid_text:
            continue
        lines = replace_msgstr_with_msgid(lines, entry_start, entry_end, msgid_text)
        fixed += 1

    with open(po_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
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
