#!/usr/bin/env python3
"""Shared .po parsing for the locale scripts.

The single msgid/msgstr parser for this toolchain, including the rule for what
counts as untranslated.

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
                 'comments', 'obsolete', '_msgstr', '_plurals', '_dirty',
                 '_flags_dirty')

    def __init__(self, raw, sep=''):
        self.raw = raw
        self.sep = sep
        self.msgid = ''
        self.msgid_plural = ''
        self.locations = []
        self.flags = []
        self.comments = []
        self.obsolete = False
        self._msgstr = ''
        self._plurals = {}
        self._dirty = False
        self._flags_dirty = False

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
    def is_fuzzy(self):
        return 'fuzzy' in self.flags

    def clear_fuzzy(self):
        """Drop the fuzzy flag. Returns True when the entry actually had it."""
        return self.remove_flags('fuzzy')

    def remove_flags(self, *names):
        """Drop flags and mark the flag line for rewrite.

        Assigning to `flags` directly is not enough: render() only rewrites the
        comment block when `_flags_dirty` is set, so a stale `#, fuzzy` or
        `#, auto-english-fallback` would survive into the written file.
        Returns True when the entry actually carried one of them.
        """
        keep = [f for f in self.flags if f not in names]
        if keep == self.flags:
            return False
        self.flags = keep
        self._dirty = True
        self._flags_dirty = True
        return True

    def _render_head(self, lines):
        """Comment/msgid portion, with the flag line rewritten when flags changed."""
        if not self._flags_dirty:
            return lines
        out = []
        for line in lines:
            if line.strip().startswith('#,'):
                if self.flags:
                    out.append('#, ' + ', '.join(self.flags))
                # an empty flag list means the line is dropped entirely
            else:
                out.append(line)
        return out

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

        head = '\n'.join(self._render_head(lines[:cut]))
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
        elif stripped.startswith('#'):
            entry.comments.append(stripped)
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


def line_spans(entries):
    """1-based (first_line, last_line) per entry, matching the on-disk layout.

    Lets tools translate a line number reported by msgfmt back to the entry that
    owns it, without a second parser.
    """
    spans = []
    line = 1
    for e in entries:
        n = e.raw.count('\n')
        spans.append((line, line + n))
        line += n + e.sep.count('\n')
    return spans


def find_by_line(entries, lineno, spans=None):
    """The entry containing lineno, or the nearest preceding one. None if before all."""
    spans = spans or line_spans(entries)
    found = None
    for entry, (start, end) in zip(entries, spans):
        if start <= lineno <= end:
            return entry
        if start <= lineno:
            found = entry
    return found


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


def plural_rule(iso):
    """The Plural-Forms rule for an ISO-639 code, from plural_forms.json.

    Raises KeyError for an unknown code. Callers must not substitute a default:
    "nplurals=2" is wrong for every 3-, 4-, 5- and 6-form language, and silently
    wrong headers are how a new catalogue ends up unable to hold its own plurals.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plural_forms.json')
    with open(path, 'r', encoding='utf-8') as fh:
        rules = json.load(fh)['rules']
    if iso not in rules:
        raise KeyError(f'no plural rule for {iso!r} in plural_forms.json - look it up in the '
                       f'GNU gettext manual and add it there rather than guessing')
    return rules[iso]


def header_plural_rule(entries):
    """The Plural-Forms rule a catalogue declares, or None.

    Read this rather than matching the raw file: 12 catalogues wrap the header
    across several quoted lines, which a single-line regex reads as absent.
    """
    header = next((e for e in entries if e.is_header), None)
    if header is None:
        return None
    for line in header.msgstr.split('\n'):
        if line.startswith('Plural-Forms:'):
            return line.split(':', 1)[1].strip()
    return None


def _strip_outer_parens(expr):
    """Drop parentheses that wrap the whole expression.

    Several rules are written `(n==0 ? 0 : ...)`, which would otherwise hide
    every `?` below the top level and defeat the scan.
    """
    expr = expr.strip()
    while expr.startswith('(') and expr.endswith(')'):
        depth = 0
        for i, ch in enumerate(expr):
            depth += (ch == '(') - (ch == ')')
            if depth == 0 and i < len(expr) - 1:
                return expr
        expr = expr[1:-1].strip()
    return expr


def _c_ternary_to_python(expr):
    """Rewrite C `cond ? a : b` as Python `a if cond else b`, innermost last.

    `?:` is the loosest operator in both languages and `&&`/`||` map straight
    onto `and`/`or`, so no other precedence work is needed.
    """
    expr = _strip_outer_parens(expr)
    depth = 0
    for i, ch in enumerate(expr):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '?' and depth == 0:
            pending = 0
            for j in range(i + 1, len(expr)):
                if expr[j] == '(':
                    depth += 1
                elif expr[j] == ')':
                    depth -= 1
                elif depth == 0 and expr[j] == '?':
                    pending += 1
                elif depth == 0 and expr[j] == ':':
                    if pending == 0:
                        cond, yes, no = expr[:i], expr[i + 1:j], expr[j + 1:]
                        return (f'(({_c_ternary_to_python(yes)}) if ({cond}) '
                                f'else ({_c_ternary_to_python(no)}))')
                    pending -= 1
            break
    return expr


def plural_spec(rule):
    """Return (nplurals, f) where f(n) is the form index the rule selects."""
    count = int(re.search(r'nplurals\s*=\s*(\d+)', rule).group(1))
    expr = re.search(r'plural\s*=\s*(.+?);?\s*$', rule).group(1).strip()
    body = _c_ternary_to_python(expr).replace('&&', ' and ').replace('||', ' or ')
    code = compile(body, '<plural-forms>', 'eval')
    return count, lambda n: int(eval(code, {'__builtins__': {}}, {'n': n}))  # noqa: S307


def same_plural_rule(a, b, limit=201):
    """True when two rules select the same form for every n below limit.

    Compare this way rather than by string equality: ru_RU and uk_UA ship two
    different spellings of the identical Russian rule.
    """
    (count_a, pick_a), (count_b, pick_b) = plural_spec(a), plural_spec(b)
    return count_a == count_b and all(pick_a(n) == pick_b(n) for n in range(limit))


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
    """
    if entry.obsolete or entry.is_header or not entry.msgid:
        return False
    if entry.msgid_plural:
        # The echo rule has to reach plural forms too. Without it a form holding
        # the raw English reads as translated because it is merely non-empty,
        # which is how 314 of them survived every earlier catalogue pass.
        if not entry.plurals or not all(entry.plurals.get(n) for n in entry.plurals):
            return True
        if locale == 'en_EN':
            return False
        return any(v in (entry.msgid, entry.msgid_plural) for v in entry.plurals.values())
    if not entry.msgstr:
        return True
    if locale == 'en_EN':
        return False
    return entry.msgstr == entry.msgid
