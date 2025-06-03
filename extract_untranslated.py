#!/usr/bin/env python3
"""
Extract untranslated messages from a .po file for translation.

Usage: python extract_untranslated.py <locale>
Example: python extract_untranslated.py fr_FR
"""

import sys
import os
import re
import json
from pathlib import Path


class PoEntry:
    def __init__(self):
        self.comments = []
        self.locations = []
        self.flags = []
        self.msgid = ""
        self.msgid_plural = ""
        self.msgstr = ""
        self.msgstr_plural = {}
        self.is_fuzzy = False
        self.is_untranslated = False


class PoParser:
    def __init__(self, file_path, exclusions=None):
        self.file_path = file_path
        self.entries = []
        self.exclusions = exclusions or []
        
    def parse(self):
        with open(self.file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by double newlines to separate entries
        blocks = re.split(r'\n\s*\n', content)
        
        for block in blocks:
            if not block.strip():
                continue
                
            entry = self._parse_block(block)
            if entry and entry.msgid:  # Skip header entry (empty msgid)
                self.entries.append(entry)
                
        return self.entries
    
    def _parse_block(self, block):
        entry = PoEntry()
        lines = block.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Comments and metadata
            if line.startswith('#.'):  # Translator comment
                entry.comments.append(line)
            elif line.startswith('#:'):  # Location
                entry.locations.append(line[2:].strip())
            elif line.startswith('#,'):  # Flags
                flags = line[2:].strip().split(',')
                entry.flags = [f.strip() for f in flags]
                if 'fuzzy' in entry.flags:
                    entry.is_fuzzy = True
            elif line.startswith('#'):  # Other comments
                entry.comments.append(line)
            
            # Message ID
            elif line.startswith('msgid '):
                msgid_lines = [self._extract_string(line[6:])]
                i += 1
                while i < len(lines) and lines[i].strip().startswith('"'):
                    msgid_lines.append(self._extract_string(lines[i].strip()))
                    i += 1
                entry.msgid = ''.join(msgid_lines)
                i -= 1
            
            # Message ID plural
            elif line.startswith('msgid_plural '):
                msgid_plural_lines = [self._extract_string(line[13:])]
                i += 1
                while i < len(lines) and lines[i].strip().startswith('"'):
                    msgid_plural_lines.append(self._extract_string(lines[i].strip()))
                    i += 1
                entry.msgid_plural = ''.join(msgid_plural_lines)
                i -= 1
            
            # Message string
            elif line.startswith('msgstr '):
                msgstr_lines = [self._extract_string(line[7:])]
                i += 1
                while i < len(lines) and lines[i].strip().startswith('"'):
                    msgstr_lines.append(self._extract_string(lines[i].strip()))
                    i += 1
                entry.msgstr = ''.join(msgstr_lines)
                i -= 1
            
            # Message string plural
            elif re.match(r'msgstr\[\d+\] ', line):
                match = re.match(r'msgstr\[(\d+)\] (.+)', line)
                if match:
                    index = int(match.group(1))
                    msgstr_lines = [self._extract_string(match.group(2))]
                    i += 1
                    while i < len(lines) and lines[i].strip().startswith('"'):
                        msgstr_lines.append(self._extract_string(lines[i].strip()))
                        i += 1
                    entry.msgstr_plural[index] = ''.join(msgstr_lines)
                    i -= 1
            
            i += 1
        
        # Check if untranslated
        if entry.msgid:
            if entry.msgid_plural:
                # For plural forms, check if any msgstr[n] is empty or same as msgid
                entry.is_untranslated = any(
                    not msgstr or msgstr == entry.msgid or msgstr == entry.msgid_plural
                    for msgstr in entry.msgstr_plural.values()
                )
            else:
                # For singular forms
                entry.is_untranslated = (
                    not entry.msgstr or 
                    entry.msgstr == entry.msgid
                )
        
        return entry
    
    def _extract_string(self, s):
        """Extract string content from quoted string."""
        s = s.strip()
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
            # Unescape common sequences
            s = s.replace('\\n', '\n')
            s = s.replace('\\t', '\t')
            s = s.replace('\\"', '"')
            s = s.replace('\\\\', '\\')
        return s

    def is_excluded(self, msgid):
        """Check if a message ID should be excluded from translation."""
        if not self.exclusions:
            return False
            
        # Direct match
        if msgid in self.exclusions:
            return True
            
        # Check if msgid is purely technical (only contains excluded terms)
        words = re.findall(r'\b\w+\b', msgid)
        if words and all(word.upper() in [e.upper() for e in self.exclusions] for word in words):
            return True
            
        # Check if msgid is very short and looks technical
        if len(msgid) <= 5 and msgid.isupper():
            return True
            
        return False


def load_exclusions():
    """Load technical exclusions from JSON file."""
    exclusions_file = Path(__file__).parent / "technical_exclusions.json"
    
    if not exclusions_file.exists():
        print(f"Warning: Exclusions file {exclusions_file} not found. Continuing without exclusions.")
        return []
    
    try:
        with open(exclusions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('exclusions', [])
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not load exclusions file: {e}")
        return []


def main():
    if len(sys.argv) < 2 or len(sys.argv) > 4:
        print("Usage: python extract_untranslated.py <locale> [limit] [--include-excluded]")
        print("Example: python extract_untranslated.py fr_FR")
        print("Example: python extract_untranslated.py fr_FR 50")
        print("Example: python extract_untranslated.py fr_FR 200 --include-excluded")
        sys.exit(1)
    
    locale = sys.argv[1]
    limit = None
    include_excluded = False
    
    # Parse additional arguments
    for arg in sys.argv[2:]:
        if arg == "--include-excluded":
            include_excluded = True
        elif arg.isdigit():
            limit = int(arg)
    
    po_file = Path(f"locale/{locale}/LC_MESSAGES/messages.po")
    
    if not po_file.exists():
        print(f"Error: File {po_file} does not exist")
        sys.exit(1)
    
    # Load exclusions unless explicitly disabled
    exclusions = [] if include_excluded else load_exclusions()
    
    print(f"Parsing {po_file}...")
    if exclusions and not include_excluded:
        print(f"Loaded {len(exclusions)} technical exclusions")
    
    parser = PoParser(po_file, exclusions)
    entries = parser.parse()
    
    # Separate untranslated and fuzzy entries
    untranslated = []
    fuzzy = []
    excluded_count = 0
    
    for entry in entries:
        if entry.is_fuzzy:
            if not parser.is_excluded(entry.msgid):
                fuzzy.append(entry)
            else:
                excluded_count += 1
        elif entry.is_untranslated:
            if not parser.is_excluded(entry.msgid):
                untranslated.append(entry)
            else:
                excluded_count += 1
    
    # Apply limit if specified
    if limit:
        untranslated = untranslated[:limit]
        fuzzy = fuzzy[:limit]
    
    # Prepare output data
    total_untranslated = len([e for e in entries if e.is_untranslated and not parser.is_excluded(e.msgid)])
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
                entry_data['current_translations'] = entry.msgstr_plural
                entry_data['translations'] = {}
                
            if entry.comments:
                entry_data['comments'] = entry.comments
                
            output_data['fuzzy_entries'].append(entry_data)
    
    # Write output file
    output_file = f"{locale}_untranslated.json"
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