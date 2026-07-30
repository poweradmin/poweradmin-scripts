#!/usr/bin/env python3
"""
Check all locales for empty translations and untranslated strings.

Scans all .po files for:
- Empty msgstr (msgstr "") that should have translations
- Strings where msgstr equals msgid (untranslated, copied from source)
- Empty plural forms (msgstr[n] = "")

Excludes technical terms listed in scripts/technical_exclusions.json.

Usage: python scripts/check_translations.py [--verbose] [--module=ModuleName]
Exit code: 0 if all translations are complete, 1 if issues found.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402


def parse_po_file(filepath):
    """Entries carrying a msgid, in file order."""
    return [e for e in poutil.parse(filepath) if e.msgid and not e.obsolete]


def check_entry(entry, exclusions, lang):
    """Check an entry for translation issues. Returns list of issue tuples."""
    issues = []
    msgid = entry.msgid

    if entry.obsolete or not msgid:
        return issues

    if poutil.is_excluded(msgid, exclusions):
        return issues

    # Skip en_EN for msgid==msgstr checks (English source = English target is expected)
    is_english = lang == 'en_EN'

    if entry.msgid_plural:
        for idx, msgstr in entry.plurals.items():
            if not msgstr:
                issues.append(('empty_plural', msgid, f'msgstr[{idx}] is empty'))
            elif not is_english and msgstr == msgid:
                issues.append(('untranslated_plural', msgid, f'msgstr[{idx}] equals msgid (not translated)'))
    else:
        if not entry.msgstr:
            issues.append(('empty', msgid, 'msgstr is empty'))
        elif not is_english and entry.msgstr == msgid:
            issues.append(('untranslated', msgid, 'msgstr equals msgid (not translated)'))

    return issues


def main():
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    module_name = None
    for arg in sys.argv[1:]:
        if arg.startswith('--module='):
            module_name = arg.split('=', 1)[1]

    # Find project root (go up from scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    os.chdir(project_root)

    exclusions = poutil.load_exclusions()

    if module_name:
        locale_base = Path(f'lib/Module/{module_name}/locale')
    else:
        locale_base = Path('locale')

    if not locale_base.exists():
        print(f"Error: {locale_base} does not exist")
        sys.exit(1)

    total_issues = 0
    total_locales = 0
    clean_locales = 0

    print(f"Checking translations in {locale_base}/")
    print(f"Loaded {len(exclusions)} technical exclusions")
    print()

    for lang_dir in sorted(locale_base.iterdir()):
        if not lang_dir.is_dir():
            continue

        if module_name:
            po_file = lang_dir / 'messages.po'
        else:
            po_file = lang_dir / 'LC_MESSAGES' / 'messages.po'

        if not po_file.exists():
            continue

        lang = lang_dir.name
        total_locales += 1

        entries = parse_po_file(po_file)
        empty_count = 0
        untranslated_count = 0
        issues_detail = []

        for entry in entries:
            entry_issues = check_entry(entry, exclusions, lang)
            for issue_type, msgid, desc in entry_issues:
                if 'empty' in issue_type:
                    empty_count += 1
                else:
                    untranslated_count += 1
                issues_detail.append((issue_type, msgid, desc, entry.locations))

        locale_issues = empty_count + untranslated_count
        total_issues += locale_issues

        if locale_issues == 0:
            clean_locales += 1
            if verbose:
                print(f"  {lang:8s}: OK ({len(entries)} entries)")
            else:
                print(f"  {lang:8s}: OK")
        else:
            print(f"  {lang:8s}: {empty_count} empty, {untranslated_count} untranslated (msgstr=msgid)")
            if verbose:
                for issue_type, msgid, desc, locations in issues_detail:
                    loc_str = locations[0] if locations else 'unknown'
                    truncated = msgid[:60] + '...' if len(msgid) > 60 else msgid
                    print(f"           [{issue_type}] {loc_str}")
                    print(f"             \"{truncated}\"")

    print()
    print(f"Summary: {total_locales} locales, {clean_locales} clean, {total_issues} total issues")

    if total_issues > 0:
        print(f"\nRun with --verbose for details on each issue.")
        sys.exit(1)
    else:
        print("\nAll translations are complete.")
        sys.exit(0)


if __name__ == "__main__":
    main()
