#!/usr/bin/env python3
"""Apply reviewed translation corrections to a catalogue, then verify the write.

Usage: python3 scripts/apply_review_corrections.py <locale> [--dir=DIR] [--plurals]

Reviewers emit JSON rather than editing .po files directly, because parallel
writes to one catalogue lose updates. This applies those files serially behind a
gate, and refuses to write anything unless every correction passes it - a single
failure aborts the whole locale so nothing lands half-applied.

  msgstr mode (default)   reads DIR/OUT_<locale>_*.json, each {msgid: translation}
  --plurals               reads DIR/OUT_<locale>_plr*.json, each
                          {msgid: {index: form}}, and writes msgstr[n]

DIR defaults to ./locale-review.

The gate holds a correction to the same standard the catalogue is checked
against: identical printf placeholders, HTML tags and [TOKEN]s, identical
leading and trailing whitespace, every identifier and IP literal from the source
still present, and every do-not-translate literal from dnt_glossary.json still
present. It also rejects corrections to entries that are untranslated English
fallbacks, since substituting words into English yields a mixed-language hybrid.
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

PRINTF = re.compile(r'%(?:\d+\$)?[sdfucxXob]|%%')
TAG = re.compile(r'</?(?:code|strong|em|b|i|u|a|br|p|span|div|ul|ol|li|small|sup|sub)\b[^<>]*>',
                 re.I)
TOKEN = re.compile(r'\[[A-Z0-9_]+\]')
IDENTIFIER = re.compile(
    r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b'
    r'|\b(?:dns|api|misc|db|ldap|mail|pdns)\.[a-z_.]+\b'
    r'|\b[\w-]+\.(?:php|html|twig|js|css|sql|dat|json|ya?ml|conf|ini)\b'
)
IPV4 = re.compile(r'(?<![0-9A-Za-z.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?'
                  r'(?![0-9A-Za-z]|\.[0-9A-Za-z])')
SLASH_SPACE = re.compile(r'\s*/\s*')

# Pass families in application order. Each reviewed the catalogue as the earlier
# ones left it, so it wins any disagreement with them; two files inside one family
# disagreeing is a real problem and still aborts. A family absent from this list
# ranks 0 and can never override, which is what keeps independent slices honest.
ORDER = ['term', 'dnt', 'id', 'cn', 'sty', 'idb', 'cnb', 'idc', 'cnc', 'sup', 'fix']


def load_dnt():
    """Glossary literals with their msgid-side matchers.

    '/', '\\', '.' and '-' belong to the token, so the boundaries never split
    templates/emails/custom/ or in-addr.arpa. A term carrying an uppercase letter
    matches case-sensitively, so the KEY record type does not fire on "key".
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dnt_glossary.json')
    with open(path, encoding='utf-8') as fh:
        glossary = json.load(fh)
    left, right = r'(?<![A-Za-z0-9_\\/-])', r'(?![A-Za-z0-9_\\/-])'
    return [(e['term'],
             re.compile(left + re.escape(e['term']) + right,
                        0 if any(c.isupper() for c in e['term']) else re.I),
             set(e.get('except_locales', {})))
            for e in glossary['literal']]


def placeholders(text):
    return sorted(re.sub(r'\d+\$', '', p) for p in PRINTF.findall(text))


def dnt_dropped(msgid, new, locale, dnt):
    """Glossary literals the source has and the correction does not."""
    # Casing and spacing around a slash are not this gate's business, so the
    # correction is searched case-insensitively with "SSL / TLS" folded back.
    haystack = SLASH_SPACE.sub('/', new).lower()
    return [term for term, pat, skip in dnt
            if locale not in skip and pat.search(msgid) and term.lower() not in haystack]


def _lead(text):
    return text[:len(text) - len(text.lstrip())]


def _trail(text):
    return text[len(text.rstrip()):]


def gate(msgid, new, old, locale, dnt):
    """Reasons this correction must not be applied, empty when it is safe."""
    bad = []
    if placeholders(msgid) != placeholders(new):
        bad.append('placeholder set differs from msgid')
    if sorted(TAG.findall(msgid)) != sorted(TAG.findall(new)):
        bad.append('HTML tags differ from msgid')
    if sorted(TOKEN.findall(msgid)) != sorted(TOKEN.findall(new)):
        bad.append('[TOKEN]s differ from msgid')
    # Exact runs, not merely "is there whitespace": these strings are concatenated
    # into sentences, so two leading spaces collapsing to one is real damage.
    if _lead(msgid) != _lead(new) or _trail(msgid) != _trail(new):
        bad.append('leading/trailing whitespace differs from msgid')
    missing = [t for t in set(IDENTIFIER.findall(msgid)) if t not in new]
    if missing:
        bad.append(f'identifiers dropped: {missing}')
    src_ips, new_ips = set(IPV4.findall(msgid)), set(IPV4.findall(new))
    if src_ips != new_ips:
        bad.append(f'IP literals differ: {sorted(src_ips)} vs {sorted(new_ips)}')
    dropped = dnt_dropped(msgid, new, locale, dnt)
    if dropped:
        bad.append(f'do-not-translate literals dropped: {dropped}')
    # old is None for plural forms: replacing an English form wholesale is the
    # point there, whereas editing an English msgstr yields a mixed-language hybrid.
    if old is not None and old == msgid:
        bad.append('entry is an untranslated English fallback')
    if not new.strip():
        bad.append('correction is empty')
    if new == msgid:
        bad.append('correction is still the English source')
    return bad


def report(problems, total, locale):
    print(f'REJECTED {len(problems)} of {total} corrections for {locale}:')
    for msgid, bad in problems[:25]:
        print(f'  {msgid[:70]!r}')
        for reason in bad:
            print(f'      {reason}')


def collect_msgstr(locale, review_dir):
    """Merge every OUT_<locale>_*.json, honouring the family override order."""
    def rank(path):
        match = re.search(r'_([a-z]+)\d*\.json$', path)
        family = match.group(1) if match else None
        return ORDER.index(family) + 1 if family in ORDER else 0

    paths = sorted(p for p in glob.glob(os.path.join(review_dir, f'OUT_{locale}_*.json'))
                   if not re.search(r'_plr\d*\.json$', p))
    proposals = {}
    for path in paths:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        for msgid, new in data.items():
            proposals.setdefault(msgid, []).append((rank(path), path, new))

    fixes, overrides = {}, 0
    for msgid, offers in proposals.items():
        top = max(r for r, _, _ in offers)
        winners = {new: path for r, path, new in offers if r == top}
        if len(winners) > 1:
            # Two files of equal standing reached different answers. A filename
            # tiebreak would pick one silently, so this needs a human - either fix
            # the input files or record the decision in a later-ranked family.
            names = ', '.join(sorted(os.path.basename(p) for p in winners.values()))
            raise SystemExit(f'CONFLICT: {names} disagree on {msgid[:60]!r}')
        fixes[msgid] = next(iter(winners))
        if any(r < top and new != fixes[msgid] for r, _, new in offers):
            overrides += 1
    if overrides:
        print(f'later pass overrode {overrides} earlier corrections')
    return fixes


def apply_msgstr(locale, path, entries, review_dir):
    by_id = {e.msgid: e for e in entries if not e.obsolete and not e.is_header}
    fixes = collect_msgstr(locale, review_dir)
    dnt = load_dnt()

    problems = []
    for msgid, new in fixes.items():
        entry = by_id.get(msgid)
        if entry is None:
            problems.append((msgid, ['msgid not in catalogue']))
        elif entry.msgstr != new:
            bad = gate(msgid, new, entry.msgstr, locale, dnt)
            if bad:
                problems.append((msgid, bad))
    if problems:
        report(problems, len(fixes), locale)
        return None

    def write():
        applied = 0
        for msgid, new in fixes.items():
            entry = by_id[msgid]
            if entry.msgstr == new:
                continue
            entry.msgstr = new
            entry.remove_flags('auto-english-fallback', 'fuzzy')
            applied += 1
        return applied

    return fixes, write


def apply_plurals(locale, path, entries, review_dir):
    by_id = {e.msgid: e for e in entries if not e.obsolete and not e.is_header}
    rule = poutil.header_plural_rule(entries)
    count = poutil.plural_spec(rule)[0] if rule else None

    # Plural files carry no family ranking, so any two of them proposing different
    # text for the same form is a disagreement between reviewers, not an override.
    fixes, source_of = {}, {}
    for name in sorted(glob.glob(os.path.join(review_dir, f'OUT_{locale}_plr*.json'))):
        with open(name, encoding='utf-8') as fh:
            for msgid, forms in json.load(fh).items():
                for index, form in forms.items():
                    key = (msgid, str(index))
                    if key in source_of and fixes[msgid][index] != form:
                        raise SystemExit(
                            f'CONFLICT: {os.path.basename(source_of[key])} and '
                            f'{os.path.basename(name)} disagree on form {index} of '
                            f'{msgid[:50]!r}')
                    fixes.setdefault(msgid, {})[index] = form
                    source_of[key] = name

    dnt = load_dnt()
    problems, planned = [], []
    for msgid, forms in fixes.items():
        entry = by_id.get(msgid)
        if entry is None:
            problems.append((msgid, ['msgid not in catalogue']))
            continue
        if not entry.msgid_plural:
            problems.append((msgid, ['not a plural entry']))
            continue
        for index, form in forms.items():
            i = int(index)
            # Bound below as well as above: set_plural(-1, ...) would write an
            # msgstr[-1] that gettext can never select.
            if i < 0 or (count is not None and i >= count):
                problems.append((msgid, [f'index {i} outside 0..{(count or 1) - 1}']))
                continue
            # gettext picks by index, so form 0 answers msgid and the rest answer
            # msgid_plural. Checking every form against msgid would reject correct
            # work wherever the two carry different placeholders.
            source = entry.msgid if i == 0 else entry.msgid_plural
            bad = gate(source, form, None, locale, dnt)
            if bad:
                problems.append((msgid, [f'[{i}] {reason}' for reason in bad]))
            elif entry.plurals.get(i) != form:
                planned.append((entry, i, form))
    if problems:
        report(problems, len(fixes), locale)
        return None

    def write():
        for entry, i, form in planned:
            entry.set_plural(i, form)
            entry.remove_flags('auto-english-fallback', 'fuzzy')
        return len(planned)

    return fixes, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('locale')
    parser.add_argument('--dir', default='locale-review',
                        help='directory holding the OUT_<locale>_*.json files')
    parser.add_argument('--plurals', action='store_true',
                        help='apply msgstr[n] forms instead of msgstr')
    args = parser.parse_args()

    path = poutil.po_path(args.locale)
    entries = poutil.parse(path)
    handler = apply_plurals if args.plurals else apply_msgstr
    result = handler(args.locale, path, entries, os.path.expanduser(args.dir))
    if result is None:
        return 1
    fixes, write = result

    # Snapshot immediately before writing rather than diffing HEAD: the working
    # tree usually already carries an earlier pass, and diffing HEAD reports those
    # as unexpected drift - after the write has already landed.
    before = {e.msgid: e for e in poutil.parse(path)
              if not e.obsolete and not e.is_header}
    applied = write()
    poutil.write(path, entries)
    print(f'{args.locale}: applied {applied} from {len(fixes)} corrections')

    after = {e.msgid: e for e in poutil.parse(path)
             if not e.obsolete and not e.is_header}
    if set(before) != set(after):
        print('FAIL: msgid set drifted')
        return 1
    if args.plurals:
        changed = {m for m in after if before[m].plurals != after[m].plurals}
        spilled = [m for m in after if before[m].msgstr != after[m].msgstr]
        label = 'msgstr touched'
    else:
        changed = {m for m in after if before[m].msgstr != after[m].msgstr}
        spilled = [m for m in after if before[m].plurals != after[m].plurals
                   or before[m].msgid_plural != after[m].msgid_plural]
        label = 'plural forms touched'
    unexpected = changed - set(fixes)
    print(f'verify: changed={len(changed)} unexpected={len(unexpected)} '
          f'{label}={len(spilled)}')
    if unexpected or spilled:
        for msgid in (sorted(unexpected) + spilled)[:10]:
            print(f'  UNEXPECTED {msgid[:70]!r}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
