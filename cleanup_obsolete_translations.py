#!/usr/bin/env python3
"""Remove translations that are no longer referenced by the template.

Usage:
  python3 scripts/cleanup_obsolete_translations.py [options]

Options:
  --dry-run         List what would be removed, change nothing
  --locale=LOCALE   Process one locale only
  --backup          Back up each .po before editing (default)
  --no-backup       Skip backups
  --stats-only      Report obsolete counts and exit
  --force-check     Run msgmerge first so gettext marks obsolete entries
  --module=NAME     Operate on lib/Module/NAME/locale instead
  --help, -h        Show this message

Entries are matched on the full msgid, so multi-line entries are compared in
full. Comparing only a msgid's first line makes distinct entries look identical
and can delete a live translation.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

RED, GREEN, YELLOW, BLUE, NC = '\033[0;31m', '\033[0;32m', '\033[1;33m', '\033[0;34m', '\033[0m'


def error(msg):
    print(f'{RED}Error: {msg}{NC}', file=sys.stderr)


def success(msg):
    print(f'{GREEN}{msg}{NC}')


def warning(msg):
    print(f'{YELLOW}Warning: {msg}{NC}')


def info(msg):
    print(f'{BLUE}{msg}{NC}')


def check_dependencies():
    missing = [t for t in ('msgmerge', 'msgattrib', 'msgfmt')
               if subprocess.run(['which', t], capture_output=True).returncode != 0]
    if missing:
        error(f"Required gettext tools not found: {' '.join(missing)}")
        error('Install gettext (apt-get install gettext / brew install gettext)')
        return False
    return True


def template_msgids(template):
    """Every live msgid in the template, compared in full."""
    return {e.msgid for e in poutil.parse(template)
            if e.msgid and not e.obsolete and not e.is_header}


def locale_dirs(module):
    base = (os.path.join(poutil.ROOT, 'lib/Module', module, 'locale') if module
            else os.path.join(poutil.ROOT, 'locale'))
    if not os.path.isdir(base):
        return base, []
    found = []
    for name in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, name)):
            continue
        po = poutil.po_path(name, module)
        if os.path.isfile(po):
            found.append(name)
    return base, found


def find_obsolete(po_file, live_msgids):
    """Entries to drop: already marked obsolete, or absent from the template."""
    entries = poutil.parse(po_file)
    marked = [e for e in entries if e.obsolete and e.msgid]
    stale = [e for e in entries
             if e.msgid and not e.obsolete and not e.is_header
             and e.msgid not in live_msgids]
    return entries, marked, stale


def remove_obsolete(po_file, live_msgids, make_backup):
    entries, marked, stale = find_obsolete(po_file, live_msgids)
    drop = {id(e) for e in marked} | {id(e) for e in stale}
    if not drop:
        success('  No obsolete translations found')
        return 0

    if make_backup:
        info(f'  Created backup: {os.path.basename(poutil.backup(po_file))}')

    kept = [e for e in entries if id(e) not in drop]
    # The last surviving entry keeps a single trailing newline
    if kept:
        kept[-1].sep = '\n'
    poutil.write(po_file, kept)

    success(f'  Removed {len(stale)} template-obsolete + {len(marked)} marked-obsolete translation(s)')

    mo_file = os.path.join(os.path.dirname(po_file), 'messages.mo')
    if subprocess.run(['msgfmt', '-o', mo_file, po_file], capture_output=True).returncode == 0:
        info('  Recompiled MO file')
    else:
        warning('  Failed to recompile MO file')
    return len(stale) + len(marked)


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    stats_only = '--stats-only' in args
    force_check = '--force-check' in args
    make_backup = '--no-backup' not in args
    specific = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)
    module = next((a.split('=', 1)[1] for a in args if a.startswith('--module=')), None)

    if '--help' in args or '-h' in args:
        print(__doc__)
        return 0

    unknown = [a for a in args if not a.startswith('--') and a not in ('-h',)]
    if unknown:
        error(f"Unknown argument: {unknown[0]}")
        return 1

    if not check_dependencies():
        return 1

    template = os.path.join(poutil.ROOT, 'locale', 'i18n-template-php.pot')
    if not module and not os.path.isfile(template):
        error(f'Template file not found: {template}')
        error('Run python3 scripts/extract_strings.py first to generate the template.')
        return 1

    base, locales = locale_dirs(module)
    if not locales:
        error(f'No locale files found under {base}')
        return 1
    if specific:
        if specific not in locales:
            error(f'Locale not found: {specific}')
            return 1
        locales = [specific]

    live = template_msgids(template) if not module else None

    if stats_only:
        info('Translation Statistics:')
        print('-' * 50)
        total = 0
        for locale in locales:
            _, marked, stale = find_obsolete(poutil.po_path(locale, module), live)
            n = len(marked) + len(stale)
            total += n
            print(f'{locale:<12}: {n} obsolete translation(s)')
        print('-' * 50)
        print(f'Total: {total} obsolete translations')
        return 0

    cleaned = {}
    for locale in locales:
        po_file = poutil.po_path(locale, module)
        info(f'\nProcessing locale: {locale}')

        if force_check:
            info('  Running msgmerge to mark obsolete entries...')
            r = subprocess.run(['msgmerge', '--backup=none', '--update', po_file, template],
                               capture_output=True)
            info('  msgmerge completed successfully' if r.returncode == 0
                 else '  msgmerge had issues but continued')

        _, marked, stale = find_obsolete(po_file, live)
        if not (marked or stale):
            success('  No obsolete translations found.')
            continue

        warning(f'  Found {len(marked) + len(stale)} obsolete translation(s).')
        if dry_run:
            info('  Obsolete translations (dry run):')
            for e in marked + stale:
                preview = e.msgid if len(e.msgid) <= 60 else e.msgid[:60] + '...'
                print(f'    - "{preview}"')
        else:
            cleaned[locale] = remove_obsolete(po_file, live, make_backup)

    if cleaned:
        info('\nSummary:')
        print('-' * 50)
        for locale, n in cleaned.items():
            if n:
                print(f'{locale:<12}: cleaned {n} translation(s)')
        print('-' * 50)
        success(f'Total: {sum(cleaned.values())} obsolete translations removed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
