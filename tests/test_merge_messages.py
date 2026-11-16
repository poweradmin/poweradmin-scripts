import os
import sys
import tempfile
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


if __name__ == '__main__':
    unittest.main()
