#!/usr/bin/env python3
"""Run the whole localization pipeline: extract, merge, compile.

Usage: python3 scripts/update_messages.py [--check]

--check is passed to the compile step so a .po with errors does not produce a .mo.
merge_messages.py regenerates the template itself, so extraction is not a separate
step here.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import poutil  # noqa: E402


def run_step(label, script, extra=()):
    print(f'{label}...')
    result = subprocess.run([sys.executable, os.path.join(HERE, script), *extra], cwd=poutil.ROOT)
    if result.returncode != 0:
        print(f'Error: {script} failed with exit code {result.returncode}', file=sys.stderr)
        return False
    return True


def main():
    strict = '--check' in sys.argv[1:]

    for script in ('merge_messages.py', 'compile_messages.py'):
        if not os.path.isfile(os.path.join(HERE, script)):
            print(f'Error: Required script not found: {script}', file=sys.stderr)
            return 1

    print('Updating translation files...')
    print()

    if not run_step('Merging messages (regenerates the template first)', 'merge_messages.py'):
        return 1
    if not run_step('Compiling messages', 'compile_messages.py', ('--check',) if strict else ()):
        return 1

    print()
    print('Update completed successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
