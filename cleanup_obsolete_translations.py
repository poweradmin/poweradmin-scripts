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
  --verify-only     Only check that every candidate is gone from the source
  --skip-verify     Remove even when a candidate still appears in the source
  --help, -h        Show this message

Before removing anything, every candidate msgid is searched for in lib/,
templates/, install/ and playwright/ as a COMPLETE literal, never a substring:
"Record could not be added." is a prefix of a longer live string, and a plain
grep reports it as still in use. A candidate that still appears means the
template is stale, so the run is refused (exit 1) until it is regenerated.
Matched shapes: 'msgid' or "msgid" (also their escaped PHP/JS source forms),
{% trans %}msgid{% endtrans %}, and >msgid< element text.

Obsolete blocks are removed in both forms: gettext's `#~` lines and the
`# OBSOLETE:` comment form merge_messages.py writes. Counts report each form.

Entries are matched on the full msgid, so multi-line entries are compared in
full. Comparing only a msgid's first line makes distinct entries look identical
and can delete a live translation.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

RED, GREEN, YELLOW, BLUE, NC = '\033[0;31m', '\033[0;32m', '\033[1;33m', '\033[0;34m', '\033[0m'


SEARCH_DIRS = ('lib', 'templates', 'install', 'playwright')
SEARCH_SUFFIXES = ('.php', '.html', '.twig', '.js', '.yaml', '.yml', '.json')


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


def source_spellings(msgid):
    """The ways one msgid can be written between quotes in PHP/JS source."""
    single = msgid.replace('\\', '\\\\').replace("'", "\\'")
    double = (msgid.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
              .replace('\t', '\\t').replace('\r', '\\r'))
    return ({f"'{msgid}'", f'"{msgid}"', f"'{single}'", f'"{double}"'}
            | {f"'{double}'", f'"{single}"'})


def appears_as_literal(msgid, blob):
    """True when the msgid is a complete literal somewhere, not part of a longer one."""
    if any(spelling in blob for spelling in source_spellings(msgid)):
        return True
    if f'>{msgid}<' in blob:
        return True
    pattern = rf'{{%\s*trans\s*%}}{re.escape(msgid)}{{%\s*endtrans\s*%}}'
    return re.search(pattern, blob) is not None


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
    # A module has no template of its own, so only gettext-marked entries can go
    stale = [] if live_msgids is None else [
        e for e in entries
        if e.msgid and not e.obsolete and not e.is_header
        and e.msgid not in live_msgids]
    return entries, marked, stale


def split_marked(marked):
    """(gettext `#~` count, `# OBSOLETE:` comment count) for the marked entries."""
    tilde = sum(1 for e in marked if any(l.startswith('#~') for l in e.raw.split('\n')))
    return tilde, len(marked) - tilde


def describe(marked, stale):
    tilde, comment = split_marked(marked)
    return (f'{len(stale)} template-obsolete + {len(marked)} marked-obsolete '
            f'({tilde} #~, {comment} # OBSOLETE:)')


def merge_into(po_file, template):
    """msgmerge in place, never fuzzy-matching. Returns an error string or None."""
    r = subprocess.run(['msgmerge', '--no-fuzzy-matching', '--backup=none', '--update',
                        po_file, template], capture_output=True, text=True)
    return None if r.returncode == 0 else (r.stderr.strip() or f'exit {r.returncode}')


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

    success(f'  Removed {describe(marked, stale)} translation(s)')

    mo_file = os.path.join(os.path.dirname(po_file), 'messages.mo')
    if subprocess.run(['msgfmt', '-o', mo_file, po_file], capture_output=True).returncode == 0:
        info('  Recompiled MO file')
    else:
        warning('  Failed to recompile MO file')
    return len(stale) + len(marked)


def build_parser():
    parser = argparse.ArgumentParser(
        description='Remove translations that are no longer referenced by the template.',
        allow_abbrev=False)
    parser.add_argument('--dry-run', action='store_true',
                        help='list what would be removed, change nothing')
    parser.add_argument('--locale', metavar='LOCALE', help='process one locale only')
    parser.add_argument('--backup', action='store_true',
                        help='back up each .po before editing (default)')
    parser.add_argument('--no-backup', action='store_true', help='skip backups')
    parser.add_argument('--stats-only', action='store_true',
                        help='report obsolete counts and exit')
    parser.add_argument('--force-check', action='store_true',
                        help='run msgmerge first so gettext marks obsolete entries')
    parser.add_argument('--module', metavar='NAME',
                        help='operate on lib/Module/NAME/locale instead')
    verify = parser.add_mutually_exclusive_group()
    verify.add_argument('--verify-only', action='store_true',
                        help='only check that every candidate is gone from the source')
    verify.add_argument('--skip-verify', action='store_true',
                        help='remove even when a candidate still appears in the source')
    return parser


def verify_candidates(locales, module, live, list_all):
    """Search the source for every candidate msgid. Returns the ones still in use."""
    candidates = set()
    for locale in locales:
        _, marked, stale = find_obsolete(poutil.po_path(locale, module), live)
        candidates.update(e.msgid for e in marked + stale)
    if not candidates:
        success('No obsolete candidates; nothing to verify.')
        return []

    info(f'Checking {len(candidates)} candidate msgid(s) against the source tree...')
    blob = source_text()
    survivors = sorted(m for m in candidates if appears_as_literal(m, blob))
    if list_all:
        for msgid in sorted(candidates):
            mark = f'{RED}IN USE{NC}' if msgid in survivors else f'{GREEN}dead  {NC}'
            preview = msgid if len(msgid) <= 60 else msgid[:60] + '...'
            print(f'  {mark}  "{preview}"')
    if survivors:
        error(f'{len(survivors)} candidate(s) still appear in the source; the template is '
              f'stale. Regenerate it (python3 scripts/extract_strings.py) first:')
        for msgid in survivors:
            preview = msgid if len(msgid) <= 70 else msgid[:70] + '...'
            print(f'  - "{preview}"', file=sys.stderr)
    else:
        success(f'All {len(candidates)} candidate(s) are gone from the source.')
    return survivors


def main(argv=None):
    args = build_parser().parse_args(argv)
    dry_run, stats_only, force_check = args.dry_run, args.stats_only, args.force_check
    make_backup = not args.no_backup
    specific, module = args.locale, args.module

    if args.backup and args.no_backup:
        error('--backup and --no-backup are mutually exclusive')
        return 1
    if force_check and module:
        # The only template is the main one; merging a module catalogue against it
        # would mark every module-specific entry obsolete.
        error('--force-check cannot be combined with --module')
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
            tilde, comment = split_marked(marked)
            print(f'{locale:<12}: {n} obsolete translation(s) '
                  f'({len(stale)} stale, {tilde} #~, {comment} # OBSOLETE:)')
        print('-' * 50)
        print(f'Total: {total} obsolete translations')
        return 0

    # --force-check only marks msgids the template lacks, which are already stale
    # candidates here, so verifying before the merge covers them
    if args.verify_only:
        return 1 if verify_candidates(locales, module, live, list_all=True) else 0
    if not args.skip_verify:
        survivors = verify_candidates(locales, module, live, list_all=dry_run)
        if survivors and not dry_run:
            error('Nothing removed. Pass --skip-verify to remove them anyway.')
            return 1

    cleaned = {}
    failed = []
    for locale in locales:
        po_file = poutil.po_path(locale, module)
        info(f'\nProcessing locale: {locale}')
        analyse, scratch, backed_up = po_file, None, False

        if force_check:
            info('  Running msgmerge to mark obsolete entries...')
            if dry_run:
                scratch = tempfile.mkdtemp()
                analyse = os.path.join(scratch, 'messages.po')
                shutil.copyfile(po_file, analyse)
            elif make_backup:
                info(f'  Created backup: {os.path.basename(poutil.backup(po_file))}')
                backed_up = True
            problem = merge_into(analyse, template)
            if problem:
                error(f'  msgmerge failed for {locale}, skipping it: {problem}')
                failed.append(locale)
                if scratch:
                    shutil.rmtree(scratch, ignore_errors=True)
                continue
            info('  msgmerge completed successfully')

        try:
            _, marked, stale = find_obsolete(analyse, live)
            if not (marked or stale):
                success('  No obsolete translations found.')
                continue

            warning(f'  Found {len(marked) + len(stale)} obsolete translation(s): '
                    f'{describe(marked, stale)}.')
            if dry_run:
                info('  Obsolete translations (dry run):')
                for e in marked + stale:
                    preview = e.msgid if len(e.msgid) <= 60 else e.msgid[:60] + '...'
                    print(f'    - "{preview}"')
            else:
                cleaned[locale] = remove_obsolete(po_file, live, make_backup and not backed_up)
        finally:
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)

    if cleaned:
        info('\nSummary:')
        print('-' * 50)
        for locale, n in cleaned.items():
            if n:
                print(f'{locale:<12}: cleaned {n} translation(s)')
        print('-' * 50)
        success(f'Total: {sum(cleaned.values())} obsolete translations removed')
    if failed:
        error(f'msgmerge failed for: {", ".join(failed)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
