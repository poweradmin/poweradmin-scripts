import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cleanup_obsolete_translations as cot  # noqa: E402


class AppearsAsLiteralTest(unittest.TestCase):
    def test_complete_literal_matches(self):
        self.assertTrue(cot.appears_as_literal('Saved.', "$t = _('Saved.');"))
        self.assertTrue(cot.appears_as_literal('Saved.', 'x = "Saved.";'))

    def test_prefix_of_longer_string_is_not_a_match(self):
        blob = "$t = _('Record could not be added. Try again later.');"
        self.assertFalse(cot.appears_as_literal('Record could not be added.', blob))

    def test_suffix_of_longer_string_is_not_a_match(self):
        self.assertFalse(cot.appears_as_literal('be added.', "_('Record could not be added.')"))

    def test_escaped_php_single_quote(self):
        self.assertTrue(cot.appears_as_literal("Can't save", "_('Can\\'t save')"))

    def test_escaped_double_quote_and_newline(self):
        self.assertTrue(cot.appears_as_literal('Say "hi"', '_("Say \\"hi\\"")'))
        self.assertTrue(cot.appears_as_literal('a\nb', '_("a\\nb")'))

    def test_twig_trans_block(self):
        self.assertTrue(cot.appears_as_literal('Hello', '{% trans %}Hello{% endtrans %}'))
        self.assertTrue(cot.appears_as_literal('Hello', '{%trans%}Hello{%endtrans%}'))
        self.assertFalse(cot.appears_as_literal('Hello', '{% trans %}Hello there{% endtrans %}'))

    def test_element_text(self):
        self.assertTrue(cot.appears_as_literal('Hello', '<span>Hello</span>'))

    def test_absent(self):
        self.assertFalse(cot.appears_as_literal('Nothing', "_('Something else')"))


PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Live"
msgstr "Lebendig"

msgid "Stale"
msgstr "Veraltet"

#~ msgid "Tilde"
#~ msgstr "Tilde-de"

# OBSOLETE: msgid "Comment"
# OBSOLETE: msgstr "Kommentar"

#~ msgid "%d old"
#~ msgid_plural "%d olds"
#~ msgstr[0] "%d alt"
#~ msgstr[1] "%d alte"
'''


class FindObsoleteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, 'messages.po')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(PO)

    def test_marked_and_stale_found(self):
        entries, marked, stale = cot.find_obsolete(self.path, {'Live'})
        self.assertEqual(sorted(e.msgid for e in marked), ['%d old', 'Comment', 'Tilde'])
        self.assertEqual([e.msgid for e in stale], ['Stale'])
        self.assertEqual(cot.split_marked(marked), (2, 1))

    def test_header_is_never_stale(self):
        _, _, stale = cot.find_obsolete(self.path, set())
        self.assertNotIn('', [e.msgid for e in stale])

    def test_module_mode_without_template(self):
        _, marked, stale = cot.find_obsolete(self.path, None)
        self.assertEqual(len(marked), 3)
        self.assertEqual(stale, [])


    @unittest.skipUnless(shutil.which('msgfmt'), 'msgfmt not installed')
    def test_remove_obsolete_keeps_only_live(self):
        with contextlib.redirect_stdout(io.StringIO()):
            n = cot.remove_obsolete(self.path, {'Live'}, make_backup=False)
        self.assertEqual(n, 4)
        with open(self.path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('msgstr "Lebendig"', text)
        for gone in ('Stale', 'Tilde', 'Comment', '%d old'):
            self.assertNotIn(gone, text)
        self.assertTrue(text.endswith('\n'))
        self.assertFalse(text.endswith('\n\n'))


class ParserTest(unittest.TestCase):
    def parse(self, argv):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                return cot.build_parser().parse_args(argv), err
            except SystemExit as exc:
                return exc.code, err

    def test_dryrun_typo_rejected(self):
        result, _ = self.parse(['--dryrun'])
        self.assertEqual(result, 2)

    def test_abbreviation_rejected(self):
        result, _ = self.parse(['--dry'])
        self.assertEqual(result, 2)

    def test_dry_run_accepted(self):
        args, _ = self.parse(['--dry-run', '--locale=de_DE'])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.locale, 'de_DE')

    def test_verify_flags_mutually_exclusive(self):
        result, _ = self.parse(['--verify-only', '--skip-verify'])
        self.assertEqual(result, 2)


if __name__ == '__main__':
    unittest.main()
