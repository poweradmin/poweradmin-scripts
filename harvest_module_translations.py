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

Plural entries are copied when the main catalogue's nplurals equals the number of
forms the module supplies; otherwise they are listed as unharvested. When two
modules supply the same msgid for one locale the first wins and a differing
second translation is reported as a conflict.
"""
import argparse
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
    return {e.msgid for e in poutil.parse(TEMPLATE) if e.msgid and not e.obsolete}


class MainCatalogues:
    """Each main catalogue parsed once, with the wrong-language index built from them."""

    def __init__(self):
        self._entries = {}
        self._values = None

    def entries(self, locale):
        if locale not in self._entries:
            self._entries[locale] = poutil.parse(poutil.po_path(locale))
        return self._entries[locale]

    def index(self, locale):
        return {e.msgid: e for e in self.entries(locale) if not e.obsolete}

    def nplurals(self, locale):
        rule = poutil.header_plural_rule(self.entries(locale))
        return poutil.plural_spec(rule)[0] if rule else None

    def others(self, msgid):
        """{locale: value} for one msgid across every main catalogue."""
        if self._values is None:
            self._values = {}
            for po in glob.glob(os.path.join(poutil.ROOT, 'locale', '*', 'LC_MESSAGES',
                                             'messages.po')):
                loc = po.split(os.sep)[-3]
                for e in self.entries(loc):
                    if e.obsolete or not e.msgid:
                        continue
                    value = entry_value(e)
                    if value:
                        self._values.setdefault(e.msgid, {}).setdefault(loc, value)
        return self._values.get(msgid, {})


def entry_value(e):
    """Comparable translation: the msgstr, or the tuple of plural forms."""
    if e.msgid_plural:
        forms = tuple(e.plurals[n] for n in sorted(e.plurals))
        return forms if any(forms) else None
    return e.msgstr or None


def render_value(value):
    return repr(value if isinstance(value, str) else list(value))


def build_parser():
    parser = argparse.ArgumentParser(
        description='Move translations that only exist in a module catalogue into the main one.',
        allow_abbrev=False)
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would move, change nothing')
    parser.add_argument('--module', metavar='NAME', help='only this module')
    parser.add_argument('--locale', metavar='LOCALE', help='only this locale')
    parser.add_argument('--include-stale', action='store_true',
                        help='also import msgids missing from the template')
    parser.add_argument('--force', action='store_true',
                        help='import even candidates the wrong-language guard rejected')
    return parser


def collect(args, main):
    """Walk the module catalogues. Returns the candidate list and the report buckets."""
    tmpl = template_msgids()
    if tmpl is None:
        print(f'{YELLOW}Warning: template not found, cannot skip stale msgids{NC}', file=sys.stderr)

    pattern = os.path.join(poutil.ROOT, 'lib', 'Module', '*', 'locale', '*', 'messages.po')
    candidates = []          # (module, locale, entry, value, kind)
    seen = {}                # (locale, msgid) -> (module, value)
    report = {'stale': [], 'rejected': [], 'unharvested': [], 'conflicts': []}

    for po in sorted(glob.glob(pattern)):
        parts = po.split(os.sep)
        module, locale = parts[-4], parts[-2]
        if args.module and module != args.module:
            continue
        if args.locale and locale != args.locale:
            continue
        if not os.path.exists(poutil.po_path(locale)):
            continue
        index = main.index(locale)

        for e in poutil.parse(po):
            if e.obsolete or not e.msgid:
                continue
            value = entry_value(e)
            if not value or poutil.is_untranslated(e, locale):
                continue                       # module has nothing real to give

            existing = index.get(e.msgid)
            if existing is None:
                kind = 'absent'
            elif poutil.is_untranslated(existing, locale):
                kind = 'untranslated'
            else:
                continue                       # main already has a real translation

            if tmpl is not None and e.msgid not in tmpl and not args.include_stale:
                report['stale'].append((module, locale, e.msgid))
                continue

            if e.msgid_plural:
                want = main.nplurals(locale)
                if want is None:
                    report['unharvested'].append(
                        (module, locale, e.msgid, 'main catalogue declares no Plural-Forms'))
                    continue
                if len(value) != want or (existing is not None and not existing.msgid_plural):
                    why = (f'module has {len(value)} plural form(s), main expects {want}'
                           if len(value) != want else 'main entry is not a plural entry')
                    report['unharvested'].append((module, locale, e.msgid, why))
                    continue

            # Wrong-language guard: identical to another locale's translation.
            clash = [loc for loc, val in main.others(e.msgid).items()
                     if val == value and loc != locale and loc != 'en_EN']
            if clash and not args.force:
                report['rejected'].append((module, locale, e.msgid, value, clash))
                continue

            key = (locale, e.msgid)
            if key in seen:
                first_module, first_value = seen[key]
                if first_value != value:
                    report['conflicts'].append(
                        (locale, e.msgid, first_module, first_value, module, value))
                continue
            seen[key] = (module, value)
            candidates.append((module, locale, e, value, kind))
    return candidates, report


def apply_locale(main, locale, rows):
    """Merge one locale's candidates and write the catalogue once."""
    main_po = poutil.po_path(locale)
    entries = main.entries(locale)
    index = main.index(locale)
    appended = []
    for e, value, kind in rows:
        target = index.get(e.msgid) if kind == 'untranslated' else None
        if target is None:
            appended.append((e, value))
            continue
        if e.msgid_plural:
            for n, text in enumerate(value):
                target.set_plural(n, text)
        else:
            target.msgstr = value
        target.remove_flags('fuzzy', 'auto-english-fallback')

    text = poutil.render(entries)
    if appended:
        text = text.rstrip('\n') + '\n'
        for e, value in appended:
            block = f'\nmsgid "{poutil.format_string(e.msgid)}"\n'
            if e.msgid_plural:
                block += f'msgid_plural "{poutil.format_string(e.msgid_plural)}"\n'
                block += ''.join(f'msgstr[{n}] "{poutil.format_string(t)}"\n'
                                 for n, t in enumerate(value))
            else:
                block += f'msgstr "{poutil.format_string(value)}"\n'
            text += block
    with open(main_po, 'w', encoding='utf-8') as fh:
        fh.write(text)


def main(argv=None):
    args = build_parser().parse_args(argv)
    catalogues = MainCatalogues()
    candidates, report = collect(args, catalogues)

    if report['stale']:
        print(f'{BLUE}Skipped {len(report["stale"])} stale msgid(s) not in the template '
              f'(use --include-stale to import):{NC}')
        for module, locale, msgid in report['stale'][:10]:
            print(f'  {module}/{locale} {msgid!r}')
        if len(report['stale']) > 10:
            print(f'  ... and {len(report["stale"]) - 10} more')

    if report['rejected']:
        print(f'\n{RED}Rejected {len(report["rejected"])} candidate(s) - text matches another '
              f'locale (likely wrong language). Use --force to import anyway:{NC}')
        for module, locale, msgid, value, clash in report['rejected']:
            print(f'  {module}/{locale} {msgid!r} -> {render_value(value)} '
                  f'(same as {", ".join(clash)})')

    if report['unharvested']:
        print(f'\n{YELLOW}{len(report["unharvested"])} plural entr(ies) could not be harvested:{NC}')
        for module, locale, msgid, why in report['unharvested']:
            print(f'  {module}/{locale} {msgid!r}: {why}')

    if report['conflicts']:
        print(f'\n{YELLOW}{len(report["conflicts"])} conflict(s) - two modules supply different '
              f'translations; the first one is kept:{NC}')
        for locale, msgid, m1, v1, m2, v2 in report['conflicts']:
            print(f'  {locale} {msgid!r}: {m1}={render_value(v1)} kept, '
                  f'{m2}={render_value(v2)} ignored')

    if not candidates:
        print(f'\n{GREEN}Nothing to harvest.{NC}')
        return 0

    print(f'\n{BLUE}{len(candidates)} translation(s) to move into the main catalogue:{NC}')
    for module, locale, e, value, kind in candidates:
        print(f'  [{kind:12}] {module}/{locale} {e.msgid!r} -> {render_value(value)}')

    if args.dry_run:
        print(f'\n{YELLOW}Dry run - nothing written.{NC}')
        return 0

    by_locale = {}
    for module, locale, e, value, kind in candidates:
        by_locale.setdefault(locale, []).append((e, value, kind))

    for locale, rows in sorted(by_locale.items()):
        apply_locale(catalogues, locale, rows)
        print(f'{GREEN}  {locale}: {len(rows)} translation(s) merged{NC}')

    print(f'\n{GREEN}Done. Recompile with: python3 scripts/compile_messages.py{NC}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
