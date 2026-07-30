#!/usr/bin/env python3
"""Merge locale/i18n-template-php.pot into every locale's messages.po.

Usage: python3 scripts/merge_messages.py

Entries left without a translation are filled from en_EN and flagged
`#, auto-english-fallback`, multi-line msgids included.

Text is manipulated as raw .po source rather than through poutil so that entry
separators come out normalised the way gettext writes them.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

ROOT = poutil.ROOT
LOCALE_DIR = os.path.join(ROOT, 'locale')
TEMPLATE = os.path.join(LOCALE_DIR, 'i18n-template-php.pot')
ENGLISH_LOCALE = 'en_EN'

# Fallback used when a locale header is missing Plural-Forms entirely
LOCALE_PLURALS = {
    'cs': 'nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;',
    'de': 'nplurals=2; plural=(n != 1);',
    'es': 'nplurals=2; plural=(n != 1);',
    'fr': 'nplurals=2; plural=(n > 1);',
    'id': 'nplurals=1; plural=0;',
    'it': 'nplurals=2; plural=(n != 1);',
    'ja': 'nplurals=1; plural=0;',
    'ko': 'nplurals=1; plural=0;',
    'lt': 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'nb': 'nplurals=2; plural=(n != 1);',
    'nl': 'nplurals=2; plural=(n != 1);',
    'pl': 'nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'pt': 'nplurals=2; plural=(n != 1);',
    'ru': 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'sv': 'nplurals=2; plural=(n != 1);',
    'tr': 'nplurals=2; plural=(n != 1);',
    'uk': 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);',
    'vi': 'nplurals=1; plural=0;',
    'zh': 'nplurals=1; plural=0;',
}

_MSGID_RE = re.compile(r'^msgid ("(?:.*?)"(?:\n".*?")*)', re.DOTALL | re.MULTILINE)
_MSGSTR_RE = re.compile(r'^msgstr ("(?:.*?)"(?:\n".*?")*)', re.DOTALL | re.MULTILINE)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def valid(po_file):
    return run(['msgfmt', '--check', po_file, '-o', '/dev/null']).returncode == 0


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def write(path, text):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def cleanup_obsolete(po_file):
    """Keep obsolete entries that still carry a translation, drop the empty ones."""
    print(f'  - Reviewing obsolete translations in {po_file}')
    content = read(po_file)
    obsolete_count = content.count('#~ msgid')
    print(f'    Found {obsolete_count} obsolete translations')
    if not obsolete_count:
        return

    sections = re.split(r'\n\n+', content)
    header, entries = sections[0], sections[1:]

    kept = removed = 0
    out = [header + '\n\n']
    for entry in entries:
        if '#~' in entry:
            m = re.search(r'#~ msgstr "(.+?)"', entry, re.DOTALL)
            if m and m.group(1).strip():
                entry = re.sub(r'^#~ ', '# OBSOLETE: ', entry, flags=re.MULTILINE)
                out.append(entry + '\n\n')
                kept += 1
            else:
                removed += 1
        else:
            out.append(entry + '\n\n')

    write(po_file, ''.join(out))
    print(f'    Kept {kept} obsolete entries with translations')
    print(f'    Removed {removed} empty obsolete entries')
    print(f"    File now has {read(po_file).count('msgid')} total entries")


def regenerate_template():
    print('Regenerating template file with extract_strings.py...')
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extract_strings.py')
    subprocess.run([sys.executable, script], cwd=ROOT, check=False)

    print('Deduplicating template file with msguniq...')
    result = run(['msguniq', '--force-po', TEMPLATE])
    if result.returncode == 0:
        write(TEMPLATE, result.stdout)
    else:
        print('Warning: msguniq failed')

    print('Fixing any potential syntax issues in template file...')
    if not valid(TEMPLATE):
        print('Template has syntax issues. Creating simplified version...')
        content = read(TEMPLATE)
        header = content.split('\n\n', 1)[0] + '\n'
        seen = sorted({line for line in content.split('\n')
                       if line.startswith('msgid') and line != 'msgid ""'})
        body = ''.join(f'{m}\nmsgstr ""\n\n' for m in seen)
        write(TEMPLATE, header + '\n' + body)


def english_translation_map(po_file):
    """msgid -> msgstr, both as raw quoted source including continuation lines."""
    mapping = {}
    msgid = msgstr = ''
    in_msgid = in_msgstr = False

    for line in read(po_file).split('\n'):
        if line.startswith('msgid "'):
            if msgid and msgstr:
                mapping[msgid.strip()] = msgstr.strip()
            msgid = line[6:]
            in_msgid, in_msgstr = True, False
            msgstr = ''
        elif line.startswith('msgstr "'):
            msgstr = line[7:]
            in_msgid, in_msgstr = False, True
        elif line.startswith('"'):
            if in_msgid:
                msgid += '\n' + line
            elif in_msgstr:
                msgstr += '\n' + line
        elif line == '':
            if msgid and msgstr:
                mapping[msgid.strip()] = msgstr.strip()
                msgid = msgstr = ''
            in_msgid = in_msgstr = False

    if msgid and msgstr:
        mapping[msgid.strip()] = msgstr.strip()
    # The header's msgid is "" and would match any commented-out entry
    mapping.pop('""', None)
    return mapping


def update_english():
    messages_dir = os.path.join(LOCALE_DIR, ENGLISH_LOCALE, 'LC_MESSAGES')
    if not os.path.isdir(messages_dir):
        print(f'Error: English locale directory {messages_dir} not found', file=sys.stderr)
        sys.exit(1)

    po = os.path.join(messages_dir, 'messages.po')
    bak = po + '.bak'
    shutil.copyfile(po, bak)
    print('  - Preserving existing English translations and adding new entries')

    merged = po + '.merged'
    run(['msgmerge', '--no-fuzzy-matching', '--quiet', po, TEMPLATE, '-o', merged])

    print('  - Using msgen to create English translations for empty entries only...')
    msgen_out = po + '.msgen'
    run(['msgen', merged, '-o', msgen_out])
    new = po + '.new'
    run(['msgcat', '--use-first', merged, msgen_out, '-o', new])
    os.remove(msgen_out)

    if os.path.isfile(new):
        os.replace(new, po)
        if os.path.isfile(merged):
            os.remove(merged)
    else:
        print('  - Warning: Failed to process English translations, keeping original')
        os.replace(merged, po)

    if not valid(po):
        print('  - Warning: English file has syntax issues, attempting to fix...')
        fixed = po + '.fixed'
        if run(['msgcat', '--no-wrap', po, '-o', fixed]).returncode == 0:
            os.replace(fixed, po)
            print('  - Fixed with msgcat')
        else:
            print('  - msgcat failed, creating fresh file from template...')
            run(['msginit', '--no-translator', f'--locale={ENGLISH_LOCALE}',
                 f'--input={TEMPLATE}', f'--output={po}'])

    cleanup_obsolete(po)
    print('  - English translations preserved and new entries added')

    old_trans = read(bak).count('\nmsgstr')
    new_trans = read(po).count('\nmsgstr')
    print(f'  - Old translations: {old_trans}')
    print(f'  - New translations: {new_trans}')
    print(f"  - Commented translations: {read(po).count('#~ ')}")
    os.remove(bak)
    return po


def fill_english_fallbacks(po, english_trans):
    """Replace empty msgstr with the English text and flag the entry."""
    content = read(po)
    sections = re.split(r'\n\n+', content)
    header, entries = sections[0], sections[1:]

    out = [header + '\n\n']
    fallback_count = 0
    for entry in entries:
        if '#~' in entry or '# OBSOLETE:' in entry:
            out.append(entry + '\n\n')
            continue
        msgid_match = _MSGID_RE.search(entry)
        msgstr_match = _MSGSTR_RE.search(entry)
        if msgid_match and msgstr_match:
            msgid = msgid_match.group(1)
            msgstr = msgstr_match.group(1)
            if msgstr.strip() == '""' and msgid in english_trans:
                if '#, auto-english-fallback' not in entry:
                    entry = re.sub(r'#, fuzzy\n', '', entry)
                    if '#:' in entry:
                        entry = re.sub(r'(#:.*(\n#:.*)*)',
                                       r'\1\n#, auto-english-fallback', entry)
                    else:
                        entry = '#, auto-english-fallback\n' + entry
                entry = re.sub(r'^msgstr ""', 'msgstr ' + english_trans[msgid].replace('\\', '\\\\'),
                               entry, flags=re.MULTILINE)
                fallback_count += 1
        out.append(entry + '\n\n')

    print(f'  - Added {fallback_count} English fallbacks with auto-english-fallback marker')
    return ''.join(out)


def fix_locale_header(po, locale):
    content = read(po)
    code = locale.split('_')[0].lower()
    plural = LOCALE_PLURALS.get(code, 'nplurals=2; plural=(n != 1);')
    if 'Plural-Forms:' not in content:
        content = re.sub(r'("Content-Transfer-Encoding: 8bit\\n")',
                         r'\1\n"Plural-Forms: ' + plural + r'\\n"', content)
    content = content.replace('"Language: en_EN\\n"', f'"Language: {code}\\n"')
    write(po, content)


def update_locale(locale, english_trans):
    print(f'Updating {locale} locale')
    messages_dir = os.path.join(LOCALE_DIR, locale, 'LC_MESSAGES')
    if not os.path.isdir(messages_dir):
        print(f'Error: Directory {messages_dir} not found', file=sys.stderr)
        sys.exit(1)

    po = os.path.join(messages_dir, 'messages.po')
    bak = po + '.bak'
    shutil.copyfile(po, bak)

    tmp = po + '.tmp'
    run(['msgmerge', '--no-fuzzy-matching', '--quiet', po, TEMPLATE, '-o', tmp])
    os.replace(tmp, po)

    filled = fill_english_fallbacks(po, english_trans)
    if filled.strip():
        write(po, filled)
        if not valid(po):
            print('  - Warning: File has syntax issues, attempting to fix...')
            fix_locale_header(po, locale)
            print('  - Applied header fixes')
            if valid(po):
                print('  - Header fixes successful')
            else:
                print('  - Header fixes insufficient, trying msgcat...')
                fixed = po + '.fixed'
                if run(['msgcat', '--no-wrap', po, '-o', fixed]).returncode == 0:
                    os.replace(fixed, po)
                    print('  - msgcat fixes applied')
                else:
                    print('  - Warning: Could not fix syntax issues, but preserving existing translations')
    else:
        print('  - Warning: Failed to process, falling back to original file')

    print(f"  - Old translations: {read(bak).count(chr(10) + 'msgstr')}")
    print(f"  - New translations: {read(po).count(chr(10) + 'msgstr')}")
    print(f"  - Commented translations: {read(po).count('#~ ')}")

    cleanup_obsolete(po)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.replace(bak, f'{po}.backup.{stamp}')
    print(f'  - Backup saved as messages.po.backup.{stamp}')


def main():
    if not os.path.isdir(LOCALE_DIR):
        print(f'Error: Locale directory not found: {LOCALE_DIR}', file=sys.stderr)
        sys.exit(1)

    for tool in ('msgmerge', 'msgen', 'msgcat', 'msgattrib', 'msguniq'):
        if shutil.which(tool) is None:
            print(f'Error: {tool} not found on PATH', file=sys.stderr)
            sys.exit(1)

    regenerate_template()
    if not os.path.isfile(TEMPLATE):
        print(f'Error: Template file not found: {TEMPLATE}', file=sys.stderr)
        sys.exit(1)

    print(f'Updating {ENGLISH_LOCALE} locale (ensuring matching translations)')
    english_po = update_english()

    print('Creating English translation map for fallbacks...')
    english_trans = english_translation_map(english_po)

    for locale in sorted(d for d in os.listdir(LOCALE_DIR)
                         if os.path.isdir(os.path.join(LOCALE_DIR, d)) and 'pot' not in d):
        if locale != ENGLISH_LOCALE:
            update_locale(locale, english_trans)

    print('')
    print('Translation files have been updated. To compile .mo files, run:')
    print('python3 scripts/compile_messages.py')
    print('')
    print('Obsolete translations with actual content have been preserved for review.')
    print('')
    print("Entries that were empty and filled with English translations are marked with '#, auto-english-fallback'.")
    print('You can find them using grep: grep -r "auto-english-fallback" locale/')


if __name__ == '__main__':
    main()
