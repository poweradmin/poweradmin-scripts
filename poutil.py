#!/usr/bin/env python3
"""Shared .po parsing for the locale scripts.

Every tool here used to carry its own msgid/msgstr parser, which had drifted apart
(multi-line msgids truncated in some, different rules for what counts as
untranslated). This module is the single implementation.

Rewriting is deliberately conservative: an entry that was not modified is written
back byte for byte, so running a tool over a locale only touches what it changed.

    entries = poutil.parse(path)
    for e in entries:
        if e.msgid == "Save":
            e.msgstr = "Gem"
    poutil.write(path, entries)
"""
import json
import os
import re
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PLURAL_RE = re.compile(r'^msgstr\[(\d+)\]\s*(.*)$')


def extract_string(s):
    """Unquote and unescape one quoted .po string fragment."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        s = s[1:-1]
        s = s.replace('\\n', '\n')
        s = s.replace('\\t', '\t')
        s = s.replace('\\"', '"')
        s = s.replace('\\\\', '\\')
    return s


def format_string(text):
    """Escape a Python string for use inside .po quotes."""
    return (text.replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace('\n', '\\n')
                .replace('\t', '\\t'))


class Entry:
    """One .po block. Assigning msgstr or plurals marks it dirty for rewriting."""

    __slots__ = ('raw', 'sep', 'msgid', 'msgid_plural', 'locations', 'flags',
                 'obsolete', '_msgstr', '_plurals', '_dirty')

    def __init__(self, raw, sep=''):
        self.raw = raw
        self.sep = sep
        self.msgid = ''
        self.msgid_plural = ''
        self.locations = []
        self.flags = []
        self.obsolete = False
        self._msgstr = ''
        self._plurals = {}
        self._dirty = False

    @property
    def msgstr(self):
        return self._msgstr

    @msgstr.setter
    def msgstr(self, value):
        if value != self._msgstr:
            self._msgstr = value
            self._dirty = True

    @property
    def plurals(self):
        return self._plurals

    def set_plural(self, index, value):
        if self._plurals.get(index) != value:
            self._plurals[index] = value
            self._dirty = True

    @property
    def is_header(self):
        return self.msgid == '' and not self.obsolete

    @property
    def dirty(self):
        return self._dirty

    def render(self):
        """Original text when untouched, otherwise the block with a rebuilt msgstr."""
        if not self._dirty:
            return self.raw

        lines = self.raw.split('\n')
        cut = None
        for i, line in enumerate(lines):
            if line.startswith('msgstr'):
                cut = i
                break
        if cut is None:
            return self.raw

        head = '\n'.join(lines[:cut])
        if self._plurals:
            body = '\n'.join(
                f'msgstr[{n}] "{format_string(self._plurals[n])}"'
                for n in sorted(self._plurals)
            )
        else:
            body = f'msgstr "{format_string(self._msgstr)}"'
        return head + '\n' + body if head else body


def _parse_block(raw, sep):
    entry = Entry(raw, sep)
    lines = raw.split('\n')

    if any(line.startswith('#~') for line in lines):
        entry.obsolete = True
        return entry

    def collect(first, start):
        """Join a quoted value with its continuation lines. Returns (text, next_index)."""
        parts = [extract_string(first)]
        i = start
        while i < len(lines) and lines[i].strip().startswith('"'):
            parts.append(extract_string(lines[i]))
            i += 1
        return ''.join(parts), i

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith('#:'):
            entry.locations.append(stripped[2:].strip())
            i += 1
        elif stripped.startswith('#,'):
            entry.flags = [f.strip() for f in stripped[2:].split(',') if f.strip()]
            i += 1
        elif stripped.startswith('msgid_plural '):
            entry.msgid_plural, i = collect(stripped[13:], i + 1)
        elif stripped.startswith('msgid '):
            entry.msgid, i = collect(stripped[6:], i + 1)
        elif stripped == 'msgid ""':
            entry.msgid, i = collect('""', i + 1)
        elif _PLURAL_RE.match(stripped):
            m = _PLURAL_RE.match(stripped)
            text, i = collect(m.group(2), i + 1)
            entry._plurals[int(m.group(1))] = text
        elif stripped.startswith('msgstr'):
            entry._msgstr, i = collect(stripped[6:], i + 1)
        else:
            i += 1

    return entry


def parse_string(content):
    """Parse .po text into Entry objects, preserving the separators between them."""
    chunks = re.split(r'(\n\s*\n)', content)
    entries = []
    i = 0
    while i < len(chunks):
        raw = chunks[i]
        sep = chunks[i + 1] if i + 1 < len(chunks) else ''
        if raw.strip():
            entries.append(_parse_block(raw, sep))
        elif raw:
            # trailing whitespace-only chunk: keep it so write() round-trips
            blank = Entry(raw, sep)
            blank.obsolete = True
            entries.append(blank)
        i += 2
    return entries


def parse(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return parse_string(fh.read())


def render(entries):
    return ''.join(e.render() + e.sep for e in entries)


def backup(path):
    """Timestamped copy alongside the original. Returns the backup path."""
    dest = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(path, dest)
    return dest


def write(path, entries, make_backup=False):
    if make_backup:
        backup(path)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(render(entries))


def po_path(locale, module=None):
    if module:
        return os.path.join(ROOT, 'lib/Module', module, 'locale', locale, 'messages.po')
    return os.path.join(ROOT, 'locale', locale, 'LC_MESSAGES', 'messages.po')


def locales():
    base = os.path.join(ROOT, 'locale')
    return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))


def load_exclusions():
    """Technical terms that are not expected to be translated."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'technical_exclusions.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh).get('exclusions', [])


def is_excluded(msgid, exclusions):
    if not exclusions:
        return False
    if msgid in exclusions:
        return True
    upper = {e.upper() for e in exclusions}
    words = re.findall(r'\b\w+\b', msgid)
    if words and all(w.upper() in upper for w in words):
        return True
    # Short all-caps strings are acronyms, not prose
    return len(msgid) <= 5 and msgid.isupper()


def is_untranslated(entry, locale=None):
    """Empty msgstr, or msgstr echoing the msgid.

    en_EN is exempt from the echo rule: there the two are identical by definition.
    The old extract_untranslated.py applied the rule to every locale and so
    reported the whole English catalogue as untranslated.
    """
    if entry.obsolete or entry.is_header or not entry.msgid:
        return False
    if entry.msgid_plural:
        return not all(entry.plurals.get(n) for n in entry.plurals) or not entry.plurals
    if not entry.msgstr:
        return True
    if locale == 'en_EN':
        return False
    return entry.msgstr == entry.msgid
