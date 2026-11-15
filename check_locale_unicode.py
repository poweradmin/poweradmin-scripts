#!/usr/bin/env python3
"""
Find hidden-Unicode, mojibake, and MT-artifact characters in locale/*.po files.

What it catches:
  - Mojibake from UTF-8 mis-decoded as Latin-1/cp1252 then re-encoded as UTF-8,
    in any script (Cyrillic, Greek, Arabic, Hebrew, Vietnamese, Latin accents).
    Example: `é` (bytes 0xC3 0xA9) becomes `Ã©`. A run is flagged only when
    reversing it yields valid UTF-8.
  - Hidden Unicode characters that can hide text from reviewers or confuse
    tools (Renovate's "smuggled text" warning):
      - SHY                  U+00AD  soft hyphen
      - ZWSP/ZWNJ/ZWJ/WJ/BOM U+200B/C/D/U+2060/U+FEFF/U+180E
      - Bidi controls        U+202A-E, U+2066-9
      - Invisible math       U+2061-4
      - Tag characters       U+E0000-U+E007F
      - ASCII controls       0x00-0x08, 0x0B-0x0C, 0x0E-0x1F, 0x7F
  - MT-artifact characters in msgstrs that almost never belong in real
    human-language translations (caught real bugs like ms_MY's `♪ OK ♪`
    music-note wrappers and Greek `α` standing in for `\"` quotes):
      - Music notes          U+2669-U+266F  (♩ ♪ ♫ ♬ ♭ ♮ ♯)
      - Math alphanumeric    U+1D400-U+1D7FF (𝐀-𝟿)
      - Box drawing          U+2500-U+257F
      - Dingbats             U+2700-U+27BF
      - Geometric shapes     U+25A0-U+25FF
      - Misc symbols         U+2600-U+26FF (decorative weather/zodiac/etc.)
      - Greek letters in non-Greek locales
    Only flagged when the character appears in msgstr but NOT in the
    corresponding msgid (msgid presence means the char is referenced
    deliberately, e.g. a code snippet).

Legitimate-use whitelist:
  - U+200C ZWNJ is normal Persian/Arabic orthography (compound verbs,
    morpheme boundaries). Skipped in fa_IR, ar_SA, fa_*, ar_*, ur_*, ps_*.
  - Greek letters in el_GR locale.

Usage:
  scripts/check_locale_unicode.py                # report only, exit 1 on findings
  scripts/check_locale_unicode.py --fix          # repair mojibake bytes in place
  scripts/check_locale_unicode.py --quiet        # only print summary
  scripts/check_locale_unicode.py --no-mt        # skip MT-artifact check
  scripts/check_locale_unicode.py path/to/x.po   # check a single file
"""
import argparse
import glob
import os
import re
import sys
import unicodedata

# --- mojibake detection ---------------------------------------------------
# UTF-8 text decoded as Latin-1/cp1252 and saved again as UTF-8 shows up as a
# lead char (U+00C2-U+00F4) followed by 1-3 chars that stand for continuation
# bytes 0x80-0xBF: U+0080-U+00BF, or the cp1252 punctuation that occupies
# 0x80-0x9F ("\u00e2\u20ac\u2122" for a right quote).
_CP1252_CONT = "".join(
    ch for ch in map(chr, range(0x100, 0x2200))
    if ch.encode("cp1252", "ignore") and 0x80 <= ch.encode("cp1252", "ignore")[0] <= 0xBF
)
_CONT = "[\u0080-\u00bf" + _CP1252_CONT + "]"
MOJIBAKE_RE = re.compile(
    "(?:[\u00c2-\u00df]" + _CONT + "|[\u00e0-\u00ef]" + _CONT + "{2}|[\u00f0-\u00f4]" + _CONT + "{3})"
)


def _unmangle(seq):
    """The UTF-8 bytes the mojibake run came from, or None when it is not mojibake.

    A run only counts when reversing it gives valid UTF-8 with no control
    characters, so legitimate adjacent accented letters stay untouched.
    """
    try:
        raw = b"".join(
            ch.encode("cp1252") if ch.encode("cp1252", "ignore") else ch.encode("latin-1")
            for ch in seq
        )
        fixed = raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if any(unicodedata.category(c) == "Cc" for c in fixed):
        return None
    # Legit pairs such as "ß«" (in »Fuß«) also reverse cleanly, but into scripts no
    # shipped locale uses (NKo, IPA), so only accept a plausible result
    if not all(_plausible(c) for c in fixed):
        return None
    return raw


# Unicode blocks real translations in the shipped locales use
_PLAUSIBLE_RANGES = (
    (0x00A0, 0x024F),  # Latin-1 Supplement, Latin Extended-A/B
    (0x0300, 0x036F),  # combining diacritics
    (0x0370, 0x052F),  # Greek, Cyrillic
    (0x0590, 0x06FF),  # Hebrew, Arabic
    (0x0900, 0x097F),  # Devanagari
    (0x0E00, 0x0E7F),  # Thai
    (0x1E00, 0x1EFF),  # Latin Extended Additional (Vietnamese)
    (0x2000, 0x214F),  # punctuation, currency, letterlike symbols
    (0x3000, 0x9FFF),  # CJK
    (0xAC00, 0xD7AF),  # Hangul
    (0xFF00, 0xFFEF),  # fullwidth forms
)


def _plausible(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _PLAUSIBLE_RANGES)


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

# --- MT-artifact detection ------------------------------------------------
# Characters that are essentially never legitimate inside a translated
# human-language string. Caught real bugs in ms_MY: music notes wrapping
# short labels (`♪ OK ♪`) and Greek alpha standing in for `\"` quotes.
MUSIC_NOTES = set("♩♪♫♬♭♮♯")
GREEK_LEGIT_LOCALES = {"el_GR"}


def is_mt_artifact_char(ch, locale):
    """True if ch is universally suspect in a translated msgstr."""
    cp = ord(ch)
    if ch in MUSIC_NOTES:
        return True
    if 0x1D400 <= cp <= 0x1D7FF:        # Math alphanumeric
        return True
    if 0x2500 <= cp <= 0x257F:          # Box drawing
        return True
    if 0x2700 <= cp <= 0x27BF:          # Dingbats
        return True
    if 0x25A0 <= cp <= 0x25FF:          # Geometric shapes
        return True
    if 0x2600 <= cp <= 0x26FF:          # Misc symbols
        return ch not in ("☐", "☑", "☒")  # ballot/checkbox is fine
    if (0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF) and locale not in GREEK_LEGIT_LOCALES:
        return True
    return False


def find_mojibake(text):
    """Return list of (char_offset, line_no, mojibake_bytes, repaired_bytes)."""
    out = []
    for m in MOJIBAKE_RE.finditer(text):
        raw = _unmangle(m.group(0))
        if raw is None:
            continue
        out.append((m.start(), text.count("\n", 0, m.start()) + 1,
                    m.group(0).encode("utf-8"), raw))
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


def find_mt_artifacts(text, locale):
    """Return list of (line_no, msgstr, dict(char->count)) for msgstrs with
    MT-artifact chars not present in the corresponding msgid."""
    out = []
    lines = text.splitlines()
    i = 0
    last_msgid = ""
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(msgid|msgstr)(\[\d+\])? "(.*)"\s*$', line)
        if not m:
            i += 1
            continue
        kind = m.group(1)
        parts = [m.group(3)]
        start = i
        j = i + 1
        while j < len(lines) and lines[j].startswith('"'):
            m2 = re.match(r'^"(.*)"\s*$', lines[j])
            if m2:
                parts.append(m2.group(1))
            j += 1
        content = ''.join(parts)
        if kind == "msgid":
            last_msgid = content
        else:
            msgid_chars = set(last_msgid)
            suspect = {}
            for ch in content:
                if ord(ch) < 128 or ch in msgid_chars:
                    continue
                if is_mt_artifact_char(ch, locale):
                    suspect[ch] = suspect.get(ch, 0) + 1
            if suspect:
                out.append((start + 1, content, suspect))
        i = j
    return out


def repair_mojibake(text):
    """Replace only runs whose reversal is itself valid UTF-8."""
    def repl(m):
        raw = _unmangle(m.group(0))
        return m.group(0) if raw is None else raw.decode("utf-8")
    return MOJIBAKE_RE.sub(repl, text)


def process_file(path, do_fix, quiet, check_mt):
    locale = path.split(os.sep)[-3] if "locale" in path else ""
    with open(path, "rb") as fh:
        blob = fh.read()
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"  {path}: NOT VALID UTF-8 ({e})")
        return 1, 0, 0, 0

    moji = find_mojibake(text)
    hidden = find_hidden(text, locale)
    mt = find_mt_artifacts(text, locale) if check_mt else []

    n_moji = len(moji)
    n_hidden = len(hidden)
    n_mt = sum(sum(d.values()) for _, _, d in mt)
    if not n_moji and not n_hidden and not n_mt:
        return 0, 0, 0, 0

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
        if n_mt:
            print(f"  MT artifacts: {len(mt)} msgstrs, {n_mt} suspect chars")
            for lineno, mstr, chars in mt[:5]:
                cs = " ".join(f"{c!r}x{n}" for c, n in chars.items())
                print(f"    L{lineno} [{cs}]: {mstr[:100]}")
            if len(mt) > 5:
                print(f"    ... and {len(mt)-5} more msgstrs")

    if do_fix and n_moji:
        fixed = repair_mojibake(text)
        with open(path, "wb") as fh:
            fh.write(fixed.encode("utf-8"))
        if not quiet:
            print(f"  -> repaired {n_moji} mojibake sequences")
    return 0, n_moji, n_hidden, n_mt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*",
                    help="specific .po files (default: locale/*/LC_MESSAGES/messages.po)")
    ap.add_argument("--fix", action="store_true",
                    help="repair mojibake byte sequences in place")
    ap.add_argument("--quiet", action="store_true",
                    help="only print summary line, no per-file detail")
    ap.add_argument("--no-mt", action="store_true",
                    help="skip MT-artifact check (music notes, math, Greek, etc.)")
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
    total_mt = 0
    affected = 0
    errors = 0
    for path in files:
        err, n_moji, n_hidden, n_mt = process_file(path, args.fix, args.quiet, not args.no_mt)
        errors += err
        if n_moji or n_hidden or n_mt:
            affected += 1
            total_moji += n_moji
            total_hidden += n_hidden
            total_mt += n_mt

    print(f"\n=== summary ===")
    print(f"  files scanned : {len(files)}")
    print(f"  files with findings: {affected}")
    print(f"  mojibake bytes: {total_moji}")
    print(f"  hidden chars  : {total_hidden}")
    print(f"  MT artifacts  : {total_mt}")
    if errors:
        sys.exit(2)
    # mojibake is auto-fixable; hidden + MT need manual review
    unresolved = (0 if args.fix else total_moji) + total_hidden + total_mt
    sys.exit(0 if unresolved == 0 else 1)


if __name__ == "__main__":
    main()
