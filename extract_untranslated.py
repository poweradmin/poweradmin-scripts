#!/usr/bin/env python3
"""
Extract untranslated messages from a .po file for translation.

Usage: python extract_untranslated.py <locale> [limit] [--include-excluded] [--module=ModuleName]
Example: python extract_untranslated.py fr_FR
Example: python extract_untranslated.py fr_FR --module=ZoneImportExport
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402


def parse_entries(po_file):
    """Entries carrying a msgid, in file order."""
    return [e for e in poutil.parse(po_file) if e.msgid and not e.obsolete]


def main():
    if len(sys.argv) < 2 or len(sys.argv) > 5:
        print("Usage: python extract_untranslated.py <locale> [limit] [--include-excluded] [--module=ModuleName]")
        print("Example: python extract_untranslated.py fr_FR")
        print("Example: python extract_untranslated.py fr_FR 50")
        print("Example: python extract_untranslated.py fr_FR 200 --include-excluded")
        print("Example: python extract_untranslated.py fr_FR --module=ZoneImportExport")
        sys.exit(1)

    locale = sys.argv[1]
    limit = None
    include_excluded = False
    module_name = None

    # Parse additional arguments
    for arg in sys.argv[2:]:
        if arg == "--include-excluded":
            include_excluded = True
        elif arg.startswith("--module="):
            module_name = arg.split("=", 1)[1]
        elif arg.isdigit():
            limit = int(arg)

    if module_name:
        po_file = Path(f"lib/Module/{module_name}/locale/{locale}/messages.po")
    else:
        po_file = Path(f"locale/{locale}/LC_MESSAGES/messages.po")
    
    if not po_file.exists():
        print(f"Error: File {po_file} does not exist")
        sys.exit(1)
    
    # Load exclusions unless explicitly disabled
    exclusions = [] if include_excluded else poutil.load_exclusions()
    
    print(f"Parsing {po_file}...")
    if exclusions and not include_excluded:
        print(f"Loaded {len(exclusions)} technical exclusions")
    
    entries = parse_entries(po_file)
    untranslated_flags = {id(e): poutil.is_untranslated(e, locale) for e in entries}
    
    # Separate untranslated and fuzzy entries
    untranslated = []
    fuzzy = []
    excluded_count = 0
    
    for entry in entries:
        if entry.is_fuzzy:
            if not poutil.is_excluded(entry.msgid, exclusions):
                fuzzy.append(entry)
            else:
                excluded_count += 1
        elif untranslated_flags[id(entry)]:
            if not poutil.is_excluded(entry.msgid, exclusions):
                untranslated.append(entry)
            else:
                excluded_count += 1
    
    # Apply limit if specified
    if limit:
        untranslated = untranslated[:limit]
        fuzzy = fuzzy[:limit]
    
    # Prepare output data
    total_untranslated = len([e for e in entries
                              if untranslated_flags[id(e)] and not poutil.is_excluded(e.msgid, exclusions)])
    output_data = {
        'locale': locale,
        'untranslated_count': len(untranslated),
        'fuzzy_count': len(fuzzy),
        'total_untranslated': total_untranslated,
        'excluded_count': excluded_count,
        'entries': []
    }
    
    # Add untranslated entries
    for entry in untranslated:
        entry_data = {
            'locations': entry.locations,
            'msgid': entry.msgid,
            'translation': ''
        }
        
        if entry.msgid_plural:
            entry_data['msgid_plural'] = entry.msgid_plural
            entry_data['translations'] = {}  # For plural forms
            
        if entry.comments:
            entry_data['comments'] = entry.comments
            
        output_data['entries'].append(entry_data)
    
    # Add fuzzy entries in a separate section
    if fuzzy:
        output_data['fuzzy_entries'] = []
        for entry in fuzzy:
            entry_data = {
                'locations': entry.locations,
                'msgid': entry.msgid,
                'current_translation': entry.msgstr,
                'translation': ''
            }
            
            if entry.msgid_plural:
                entry_data['msgid_plural'] = entry.msgid_plural
                entry_data['current_translations'] = entry.plurals
                entry_data['translations'] = {}
                
            if entry.comments:
                entry_data['comments'] = entry.comments
                
            output_data['fuzzy_entries'].append(entry_data)
    
    # Write output file
    output_file = f"{module_name}_{locale}_untranslated.json" if module_name else f"{locale}_untranslated.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nExtraction complete!")
    if limit and 'total_untranslated' in output_data:
        print(f"- Untranslated entries: {len(untranslated)} (limited from {output_data['total_untranslated']})")
    else:
        print(f"- Untranslated entries: {len(untranslated)}")
    print(f"- Fuzzy entries: {len(fuzzy)}")
    if excluded_count > 0:
        print(f"- Excluded technical terms: {excluded_count}")
    print(f"- Output saved to: {output_file}")
    
    # Show a few examples
    if untranslated:
        print("\nExample untranslated entries:")
        for i, entry in enumerate(untranslated[:3]):
            print(f"\n{i+1}. {entry.locations[0] if entry.locations else 'No location'}")
            print(f"   msgid: {entry.msgid[:80]}{'...' if len(entry.msgid) > 80 else ''}")


if __name__ == "__main__":
    main()