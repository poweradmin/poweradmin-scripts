#!/usr/bin/env python3
"""Build locale/i18n-template-php.pot from PHP sources and Twig templates.

Usage: python3 scripts/extract_strings.py

gettext tools and `find` are invoked as subprocesses so output ordering is stable.

The template scan is line based: a {% trans %} block spread over several lines is
not picked up. Widening it would surface new msgids and force a merge across every
locale, so it is left alone deliberately.
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

CODE_DIR = 'lib'
TEMPLATES_DIR = 'templates'
MODULE_TEMPLATES_DIR = 'lib/Module'
INSTALL_DIR = 'install/templates'
HELPERS_DIR = 'install/helpers'
OUTPUT_POT = 'locale/i18n-template-php.pot'

BUGS_ADDRESS = 'edmondas@girkantas.lt'

# {% trans %}...{% endtrans %} and the 'string'|trans filter form
_TRANS_RE = re.compile(r'{%\s*trans\s*%}(.*?){%\s*endtrans\s*%}', re.DOTALL)
_FILTER_RE = re.compile(r"""(?:'((?:[^'\\]|\\.)+)'|"((?:[^"\\]|\\.)+)")\s*\|\s*trans\b""")


def version():
    path = os.path.join(ROOT, 'lib/Version.php')
    if not os.path.isfile(path):
        print("Warning: Unable to determine version. Using 'unknown'")
        return 'unknown'
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if 'VERSION' in line:
                parts = line.split("'")
                if len(parts) > 1:
                    return parts[1]
    return 'unknown'


def pot_header(ver, stamp, language=''):
    return (
        'msgid ""\n'
        'msgstr ""\n'
        f'"Project-Id-Version: Poweradmin {ver}\\n"\n'
        f'"Report-Msgid-Bugs-To: {BUGS_ADDRESS}\\n"\n'
        f'"POT-Creation-Date: {stamp}\\n"\n'
        '"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"\n'
        '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"\n'
        '"Language-Team: LANGUAGE <LL@li.org>\\n"\n'
        f'"Language: {language}\\n"\n'
        '"MIME-Version: 1.0\\n"\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Content-Transfer-Encoding: 8bit\\n"\n'
    )


def find_files(root, args):
    """Run find so traversal order stays stable across runs."""
    if not os.path.isdir(os.path.join(ROOT, root)):
        return []
    out = subprocess.run(['find', root] + args, cwd=ROOT,
                         capture_output=True, text=True).stdout
    return [line for line in out.split('\n') if line]


def xgettext_php(root, dest, ver):
    files = find_files(root, ['-name', '*.php'])
    if not files:
        return False
    subprocess.run([
        'xgettext', '--no-wrap', '-L', 'PHP',
        '--copyright-holder=Poweradmin Development Team',
        f'--msgid-bugs-address={BUGS_ADDRESS}',
        '-o', dest, '--package-name=Poweradmin',
        f'--package-version={ver}', '--from-code=UTF-8',
    ] + files, cwd=ROOT, check=False)
    return os.path.isfile(dest)


def fix_pot_header(path, year):
    """Replace xgettext's placeholder header fields with real values."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path, encoding='utf-8') as fh:
        lines = fh.read().split('\n')
    out = []
    for line in lines:
        if 'Plural-Forms:' in line:
            continue
        line = line.replace('SOME DESCRIPTIVE TITLE', 'Poweradmin translation template')
        line = line.replace('Language: ', 'Language: en_EN')
        line = line.replace('PACKAGE', 'Poweradmin')
        line = line.replace('(C) YEAR', f'(C) {year}')
        line = line.replace('CHARSET', 'UTF-8')
        out.append(line)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))


def extract_from_template(path):
    """Emit .pot records for every translatable string in one template."""
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        content = fh.read()

    records = []
    # Line based on purpose: see the module docstring.
    for lineno, line in enumerate(content.split('\n'), 1):
        matches = _TRANS_RE.findall(line)
        matches += [a or b for a, b in _FILTER_RE.findall(line)]
        for match in matches:
            text = match.strip()
            if not text:
                continue
            escaped = text.replace('"', '\\"')
            records.append(f'#: {path}:{lineno}\nmsgid "{escaped}"\nmsgstr ""\n')
    return records


def build_template_pot(dest, roots, ver, stamp):
    """Header plus every template record, deduplicated with msguniq."""
    chunks = [pot_header(ver, stamp) + '\n']
    for root, find_args in roots:
        for path in find_files(root, find_args):
            chunks.extend(extract_from_template(path))

    tmp = dest + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(chunks))

    result = subprocess.run(['msguniq', tmp, '--force-po', '-o', dest],
                            capture_output=True, text=True)
    if result.returncode != 0:
        shutil.copyfile(tmp, dest)


def collect_records(source):
    """Entries that start with a `#:` location line, headers excluded."""
    if not os.path.isfile(source) or os.path.getsize(source) == 0:
        return ''
    emitted = []
    record = None
    with open(source, encoding='utf-8') as fh:
        for line in fh.read().split('\n'):
            if line.startswith('#:'):
                record = line
                continue
            if record is not None and line == '':
                emitted.append(record)
                emitted.append('')
                record = None
                continue
            if record is not None:
                record += '\n' + line
    text = ''.join(chunk + '\n' for chunk in emitted)
    return '\n'.join(l for l in text.split('\n') if 'Project-Id-Version' not in l)


def main():
    ver = version()
    year = datetime.now().strftime('%Y')
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M%z')

    if not os.path.isdir(os.path.join(ROOT, CODE_DIR)):
        print(f'Error: Directory {CODE_DIR} not found', file=sys.stderr)
        sys.exit(1)

    tmpdir = tempfile.mkdtemp()
    try:
        php_pot = os.path.join(tmpdir, 'php_strings.pot')
        html_pot = os.path.join(tmpdir, 'html_strings.pot')
        install_pot = os.path.join(tmpdir, 'install_strings.pot')
        helpers_pot = os.path.join(tmpdir, 'helpers_strings.pot')

        xgettext_php(CODE_DIR, php_pot, ver)
        fix_pot_header(php_pot, year)

        if os.path.isdir(os.path.join(ROOT, HELPERS_DIR)):
            xgettext_php(HELPERS_DIR, helpers_pot, ver)
            fix_pot_header(helpers_pot, year)
        else:
            print(f'Warning: Helpers directory {HELPERS_DIR} not found, skipping')
            open(helpers_pot, 'w').close()

        if os.path.isdir(os.path.join(ROOT, TEMPLATES_DIR)):
            build_template_pot(html_pot, [
                (TEMPLATES_DIR, ['(', '-name', '*.html', '-o', '-name', '*.html.twig', ')']),
                (MODULE_TEMPLATES_DIR, ['-path', '*/templates/*.html']),
            ], ver, stamp)
        else:
            print(f'Warning: Templates directory {TEMPLATES_DIR} not found, skipping')
            open(html_pot, 'w').close()

        if os.path.isdir(os.path.join(ROOT, INSTALL_DIR)):
            build_template_pot(install_pot, [
                (INSTALL_DIR, ['(', '-name', '*.html', '-o', '-name', '*.html.twig', ')']),
            ], ver, stamp)
        else:
            print(f'Warning: Install directory {INSTALL_DIR} not found, skipping')
            open(install_pot, 'w').close()

        for pot in (php_pot, html_pot, install_pot, helpers_pot):
            if os.path.isfile(pot) and os.path.getsize(pot):
                check = subprocess.run(['msgfmt', '--check', pot, '-o', '/dev/null'],
                                       capture_output=True)
                if check.returncode != 0:
                    print(f'Error in {os.path.basename(pot)}')
            elif not os.path.isfile(pot):
                with open(pot, 'w', encoding='utf-8') as fh:
                    fh.write(pot_header(ver, stamp))

        output = os.path.join(ROOT, OUTPUT_POT)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with open(output, 'w', encoding='utf-8') as fh:
            fh.write(
                '# Poweradmin translation template.\n'
                f'# Copyright (C) {year} Poweradmin Development Team\n'
                '# This file is distributed under the same license as the Poweradmin package.\n'
                '# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.\n'
                '#\n'
                '#, fuzzy\n'
                + pot_header(ver, stamp, 'en_EN')
            )
            for pot in (php_pot, html_pot, install_pot, helpers_pot):
                fh.write(collect_records(pot))

        final = os.path.join(tmpdir, 'final.pot')
        result = subprocess.run(['msguniq', output, '--output=' + final, '--force-po'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            shutil.copyfile(final, output)
        else:
            print('Warning: Failed to deduplicate the final POT file')

        print('Template generation complete.')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
