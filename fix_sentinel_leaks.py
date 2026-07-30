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
    with open(po_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Walk blocks; for each entry, extract msgid + msgstr (handling multi-line), repair, write back.
    blocks = re.split(r"\n\s*\n", content)
    repaired_count = 0
    new_blocks = []
    for block in blocks:
        if not block.strip():
            new_blocks.append(block)
            continue
        msgid = _extract(block, "msgid")
        msgstr = _extract(block, "msgstr")
        if not msgid or not msgstr:
            new_blocks.append(block)
            continue
        # Only act if msgstr clearly has a sentinel leak. Includes ZZ-pattern leaks,
        # quote-wrapped digits, and bullet artifacts from prior sentinel formats.
        if not re.search(r'Z\d+Z|ZZ\d+|"\d+"|•\s*\d+|\d+\s*•|"\s*•\s*\d+\s*"', msgstr):
            new_blocks.append(block)
            continue
        fixed = repair_msgstr(msgid, msgstr)
        if fixed != msgstr:
            repaired_count += 1
            # Replace the msgstr block with a single-line clean form
            block = _rewrite_msgstr(block, fixed)
        new_blocks.append(block)

    with open(po_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(new_blocks))

    print(f"Repaired {repaired_count} entries in {po_path}")


def _extract(block: str, key: str):
    pattern = rf'^{re.escape(key)}\s+"(.*)"$'
    m = re.search(pattern, block, re.MULTILINE)
    if not m:
        return None
    parts = [m.group(1)]
    pos = block.index(m.group(0)) + len(m.group(0))
    for line in block[pos:].split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith('"') and s.endswith('"'):
            parts.append(s[1:-1])
        else:
            break
    # Unescape only PO-relevant sequences. Don't re-encode through latin-1 as that
    # mangles UTF-8 multi-byte characters like Danish æ/ø/å.
    text = "".join(parts)
    text = text.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
    return text


def _rewrite_msgstr(block: str, new_msgstr: str) -> str:
    """Find the msgstr block and replace it with a single-line clean form."""
    lines = block.split("\n")
    out = []
    in_msgstr = False
    skipped_continuation = False
    for line in lines:
        if line.startswith("msgstr"):
            in_msgstr = True
            out.append(f'msgstr "{_escape(new_msgstr)}"')
            continue
        if in_msgstr and line.strip().startswith('"') and line.strip().endswith('"'):
            skipped_continuation = True
            continue
        in_msgstr = False
        out.append(line)
    return "\n".join(out)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


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
