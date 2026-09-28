#!/usr/bin/env python3
"""Move translations that only exist in a module catalogue into the main one.

Module catalogues under lib/Module/<Name>/locale/<locale>/messages.po are loaded
by Symfony *in addition to* the main catalogue, so anything they define shadows
locale/<locale>/LC_MESSAGES/messages.po. Before those catalogues can be retired,
any translation they alone carry has to be preserved here.

Two classes are reported:

  absent      the msgid does not exist in the main catalogue at all
  untranslated the main catalogue has the msgid but no real translation, while
              the module has one

Stale msgids - ones no longer present in the extracted template - are skipped by
default: importing them would only give cleanup_obsolete_translations.py more to
delete. Pass --include-stale to override.

A wrong-language guard rejects any candidate whose text is byte-identical to a
*different* locale's translation of the same msgid; that is how a French string
ended up sitting in the Indonesian module catalogue.

Usage:
  python3 scripts/harvest_module_translations.py [options]

Options:
  --dry-run         Report what would move, change nothing
  --module=NAME     Only this module
  --locale=LOCALE   Only this locale
  --include-stale   Also import msgids missing from the template
  --force           Import even candidates the wrong-language guard rejected
  --help, -h        Show this message
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

RED, GREEN, YELLOW, BLUE, NC = '\033[0;31m', '\033[0;32m', '\033[1;33m', '\033[0;34m', '\033[0m'

TEMPLATE = os.path.join(poutil.ROOT, 'locale', 'i18n-template-php.pot')


def template_msgids():
    """Every msgid the extractor currently finds, so stale entries can be skipped."""
    if not os.path.exists(TEMPLATE):
        return None
    return {e.msgid for e in poutil.parse(TEMPLATE) if e.msgid}


def main_value_by_locale(msgid):
    """msgid -> {locale: msgstr} across every main catalogue, for the guard."""
    out = {}
    for po in glob.glob(os.path.join(poutil.ROOT, 'locale', '*', 'LC_MESSAGES', 'messages.po')):
        loc = po.split(os.sep)[-3]
        for e in poutil.parse(po):
            if e.msgid == msgid and not e.obsolete and e.msgstr:
                out[loc] = e.msgstr
                break
    return out


def main():
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        print(__doc__)
        return 0

    dry = '--dry-run' in args
    force = '--force' in args
    include_stale = '--include-stale' in args
    only_module = next((a.split('=', 1)[1] for a in args if a.startswith('--module=')), None)
    only_locale = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)

    tmpl = template_msgids()
    if tmpl is None:
        print(f'{YELLOW}Warning: template not found, cannot skip stale msgids{NC}', file=sys.stderr)

    pattern = os.path.join(poutil.ROOT, 'lib', 'Module', '*', 'locale', '*', 'messages.po')
    candidates = []          # (module, locale, msgid, msgstr, kind)
    skipped_stale = []
    rejected = []

    for po in sorted(glob.glob(pattern)):
        parts = po.split(os.sep)
        module, locale = parts[-4], parts[-2]
        if only_module and module != only_module:
            continue
        if only_locale and locale != only_locale:
            continue

        main_po = poutil.po_path(locale)
        if not os.path.exists(main_po):
            continue
        main_entries = {e.msgid: e for e in poutil.parse(main_po) if not e.obsolete}

        for e in poutil.parse(po):
            if e.obsolete or not e.msgid or not e.msgstr:
                continue
            if poutil.is_untranslated(e, locale):
                continue                       # module has nothing real to give

            existing = main_entries.get(e.msgid)
            if existing is None:
                kind = 'absent'
            elif poutil.is_untranslated(existing, locale):
                kind = 'untranslated'
            else:
                continue                       # main already has a real translation

            if tmpl is not None and e.msgid not in tmpl and not include_stale:
                skipped_stale.append((module, locale, e.msgid))
                continue

            # Wrong-language guard: identical to another locale's translation.
            others = main_value_by_locale(e.msgid)
            clash = [loc for loc, val in others.items()
                     if val == e.msgstr and loc != locale and loc != 'en_EN']
            if clash and not force:
                rejected.append((module, locale, e.msgid, e.msgstr, clash))
                continue

            candidates.append((module, locale, e.msgid, e.msgstr, kind))

    if skipped_stale:
        print(f'{BLUE}Skipped {len(skipped_stale)} stale msgid(s) not in the template '
              f'(use --include-stale to import):{NC}')
        for module, locale, msgid in skipped_stale[:10]:
            print(f'  {module}/{locale} {msgid!r}')
        if len(skipped_stale) > 10:
            print(f'  ... and {len(skipped_stale) - 10} more')

    if rejected:
        print(f'\n{RED}Rejected {len(rejected)} candidate(s) - text matches another locale '
              f'(likely wrong language). Use --force to import anyway:{NC}')
        for module, locale, msgid, msgstr, clash in rejected:
            print(f'  {module}/{locale} {msgid!r} -> {msgstr!r} (same as {", ".join(clash)})')

    if not candidates:
        print(f'\n{GREEN}Nothing to harvest.{NC}')
        return 0

    print(f'\n{BLUE}{len(candidates)} translation(s) to move into the main catalogue:{NC}')
    for module, locale, msgid, msgstr, kind in candidates:
        print(f'  [{kind:12}] {module}/{locale} {msgid!r} -> {msgstr!r}')

    if dry:
        print(f'\n{YELLOW}Dry run - nothing written.{NC}')
        return 0

    by_locale = {}
    for module, locale, msgid, msgstr, kind in candidates:
        by_locale.setdefault(locale, []).append((msgid, msgstr, kind))

    for locale, rows in sorted(by_locale.items()):
        main_po = poutil.po_path(locale)
        entries = poutil.parse(main_po)
        index = {e.msgid: e for e in entries if not e.obsolete}
        appended = []
        for msgid, msgstr, kind in rows:
            if kind == 'untranslated' and msgid in index:
                index[msgid].msgstr = msgstr
            else:
                appended.append((msgid, msgstr))
        poutil.write(main_po, entries)

        if appended:
            with open(main_po, 'r', encoding='utf-8') as fh:
                text = fh.read()
            if not text.endswith('\n'):
                text += '\n'
            for msgid, msgstr in appended:
                text += (f'\nmsgid "{poutil.format_string(msgid)}"\n'
                         f'msgstr "{poutil.format_string(msgstr)}"\n')
            with open(main_po, 'w', encoding='utf-8') as fh:
                fh.write(text)
        print(f'{GREEN}  {locale}: {len(rows)} translation(s) merged{NC}')

    print(f'\n{GREEN}Done. Recompile with: python3 scripts/compile_messages.py{NC}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
