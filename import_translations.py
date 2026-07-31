#!/usr/bin/env python3
"""
Import translations back into a .po file from a JSON file.

Usage: python import_translations.py <json_file> [--module=ModuleName]
       python import_translations.py <locale> --dict=<translations.json> [--module=ModuleName] [--force]

The first form imports from an extracted untranslated JSON file (from extract_untranslated.py).
The second form imports from a simple {msgid: translation} JSON dict directly into the .po file.
In that dict a plural msgid takes a {"0": form, "1": form, ...} map with one key per form the
locale declares; a bare string there is an error, not a skipped entry.

By default only entries still needing translation are filled. Pass --force to overwrite
existing translations too, which is what repairing corrupted machine output needs.

Examples:
  python import_translations.py fr_FR_untranslated.json
  python import_translations.py fr_FR --dict=translations.json
  python import_translations.py fr_FR --dict=translations.json --module=ZoneImportExport
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402


class PoUpdater:
    """Write translations from an extracted JSON payload back into a .po file."""

    def __init__(self, po_file, translations_data):
        self.po_file = po_file
        self.translations_data = translations_data
        self.updated_count = 0
        self.fuzzy_cleared_count = 0

    def update(self):
        entries = poutil.parse(self.po_file)
        print(f"Created backup: {poutil.backup(self.po_file)}")

        # A plural payload carries `translations`, never `translation`, so both keys
        # have to count here - filtering on `translation` alone silently discarded
        # every plural entry before it reached the loop below.
        def wanted(payload):
            return bool(payload.get('translation') or payload.get('translations'))

        regular = {e['msgid']: e for e in self.translations_data.get('entries', [])
                   if wanted(e)}
        fuzzy = {e['msgid']: e for e in self.translations_data.get('fuzzy_entries', [])
                 if wanted(e)}

        for entry in entries:
            if entry.obsolete or not entry.msgid:
                continue
            payload = regular.get(entry.msgid) or fuzzy.get(entry.msgid)
            if payload is None:
                continue

            if entry.msgid_plural and payload.get('translations'):
                for index_str, text in payload['translations'].items():
                    entry.set_plural(int(index_str), text)
                    self.updated_count += 1
            elif not entry.msgid_plural:
                entry.msgstr = payload['translation']
                self.updated_count += 1

            if entry.msgid in fuzzy and entry.clear_fuzzy():
                self.fuzzy_cleared_count += 1

        poutil.write(self.po_file, entries)

        print("\nUpdate complete!")
        print(f"- Translations updated: {self.updated_count}")
        print(f"- Fuzzy flags cleared: {self.fuzzy_cleared_count}")
        return True


def build_translations_data_from_dict(locale, dict_file, po_file, force=False):
    """Turn a flat {msgid: translation} dict into the extracted-JSON shape.

    A plural entry's value must be a {"0": form, "1": form, ...} map, one key per
    form the locale declares. A bare string there is rejected rather than skipped:
    silently ignoring it is how 314 plural forms stayed in English through every
    earlier translation pass.

    Only entries that still need translating are filled. That includes entries whose
    msgstr merely echoes the English msgid, not only those with an empty msgstr.
    """
    with open(dict_file, 'r', encoding='utf-8') as fh:
        trans_dict = json.load(fh)

    data = {'locale': locale, 'entries': [], 'fuzzy_entries': []}
    entries = poutil.parse(po_file)
    rule = poutil.header_plural_rule(entries)
    nplurals = poutil.plural_spec(rule)[0] if rule else None
    rejected = []

    for entry in entries:
        if entry.obsolete or not entry.msgid or entry.msgid not in trans_dict:
            continue
        if not (force or poutil.is_untranslated(entry, locale) or entry.is_fuzzy):
            continue
        value = trans_dict[entry.msgid]
        payload = {'msgid': entry.msgid}
        if entry.msgid_plural:
            if not isinstance(value, dict):
                rejected.append((entry.msgid, 'plural entry needs a {index: form} map, '
                                              'not a single string'))
                continue
            want = {str(i) for i in range(nplurals)} if nplurals else set(value)
            if {str(k) for k in value} != want:
                rejected.append((entry.msgid,
                                 f'has forms {sorted(value)}, locale declares {sorted(want)}'))
                continue
            payload['msgid_plural'] = entry.msgid_plural
            payload['translations'] = {str(k): v for k, v in value.items()}
        elif isinstance(value, dict):
            rejected.append((entry.msgid, 'singular entry given a {index: form} map'))
            continue
        else:
            payload['translation'] = value
        if entry.is_fuzzy:
            payload['current_translation'] = entry.msgstr
            data['fuzzy_entries'].append(payload)
        else:
            data['entries'].append(payload)

    if rejected:
        print(f"\nERROR: {len(rejected)} dict entries cannot be applied:")
        for msgid, why in rejected[:20]:
            print(f"  {msgid[:70]!r}\n      {why}")
        sys.exit(1)

    filled = len(data['entries']) + len(data['fuzzy_entries'])
    print(f"Matched {filled} entries from dict ({len(trans_dict) - filled} dict entries not needed)")
    return data


def main():
    if len(sys.argv) < 2:
        print("Usage: python import_translations.py <json_file> [--module=ModuleName]")
        print("       python import_translations.py <locale> --dict=<translations.json> [--module=ModuleName] [--force]")
        print()
        print("Examples:")
        print("  python import_translations.py fr_FR_untranslated.json")
        print("  python import_translations.py fr_FR --dict=translations.json")
        sys.exit(1)

    module_name = None
    dict_file = None
    force = '--force' in sys.argv[2:]

    for arg in sys.argv[2:]:
        if arg.startswith("--module="):
            module_name = arg.split("=", 1)[1]
        elif arg.startswith("--dict="):
            dict_file = arg.split("=", 1)[1]

    if dict_file:
        # Dict mode: first arg is locale
        locale = sys.argv[1]

        if not os.path.exists(dict_file):
            print(f"Error: File {dict_file} does not exist")
            sys.exit(1)

        if module_name:
            po_file = Path(f"lib/Module/{module_name}/locale/{locale}/messages.po")
        else:
            po_file = Path(f"locale/{locale}/LC_MESSAGES/messages.po")

        if not po_file.exists():
            print(f"Error: File {po_file} does not exist")
            sys.exit(1)

        print(f"Loading translations dict from {dict_file}...")
        translations_data = build_translations_data_from_dict(locale, dict_file, po_file, force)
    else:
        # Original mode: first arg is extracted JSON file
        json_file = sys.argv[1]

        if not os.path.exists(json_file):
            print(f"Error: File {json_file} does not exist")
            sys.exit(1)

        print(f"Loading translations from {json_file}...")
        with open(json_file, 'r', encoding='utf-8') as f:
            translations_data = json.load(f)

        locale = translations_data.get('locale')
        if not locale:
            print("Error: No locale found in JSON file")
            sys.exit(1)

        if module_name:
            po_file = Path(f"lib/Module/{module_name}/locale/{locale}/messages.po")
        else:
            po_file = Path(f"locale/{locale}/LC_MESSAGES/messages.po")

        if not po_file.exists():
            print(f"Error: File {po_file} does not exist")
            sys.exit(1)

    # Update the .po file
    updater = PoUpdater(po_file, translations_data)
    updater.update()

    if not module_name:
        print(f"\nDon't forget to compile the .po file to .mo:")
        print(f"  msgfmt locale/{locale}/LC_MESSAGES/messages.po -o locale/{locale}/LC_MESSAGES/messages.mo")


if __name__ == "__main__":
    main()