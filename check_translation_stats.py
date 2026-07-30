#!/usr/bin/env python3
"""Per-locale translation coverage.

Usage: python3 scripts/check_translation_stats.py [--module=ModuleName] [--verbose]

Reports two different numbers on purpose:

  Filled  - msgstr is non-empty. This is what msgfmt calls "translated", and it
            counts an English fallback as done, so it reads 100% once a merge has
            filled every entry.
  Real    - msgstr is non-empty AND differs from the msgid, excluding the
            technical terms in technical_exclusions.json. en_EN is exempt from the
            differs-from-msgid rule. This is the figure that tracks real progress.

The gap between them is the fallback backlog: entries carrying English text,
usually flagged `#, auto-english-fallback`.
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402


def stats_for(po_file, locale, exclusions):
    entries = poutil.parse(po_file)
    total = filled = real = fallback = identity = orphaned = 0

    for e in entries:
        if e.obsolete:
            if e.msgid:
                orphaned += 1
            continue
        if not e.msgid or e.is_header:
            continue
        if poutil.is_excluded(e.msgid, exclusions):
            continue

        total += 1
        if e.msgstr or e.plurals:
            filled += 1
        if not poutil.is_untranslated(e, locale):
            real += 1
        elif e.msgstr == e.msgid and e.msgstr:
            if 'auto-english-fallback' in e.flags:
                fallback += 1
            elif len(re.findall(r'\w+', e.msgid)) <= 2:
                # one or two words: often correct as-is (Hostname, Dashboard)
                identity += 1
    return total, filled, real, fallback, identity, orphaned


def main():
    args = sys.argv[1:]
    verbose = '--verbose' in args or '-v' in args
    module = next((a.split('=', 1)[1] for a in args if a.startswith('--module=')), None)

    if module:
        base = os.path.join(poutil.ROOT, 'lib/Module', module, 'locale')
        print(f'=== Translation Statistics for Module: {module} ===')
    else:
        base = os.path.join(poutil.ROOT, 'locale')
        print('=== Translation Statistics for All Locales ===')
    print(f'Generated on: {datetime.now().astimezone().strftime("%a %b %d %H:%M:%S %Z %Y")}')
    print()

    if not os.path.isdir(base):
        print(f'Error: locale directory not found: {base}', file=sys.stderr)
        return 1

    exclusions = poutil.load_exclusions()
    locales = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))

    print(f'{"Locale":<8} | {"Total":>6} | {"Filled":>7} | {"Real":>6} | {"Fallback":>8} | {"Identity":>8} | {"Orphan":>6} | Real %')
    print('-' * 8 + '-|-' + '-' * 6 + '-|-' + '-' * 7 + '-|-' + '-' * 6 + '-|-'
          + '-' * 8 + '-|-' + '-' * 8 + '-|-' + '-' * 6 + '-|-------')

    sum_total = sum_real = sum_fallback = sum_identity = sum_orphan = 0
    complete = 0
    rows = 0

    for locale in locales:
        po_file = poutil.po_path(locale, module)
        if not os.path.isfile(po_file):
            continue
        total, filled, real, fallback, identity, orphaned = stats_for(po_file, locale, exclusions)
        if not total:
            continue
        rows += 1
        pct = real * 100.0 / total
        mark = ' OK' if pct >= 95 else ''
        print(f'{locale:<8} | {total:>6} | {filled:>7} | {real:>6} | {fallback:>8} | '
              f'{identity:>8} | {orphaned:>6} | {pct:5.1f}%{mark}')
        sum_total += total
        sum_real += real
        sum_fallback += fallback
        sum_identity += identity
        sum_orphan += orphaned
        if pct >= 95:
            complete += 1

    print()
    print('=== Summary ===')
    print(f'Locales                     : {rows}')
    print(f'Strings per locale           : {sum_total // rows if rows else 0}')
    print(f'Really translated (>=95%)    : {complete}')
    print(f'English fallbacks pending    : {sum_fallback}')
    print(f'1-2 word identity matches    : {sum_identity}  (often correct as-is)')
    print(f'Orphaned entries             : {sum_orphan}')
    if verbose:
        print()
        print('"Filled" is msgfmt\'s view and counts English fallbacks as translated.')
        print('Use "Real" for progress, and python3 scripts/check_translations.py for a per-entry list.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
