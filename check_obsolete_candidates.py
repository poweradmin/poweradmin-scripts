#!/usr/bin/env python3
"""
Verify that every translation cleanup_obsolete_translations.py would delete is
really dead, by looking for its msgid in the source tree.

An entry counts as obsolete when the extracted template no longer lists its
msgid, so a stale template silently turns live translations into deletion
candidates. This checks the other direction: each candidate is searched for in
lib/, templates/, install/ and playwright/ as a COMPLETE literal, never as a
substring. That distinction is the whole point - "Record could not be added."
is a prefix of the live string "Record could not be added. Please check the
record data and try again.", and a plain grep reports it as still in use.

Matched shapes:
  'msgid' or "msgid"              PHP and JS string literals
  {% trans %}msgid{% endtrans %}  Twig translation blocks
  >msgid<                         bare element text

Exits 1 when any candidate still appears, so it can gate a cleanup run:

  scripts/extract_strings.py && scripts/check_obsolete_candidates.py \
      && scripts/cleanup_obsolete_translations.py

Usage:
  scripts/check_obsolete_candidates.py                # check every locale
  scripts/check_obsolete_candidates.py --locale=de_DE # one locale
  scripts/check_obsolete_candidates.py --list         # print the candidates too
  scripts/check_obsolete_candidates.py --quiet        # summary only
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

RED, GREEN, YELLOW, BLUE, NC = '\033[0;31m', '\033[0;32m', '\033[1;33m', '\033[0;34m', '\033[0m'

SEARCH_DIRS = ('lib', 'templates', 'install', 'playwright')
SEARCH_SUFFIXES = ('.php', '.html', '.twig', '.js')


def source_text():
    """Every searchable source file, concatenated once."""
    chunks = []
    for name in SEARCH_DIRS:
        root = os.path.join(poutil.ROOT, name)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ('vendor', 'node_modules', '.git', 'locale')]
            for filename in filenames:
                if not filename.endswith(SEARCH_SUFFIXES):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, encoding='utf-8', errors='replace') as handle:
                        chunks.append(handle.read())
                except OSError:
                    continue
    return '\n'.join(chunks)


def appears_as_literal(msgid, blob):
    """True when the msgid is a complete literal somewhere, not part of a longer one."""
    quoted = re.escape(msgid)
    patterns = (
        rf"'{quoted}'",
        rf'"{quoted}"',
        rf'{{%\s*trans\s*%}}{quoted}{{%\s*endtrans\s*%}}',
        rf'>{quoted}<',
    )
    return any(re.search(pattern, blob) for pattern in patterns)


def template_msgids():
    template = os.path.join(poutil.ROOT, 'locale', 'i18n-template-php.pot')
    if not os.path.isfile(template):
        print(f'{RED}Error: template not found: {template}{NC}', file=sys.stderr)
        print('Run scripts/extract_strings.py first.', file=sys.stderr)
        return None
    return {e.msgid for e in poutil.parse(template)
            if e.msgid and not e.obsolete and not e.is_header}


def main():
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        print(__doc__)
        return 0

    quiet = '--quiet' in args
    show_list = '--list' in args
    only = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)

    live = template_msgids()
    if live is None:
        return 1

    locales = [only] if only else list(poutil.locales())
    candidates = set()
    for locale in locales:
        path = poutil.po_path(locale)
        if not os.path.isfile(path):
            print(f'{RED}Error: no catalogue for {locale}{NC}', file=sys.stderr)
            return 1
        for entry in poutil.parse(path):
            if not entry.msgid or entry.is_header:
                continue
            if entry.obsolete or entry.msgid not in live:
                candidates.add(entry.msgid)

    if not candidates:
        if not quiet:
            print(f'{GREEN}No obsolete candidates; nothing to verify.{NC}')
        return 0

    if not quiet:
        print(f'{BLUE}Checking {len(candidates)} candidate msgid(s) against the source tree...{NC}')
    blob = source_text()
    survivors = sorted(m for m in candidates if appears_as_literal(m, blob))

    if show_list and not quiet:
        for msgid in sorted(candidates):
            mark = f'{RED}IN USE{NC}' if msgid in survivors else f'{GREEN}dead  {NC}'
            preview = msgid if len(msgid) <= 60 else msgid[:60] + '...'
            print(f'  {mark}  "{preview}"')

    if survivors:
        print(f'{RED}{len(survivors)} candidate(s) still appear in the source; '
              f'the template is stale, do not run the cleanup:{NC}')
        for msgid in survivors:
            preview = msgid if len(msgid) <= 70 else msgid[:70] + '...'
            print(f'  - "{preview}"')
        return 1

    if not quiet:
        print(f'{GREEN}All {len(candidates)} candidate(s) are gone from the source; '
              f'the cleanup is safe to run.{NC}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
