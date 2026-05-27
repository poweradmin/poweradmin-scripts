#!/usr/bin/env python3
"""
Find hidden-Unicode and UTF-8-double-encoding bugs in locale/*.po files.

What it catches:
  - Mojibake from UTF-8 mis-decoded as Latin-1 then re-encoded as UTF-8
    (signature: 4-byte sequence `0xC3 [0x82-0x85] [0xC2|0xC3] [0x80-0xBF]`).
    Example: bytes for `é` (0xC3 0xA9) become `Ã©` (0xC3 0x83 0xC2 0xA9).
  - Hidden Unicode characters that can hide text from reviewers or confuse
    tools (Renovate's "smuggled text" warning):
      - SHY                  U+00AD  soft hyphen
      - ZWSP/ZWNJ/ZWJ/WJ/BOM U+200B/C/D/U+2060/U+FEFF/U+180E
      - Bidi controls        U+202A-E, U+2066-9
      - Invisible math       U+2061-4
      - Tag characters       U+E0000-U+E007F
      - ASCII controls       0x00-0x08, 0x0B-0x0C, 0x0E-0x1F, 0x7F

Legitimate-use whitelist:
  - U+200C ZWNJ is normal Persian/Arabic orthography (compound verbs,
    morpheme boundaries). Skipped in fa_IR, ar_SA, fa_*, ar_*, ur_*, ps_*.

Usage:
  scripts/check_locale_unicode.py                # report only, exit 1 on findings
  scripts/check_locale_unicode.py --fix          # repair mojibake bytes in place
  scripts/check_locale_unicode.py --quiet        # only print summary
  scripts/check_locale_unicode.py path/to/x.po   # check a single file
"""
import argparse
import glob
import os
import re
import sys

# --- mojibake detection ---------------------------------------------------
# Ã/Â/Ä/Å are U+00C2..U+00C5, UTF-8 encoded as 0xC3 0x82..0xC3 0x85.
# The second mojibake char is any byte 0x80-0xFF re-encoded as UTF-8,
# which is `0xC2|0xC3` + `0x80-0xBF`.
MOJIBAKE_BYTES = re.compile(rb"\xc3[\x82-\x85][\xc2\xc3][\x80-\xbf]")

# --- hidden-character detection -------------------------------------------
HIDDEN_CATS = {
    "zero-width": {"​", "‌", "‍", "⁠", "﻿", "᠎"},
    "soft-hyphen": {"­"},
    "bidi-control": set("‪‫‬‭‮⁦⁧⁨⁩"),
    "invisible-math": {"⁡", "⁢", "⁣", "⁤"},
    "tag-chars": {chr(c) for c in range(0xE0000, 0xE007F + 1)},
    "ascii-control": (
        {chr(c) for c in range(0, 9)} | {"\x0B", "\x0C"} |
        {chr(c) for c in range(14, 32)} | {"\x7F"}
    ),
}
CHAR_TO_CAT = {ch: cat for cat, chars in HIDDEN_CATS.items() for ch in chars}

# locales where U+200C (ZWNJ) is legitimate orthography
ZWNJ_LEGIT_PREFIXES = ("fa_", "ar_", "ur_", "ps_")


def find_mojibake(blob):
    """Return list of (offset, line_no, four_byte_seq, repaired_two_bytes).

    Filters false positives: if the 2-byte repair isn't itself valid UTF-8,
    the source bytes weren't mojibake -- they were legitimate adjacent
    characters that happened to fit the byte pattern (e.g. Finnish `Ää`).
    """
    out = []
    for m in MOJIBAKE_BYTES.finditer(blob):
        seq = m.group(0)
        try:
            repaired = seq.decode("utf-8").encode("latin-1")
            repaired.decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        line_no = blob.count(b"\n", 0, m.start()) + 1
        out.append((m.start(), line_no, seq, repaired))
    return out


def find_hidden(text, locale):
    """Return list of (line_no, col, char, category)."""
    out = []
    zwnj_legit = any(locale.startswith(p) for p in ZWNJ_LEGIT_PREFIXES)
    for lineno, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            cat = CHAR_TO_CAT.get(ch)
            if not cat:
                continue
            if ch == "‌" and zwnj_legit:
                continue
            out.append((lineno, col, ch, cat))
    return out


def repair_mojibake(blob):
    """Replace only sequences whose repair is itself valid UTF-8."""
    def repl(m):
        seq = m.group(0)
        try:
            repaired = seq.decode("utf-8").encode("latin-1")
            repaired.decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return seq
        return repaired
    return MOJIBAKE_BYTES.sub(repl, blob)


def process_file(path, do_fix, quiet):
    locale = path.split(os.sep)[-3] if "locale" in path else ""
    with open(path, "rb") as fh:
        blob = fh.read()
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"  {path}: NOT VALID UTF-8 ({e})")
        return 1, 0, 0

    moji = find_mojibake(blob)
    hidden = find_hidden(text, locale)

    n_moji = len(moji)
    n_hidden = len(hidden)
    if not n_moji and not n_hidden:
        return 0, 0, 0

    if not quiet:
        print(f"\n{path}")
        if n_moji:
            cats = {}
            for _, _, seq, rep in moji:
                cats[(seq, rep)] = cats.get((seq, rep), 0) + 1
            top = sorted(cats.items(), key=lambda kv: -kv[1])[:6]
            print(f"  mojibake: {n_moji} byte sequences")
            for (seq, rep), n in top:
                s = seq.decode("utf-8")
                try:
                    r = rep.decode("utf-8")
                except UnicodeDecodeError:
                    r = repr(rep)
                print(f"    {s!r} -> {r!r}  x{n}")
            if len(cats) > 6:
                print(f"    ... and {len(cats)-6} more distinct patterns")
        if n_hidden:
            by_cat = {}
            for _, _, ch, cat in hidden:
                by_cat[(cat, ch)] = by_cat.get((cat, ch), 0) + 1
            print(f"  hidden Unicode: {n_hidden} characters")
            for (cat, ch), n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
                print(f"    {cat} U+{ord(ch):04X}  x{n}")

    if do_fix and n_moji:
        fixed = repair_mojibake(blob)
        try:
            fixed.decode("utf-8")
        except UnicodeDecodeError as e:
            print(f"  REFUSING to write {path}: repair produced invalid UTF-8 ({e})")
            return 1, 0, 0
        with open(path, "wb") as fh:
            fh.write(fixed)
        if not quiet:
            print(f"  -> repaired {n_moji} mojibake sequences")
    return 0, n_moji, n_hidden


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*",
                    help="specific .po files (default: locale/*/LC_MESSAGES/messages.po)")
    ap.add_argument("--fix", action="store_true",
                    help="repair mojibake byte sequences in place")
    ap.add_argument("--quiet", action="store_true",
                    help="only print summary line, no per-file detail")
    args = ap.parse_args()

    if args.paths:
        files = args.paths
    else:
        files = sorted(glob.glob("locale/*/LC_MESSAGES/messages.po"))
    if not files:
        print("no .po files found", file=sys.stderr)
        sys.exit(2)

    total_moji = 0
    total_hidden = 0
    affected = 0
    errors = 0
    for path in files:
        err, n_moji, n_hidden = process_file(path, args.fix, args.quiet)
        errors += err
        if n_moji or n_hidden:
            affected += 1
            total_moji += n_moji
            total_hidden += n_hidden

    print(f"\n=== summary ===")
    print(f"  files scanned : {len(files)}")
    print(f"  files with findings: {affected}")
    print(f"  mojibake bytes: {total_moji}")
    print(f"  hidden chars  : {total_hidden}")
    if errors:
        sys.exit(2)
    sys.exit(0 if (total_moji + total_hidden == 0 or args.fix) else 1)


if __name__ == "__main__":
    main()
