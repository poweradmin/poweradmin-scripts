#!/usr/bin/env python3
"""Check translation catalogues for the damage classes a past MT import left behind.

Usage:
  python3 scripts/check_translation_integrity.py [--locale=xx_XX] [--class=name,...]
                                                 [--examples=N] [--quiet]

Exits non-zero if any hard class reports a hit. Hard classes are the ones that
break the string at runtime or state something factually different from the
source; soft classes are reported but never fail the run, because each has a
known false-positive mode documented on its checker.

Classes
  placeholder  printf set differs from the msgid (hard)
  leak         a letter glued onto a placeholder, e.g. "%sZ" (hard)
  tags         HTML tag multiset differs (hard)
  tokens       [BRACKET] token multiset differs (hard)
  identifiers  a config key, table name or path is not verbatim (hard)
  trailing     msgid ends in whitespace but the translation does not (hard)
  boilerplate  text from outside this application, e.g. Twitter chrome (hard)
  numerals     a number in the msgid is missing from the translation (soft)
  truncation   translation under half the source length, non-CJK only (soft)
  crosswire    the translation appears to render a different msgid (soft)
"""
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

HARD = ('placeholder', 'leak', 'tags', 'tokens', 'identifiers', 'trailing', 'boilerplate')
SOFT = ('numerals', 'truncation', 'crosswire')

# Chinese, Japanese and Korean are far more compact than English, so the length
# ratio that finds dropped clauses elsewhere flags healthy text here.
CJK = {'zh_CN', 'zh_TW', 'ja_JP', 'ko_KR'}

PRINTF = re.compile(r'%(?:\d+\$)?[sdfucxXob]|%%')
LEAK = re.compile(r'%(?:\d+\$)?[sdfucxXob][A-Za-z]')
# Real markup only. Angle brackets are also used for metavariables such as
# <priority> or <hash>._openpgpkey.<domain>, which translators legitimately
# render in the target language - matching those would be almost all noise.
TAG = re.compile(r'</?(?:code|strong|em|b|i|u|a|br|p|span|div|ul|ol|li|small|sup|sub)\b[^<>]*>',
                 re.I)
TOKEN = re.compile(r'\[[A-Z0-9_]+\]')
NUMERAL = re.compile(r'(?<![\w.])\d[\d.]*(?![\w.])')
IDENTIFIER = re.compile(
    r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b'
    r'|\b(?:dns|api|misc|db|ldap|mail|pdns)\.[a-z_.]+\b'
    r'|\b[\w-]+\.(?:php|html|twig|js|css|sql|dat|json|ya?ml|conf|ini)\b'
)
# Chrome from other products. Anchored so Danish "citationstegn" and French
# "Félicitations" do not match on the "citation" substring.
BOILERPLATE = re.compile(
    r'\b(?:tweet|tweets|retweet|twitter|facebook|instagram|wikipedia|accessdate'
    r'|hashtag)\b', re.I
)
# Acronyms only: hyphen excluded so "DNS-Assistenten" yields DNS, and a 3-char
# floor so uppercase emphasis words like ALL and KEY stay out.
ACRONYM = re.compile(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{2,}(?![A-Za-z0-9])')
SIGNIFICANT = re.compile(r'(?<![A-Za-z0-9])(?:[A-Z][A-Za-z0-9]{2,}|\d+)(?![A-Za-z0-9])')
STOPWORDS = {'The', 'And', 'For', 'You', 'Not', 'This', 'That', 'Use', 'Using',
             'Please', 'Only', 'All', 'Each', 'New'}


def _placeholders(text):
    """Positional forms are legitimate reordering, so %1$d compares as %d."""
    return sorted(re.sub(r'\d+\$', '', p) for p in PRINTF.findall(text))


def _signature(text):
    return {t for t in SIGNIFICANT.findall(text) if t not in STOPWORDS}


def check_entry(entry, locale):
    """Return the hit classes for one entry."""
    src, dst = entry.msgid, entry.msgstr
    hits = []

    if _placeholders(src) != _placeholders(dst):
        hits.append('placeholder')
    if LEAK.search(dst) and not LEAK.search(src):
        hits.append('leak')
    if sorted(TAG.findall(src)) != sorted(TAG.findall(dst)):
        hits.append('tags')
    if sorted(TOKEN.findall(src)) != sorted(TOKEN.findall(dst)):
        hits.append('tokens')
    if any(tok not in dst for tok in set(IDENTIFIER.findall(src))):
        hits.append('identifiers')
    if src != src.rstrip() and dst.rstrip() == dst:
        hits.append('trailing')
    if BOILERPLATE.search(dst) and not BOILERPLATE.search(src):
        hits.append('boilerplate')

    # Soft: a translation may legitimately reformat a decimal separator, so a
    # missing numeral is a prompt to look rather than proof of damage.
    if set(NUMERAL.findall(src)) - set(NUMERAL.findall(dst)):
        hits.append('numerals')
    if locale not in CJK and len(re.findall(r'\S+', src)) >= 8 and len(dst) < len(src) * 0.5:
        hits.append('truncation')

    return hits


def check_locale(locale, examples=0):
    entries = [e for e in poutil.parse(poutil.po_path(locale))
               if e.msgid and not e.obsolete and not e.is_header
               and e.msgstr and e.msgstr != e.msgid]

    counts = Counter()
    samples = defaultdict(list)
    for entry in entries:
        for cls in check_entry(entry, locale):
            counts[cls] += 1
            if len(samples[cls]) < examples:
                samples[cls].append((entry.msgid, entry.msgstr))

    # Cross-wire needs the whole file: a translation carrying none of its own
    # source's tokens but matching a nearby source's is evidence of a swap.
    sigs_src = [_signature(e.msgid) for e in entries]
    sigs_dst = [_signature(e.msgstr) for e in entries]
    for i, entry in enumerate(entries):
        dst, src = sigs_dst[i], sigs_src[i]
        if len(dst) < 2 or len(src) < 2 or (dst & src):
            continue
        window = range(max(0, i - 80), min(len(entries), i + 81))
        best = max((len(dst & sigs_src[j]) for j in window if j != i), default=0)
        if best >= 2 and best >= len(dst) * 0.5:
            counts['crosswire'] += 1
            if len(samples['crosswire']) < examples:
                samples['crosswire'].append((entry.msgid, entry.msgstr))

    return len(entries), counts, samples


def main():
    args = sys.argv[1:]
    only = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)
    wanted = next((a.split('=', 1)[1].split(',') for a in args if a.startswith('--class=')), None)
    examples = int(next((a.split('=', 1)[1] for a in args if a.startswith('--examples=')), 0))
    quiet = '--quiet' in args

    locales = [only] if only else [l for l in sorted(poutil.locales()) if l != 'en_EN']
    classes = wanted or list(HARD + SOFT)

    totals = Counter()
    rows = []
    for locale in locales:
        if not os.path.isfile(poutil.po_path(locale)):
            print(f'Error: no catalogue for {locale}', file=sys.stderr)
            return 2
        n, counts, samples = check_locale(locale, examples)
        counts = Counter({k: v for k, v in counts.items() if k in classes})
        totals.update(counts)
        if counts:
            rows.append((locale, n, counts, samples))

    width = max((len(c) for c in classes), default=10)
    if not quiet:
        for locale, n, counts, samples in rows:
            print(f'{locale}  ({n} translated)')
            for cls, hits in counts.most_common():
                mark = '' if cls in HARD else '  (soft)'
                print(f'    {cls:<{width}} {hits:>5}{mark}')
                for src, dst in samples.get(cls, []):
                    print(f'        id : {src[:88]}')
                    print(f'        str: {dst[:88]}')
        print()

    print('total')
    for cls in classes:
        if totals[cls]:
            print(f'    {cls:<{width}} {totals[cls]:>5}' + ('' if cls in HARD else '  (soft)'))
    if not totals:
        print('    clean')

    return 1 if any(totals[c] for c in HARD if c in classes) else 0


if __name__ == '__main__':
    sys.exit(main())
