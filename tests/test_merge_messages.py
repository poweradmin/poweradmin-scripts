import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_messages  # noqa: E402
import poutil  # noqa: E402

BEFORE = (
    'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
    '#: a.php:1\n#, auto-english-fallback\nmsgid "Still English"\nmsgstr "Still English"\n\n'
    '#, auto-english-fallback\nmsgid "Translated since"\nmsgstr "Schon übersetzt"\n\n'
    'msgid "Plain"\nmsgstr "Plain"\n'
)


class FallbackFlagTest(unittest.TestCase):
    def test_flags_survive_a_flag_dropping_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            po = os.path.join(tmp, 'messages.po')
            with open(po, 'w', encoding='utf-8') as fh:
                fh.write(BEFORE)
            flagged = merge_messages.fallback_msgids(po)
            self.assertEqual(flagged, {'Still English', 'Translated since'})
            # what msgmerge leaves behind: the custom flag is gone
            with open(po, 'w', encoding='utf-8') as fh:
                fh.write(BEFORE.replace('#, auto-english-fallback\n', ''))
            with mock.patch('builtins.print'):
                merge_messages.restore_fallback_flags(po, flagged)
            flags = {e.msgid: e.flags for e in poutil.parse(po) if not e.is_header}
        self.assertEqual(flags['Still English'], ['auto-english-fallback'])
        self.assertEqual(flags['Translated since'], [])
        self.assertEqual(flags['Plain'], [])


PO = ('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
      '#: a.php:1\nmsgid "Save"\nmsgstr "Speichern"\n')


class FakeGettext:
    """Stand-in for the gettext tools: copies input to output unless told to fail."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.calls = []

    def __call__(self, cmd, **kw):
        tool = cmd[0] + (' --no-wrap' if '--no-wrap' in cmd else '')
        self.calls.append(tool)
        if tool in self.failing:
            return types.SimpleNamespace(returncode=1, stderr=f'{tool} broke', stdout='')
        out = next((a.split('=', 1)[1] for a in cmd if a.startswith('--output=')), None)
        if out is None and '-o' in cmd:
            out = cmd[cmd.index('-o') + 1]
        src = next(a for a in cmd[1:] if a.endswith(('.po', '.merged')) and a != out)
        if out and out != os.devnull:
            shutil.copyfile(src, out)
        return types.SimpleNamespace(returncode=0, stderr='', stdout='')


class FailurePathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        locale_dir = os.path.join(self.tmp.name, 'locale')
        for loc in ('en_EN', 'de_DE'):
            os.makedirs(os.path.join(locale_dir, loc, 'LC_MESSAGES'))
            with open(self.po(loc, locale_dir), 'w', encoding='utf-8') as fh:
                fh.write(PO)
        template = os.path.join(locale_dir, 'i18n-template-php.pot')
        with open(template, 'w', encoding='utf-8') as fh:
            fh.write(PO)
        self.locale_dir = locale_dir
        for name, value in (('LOCALE_DIR', locale_dir), ('TEMPLATE', template)):
            patcher = mock.patch.object(merge_messages, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        quiet = mock.patch('builtins.print')
        quiet.start()
        self.addCleanup(quiet.stop)

    def po(self, loc, locale_dir=None):
        return os.path.join(locale_dir or self.locale_dir, loc, 'LC_MESSAGES', 'messages.po')

    def text(self, loc):
        with open(self.po(loc), encoding='utf-8') as fh:
            return fh.read()

    def leftovers(self, loc):
        return sorted(f for f in os.listdir(os.path.dirname(self.po(loc))) if f != 'messages.po')

    def test_english_msgmerge_failure_restores_catalogue(self):
        with mock.patch.object(merge_messages, 'run', FakeGettext({'msgmerge'})):
            with self.assertRaisesRegex(merge_messages.MergeError, 'msgmerge broke.*restored'):
                merge_messages.update_english()
        self.assertEqual(self.text('en_EN'), PO)
        self.assertEqual(self.leftovers('en_EN'), [])

    def test_english_msginit_failure_after_failed_repair_restores_catalogue(self):
        fake = FakeGettext({'msgcat --no-wrap', 'msginit'})
        with mock.patch.object(merge_messages, 'run', fake), \
                mock.patch.object(merge_messages, 'valid', return_value=False):
            with self.assertRaisesRegex(merge_messages.MergeError, 'msginit broke.*restored'):
                merge_messages.update_english()
        self.assertIn('msginit', fake.calls)
        self.assertEqual(self.text('en_EN'), PO)
        self.assertEqual(self.leftovers('en_EN'), [])

    def test_locale_msgmerge_failure_restores_catalogue(self):
        with mock.patch.object(merge_messages, 'run', FakeGettext({'msgmerge'})):
            with self.assertRaisesRegex(merge_messages.MergeError, 'de_DE.*restored'):
                merge_messages.update_locale('de_DE', {})
        self.assertEqual(self.text('de_DE'), PO)
        self.assertEqual(self.leftovers('de_DE'), [])

    def test_locale_msgcat_repair_keeps_translations(self):
        fake = FakeGettext()
        with mock.patch.object(merge_messages, 'run', fake), \
                mock.patch.object(merge_messages, 'valid', return_value=False):
            merge_messages.update_locale('de_DE', {})
        self.assertIn('msgcat --no-wrap', fake.calls)
        self.assertIn('msgstr "Speichern"', self.text('de_DE'))
        left = self.leftovers('de_DE')
        self.assertEqual(len(left), 1)
        self.assertTrue(left[0].startswith('messages.po.backup.'))

    def test_main_exits_non_zero_on_merge_error(self):
        with mock.patch.object(merge_messages, 'merge_all',
                               side_effect=merge_messages.MergeError('boom')), \
                mock.patch.object(merge_messages.shutil, 'which', return_value='/bin/true'), \
                mock.patch('sys.stderr'):
            self.assertEqual(merge_messages.main(), 1)


if __name__ == '__main__':
    unittest.main()
