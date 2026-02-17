#!/usr/bin/env python3
"""
Import translations back into a .po file from a JSON file.

Usage: python import_translations.py <json_file> [--module=ModuleName]
Example: python import_translations.py fr_FR_untranslated.json
Example: python import_translations.py ZoneImportExport_fr_FR_untranslated.json --module=ZoneImportExport
"""

import sys
import os
import re
import json
import shutil
from datetime import datetime
from pathlib import Path


class PoUpdater:
    def __init__(self, po_file, translations_data):
        self.po_file = po_file
        self.translations_data = translations_data
        self.content = ""
        self.updated_count = 0
        self.fuzzy_cleared_count = 0
        
    def update(self):
        # Create backup
        backup_file = f"{self.po_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(self.po_file, backup_file)
        print(f"Created backup: {backup_file}")
        
        # Read the original file
        with open(self.po_file, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        # Create translation lookup maps
        translations_map = {}
        fuzzy_map = {}
        
        # Process regular entries
        for entry in self.translations_data.get('entries', []):
            if entry.get('translation'):
                translations_map[entry['msgid']] = entry
        
        # Process fuzzy entries
        for entry in self.translations_data.get('fuzzy_entries', []):
            if entry.get('translation'):
                fuzzy_map[entry['msgid']] = entry
        
        # Process the content
        updated_content = self._process_content(translations_map, fuzzy_map)
        
        # Write the updated file
        with open(self.po_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        print(f"\nUpdate complete!")
        print(f"- Translations updated: {self.updated_count}")
        print(f"- Fuzzy flags cleared: {self.fuzzy_cleared_count}")
        
        return True
    
    def _process_content(self, translations_map, fuzzy_map):
        # Split content into blocks
        blocks = re.split(r'(\n\s*\n)', self.content)
        updated_blocks = []
        
        for i, block in enumerate(blocks):
            if not block.strip():
                updated_blocks.append(block)
                continue
            
            # Parse the block to extract msgid
            msgid = self._extract_msgid(block)
            
            if msgid and (msgid in translations_map or msgid in fuzzy_map):
                # This block needs to be updated
                if msgid in translations_map:
                    updated_block = self._update_block(block, translations_map[msgid], False)
                else:
                    updated_block = self._update_block(block, fuzzy_map[msgid], True)
                updated_blocks.append(updated_block)
            else:
                updated_blocks.append(block)
        
        return ''.join(updated_blocks)
    
    def _extract_msgid(self, block):
        """Extract msgid from a block."""
        lines = block.strip().split('\n')
        msgid_lines = []
        in_msgid = False
        
        for line in lines:
            if line.strip().startswith('msgid "'):
                in_msgid = True
                msgid_lines.append(self._extract_string(line[6:].strip()))
            elif in_msgid and line.strip().startswith('"'):
                msgid_lines.append(self._extract_string(line.strip()))
            elif in_msgid and not line.strip().startswith('"'):
                break
        
        return ''.join(msgid_lines)
    
    def _update_block(self, block, translation_entry, is_fuzzy):
        """Update a block with new translation."""
        lines = block.strip().split('\n')
        updated_lines = []
        
        # Track what we're currently parsing
        in_msgstr = False
        in_msgstr_plural = False
        current_plural_index = -1
        skip_next = False
        
        for i, line in enumerate(lines):
            if skip_next:
                skip_next = False
                continue
            
            # Remove fuzzy flag if this is a fuzzy entry being updated
            if is_fuzzy and line.strip().startswith('#,') and 'fuzzy' in line:
                flags = [f.strip() for f in line[2:].split(',') if f.strip() != 'fuzzy']
                if flags:
                    updated_lines.append(f"#, {', '.join(flags)}")
                self.fuzzy_cleared_count += 1
                continue
            
            # Handle msgstr for singular
            if line.strip().startswith('msgstr "') and 'msgid_plural' not in translation_entry:
                translation = translation_entry['translation']
                formatted_translation = self._format_string(translation)
                updated_lines.append(f'msgstr {formatted_translation[0]}')
                
                # Add continuation lines if needed
                for cont_line in formatted_translation[1:]:
                    updated_lines.append(cont_line)
                
                # Skip original msgstr continuation lines
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('"'):
                    j += 1
                skip_next = j - i - 1
                
                self.updated_count += 1
                in_msgstr = False
                
            # Handle msgstr[n] for plurals
            elif re.match(r'msgstr\[\d+\] ', line.strip()):
                match = re.match(r'msgstr\[(\d+)\] ', line.strip())
                if match and 'translations' in translation_entry:
                    index = int(match.group(1))
                    if str(index) in translation_entry['translations']:
                        translation = translation_entry['translations'][str(index)]
                        formatted_translation = self._format_string(translation)
                        updated_lines.append(f'msgstr[{index}] {formatted_translation[0]}')
                        
                        # Add continuation lines if needed
                        for cont_line in formatted_translation[1:]:
                            updated_lines.append(cont_line)
                        
                        # Skip original msgstr[n] continuation lines
                        j = i + 1
                        while j < len(lines) and lines[j].strip().startswith('"'):
                            j += 1
                        skip_next = j - i - 1
                        
                        self.updated_count += 1
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        return '\n'.join(updated_lines)
    
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
    
    def _format_string(self, s):
        """Format a string for .po file output."""
        # Escape special characters
        s = s.replace('\\', '\\\\')
        s = s.replace('"', '\\"')
        s = s.replace('\t', '\\t')
        
        # Split by newlines and format
        lines = s.split('\n')
        
        if len(lines) == 1 and len(s) < 70:
            # Single line, short enough
            return [f'"{s}"']
        else:
            # Multi-line or long string
            result = ['""']  # Empty first line
            for i, line in enumerate(lines):
                if i < len(lines) - 1:
                    result.append(f'"{line}\\n"')
                else:
                    if line:  # Don't add empty last line
                        result.append(f'"{line}"')
            return result


def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python import_translations.py <json_file> [--module=ModuleName]")
        print("Example: python import_translations.py fr_FR_untranslated.json")
        print("Example: python import_translations.py ZoneImportExport_fr_FR_untranslated.json --module=ZoneImportExport")
        sys.exit(1)

    json_file = sys.argv[1]
    module_name = None

    for arg in sys.argv[2:]:
        if arg.startswith("--module="):
            module_name = arg.split("=", 1)[1]

    if not os.path.exists(json_file):
        print(f"Error: File {json_file} does not exist")
        sys.exit(1)

    # Load translations
    print(f"Loading translations from {json_file}...")
    with open(json_file, 'r', encoding='utf-8') as f:
        translations_data = json.load(f)

    locale = translations_data.get('locale')
    if not locale:
        print("Error: No locale found in JSON file")
        sys.exit(1)

    # Find the .po file
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