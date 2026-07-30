#!/usr/bin/env python3
"""Compile every locale's messages.po into messages.mo.

Usage: python3 scripts/compile_messages.py [--locale=LOCALE] [--module=ModuleName] [--check]

--check runs msgfmt in validating mode first and refuses to write a .mo for any
locale that fails, so a broken .po cannot silently ship a stale .mo.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402


def main():
    args = sys.argv[1:]
    strict = '--check' in args
    only = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)
    module = next((a.split('=', 1)[1] for a in args if a.startswith('--module=')), None)

    base = (os.path.join(poutil.ROOT, 'lib/Module', module, 'locale') if module
            else os.path.join(poutil.ROOT, 'locale'))
    if not os.path.isdir(base):
        print(f'Error: Locale directory not found: {base}', file=sys.stderr)
        return 1

    locales = sorted(d for d in os.listdir(base)
                     if os.path.isdir(os.path.join(base, d)) and 'pot' not in d)
    if only:
        if only not in locales:
            print(f'Error: Locale not found: {only}', file=sys.stderr)
            return 1
        locales = [only]

    compiled = failed = skipped = 0
    for locale in locales:
        po_file = poutil.po_path(locale, module)
        if not os.path.isfile(po_file):
            print(f'Compiling {locale} locale')
            print(f'  Warning: PO file not found: {po_file}')
            skipped += 1
            continue

        print(f'Compiling {locale} locale')
        if strict:
            check = subprocess.run(['msgfmt', '--check', '-o', os.devnull, po_file],
                                   capture_output=True, text=True)
            real = [ln for ln in check.stderr.splitlines() if 'warning:' not in ln]
            if check.returncode != 0 and real:
                print(f'  Refusing to compile, {po_file} has errors:')
                for ln in real[:5]:
                    print(f'    {ln}')
                failed += 1
                continue

        mo_file = os.path.join(os.path.dirname(po_file), 'messages.mo')
        result = subprocess.run(['msgfmt', '-o', mo_file, po_file], capture_output=True, text=True)
        if result.returncode == 0:
            print(f'  Successfully compiled to {mo_file}')
            compiled += 1
        else:
            print(f'  Failed to compile {po_file}')
            for ln in result.stderr.splitlines()[:5]:
                print(f'    {ln}')
            failed += 1

    print()
    if failed:
        print(f'Compiled {compiled}, failed {failed}, skipped {skipped}.')
        return 1
    print('All message files have been compiled successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
