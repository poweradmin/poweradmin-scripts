import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import poutil  # noqa: E402

HEADER = (
    'msgid ""\n'
    'msgstr ""\n'
    '"Project-Id-Version: x\\n"\n'
    '"Plural-Forms: nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : "\n'
    '"n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? 1 : 2);\\n"\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"'
)
MULTILINE = (
    '#: a.php:1\n'
    'msgid ""\n'
    '"first line\\n"\n'
    '"second line"\n'
    'msgstr ""\n'
    '"erste\\n"\n'
    '"zweite"'
)
PLURAL = (
    '#: a.php:2\n'
    'msgid "%d item"\n'
    'msgid_plural "%d items"\n'
    'msgstr[0] "%d Ding"\n'
    'msgstr[1] "%d Dinge"'
)
FUZZY = '#, fuzzy\nmsgid "Save"\nmsgstr "Speichern"'
FALLBACK = '#, auto-english-fallback\nmsgid "Cancel"\nmsgstr "Cancel"'
BOTH = '#, fuzzy, auto-english-fallback\nmsgid "Close"\nmsgstr "Close"'
OBS_S = '#~ msgid "Old"\n#~ msgstr "Alt"'
OBS_P = ('#~ msgid "%d old"\n#~ msgid_plural "%d olds"\n'
         '#~ msgstr[0] "%d alt"\n#~ msgstr[1] "%d alte"')
OBS_C = '# OBSOLETE: msgid "Gone"\n# OBSOLETE: msgstr "Weg"'


def doc(*blocks, tail='\n'):
    return '\n\n'.join(blocks) + tail


class RoundTripTest(unittest.TestCase):
    def assertRoundTrip(self, text):
        self.assertEqual(poutil.render(poutil.parse_string(text)), text)

    def test_full_document(self):
        self.assertRoundTrip(doc(HEADER, MULTILINE, PLURAL, FUZZY, FALLBACK, BOTH,
                                 OBS_S, OBS_P, OBS_C))

    def test_each_block_alone(self):
        for block in (HEADER, MULTILINE, PLURAL, FUZZY, FALLBACK, BOTH, OBS_S, OBS_P, OBS_C):
            with self.subTest(block=block[:20]):
                self.assertRoundTrip(block)

    def test_trailing_whitespace_chunks(self):
        self.assertRoundTrip(doc(FUZZY, tail='\n\n\n'))
        self.assertRoundTrip(doc(FUZZY, FALLBACK, tail='\n  \n'))
        self.assertRoundTrip('\n' + FUZZY + '\n')

    def test_wide_blank_separators_kept(self):
        self.assertRoundTrip(FUZZY + '\n\n\n\n' + FALLBACK + '\n')

    def test_header_parsed_across_wrapped_lines(self):
        header = poutil.parse_string(HEADER)[0]
        self.assertTrue(header.is_header)
        rule = poutil.header_plural_rule([header])
        self.assertEqual(poutil.plural_spec(rule)[0], 3)
        self.assertIn('Content-Type: text/plain', header.msgstr)

    def test_multiline_values_joined(self):
        e = poutil.parse_string(MULTILINE)[0]
        self.assertEqual(e.msgid, 'first line\nsecond line')
        self.assertEqual(e.msgstr, 'erste\nzweite')
        self.assertEqual(e.locations, ['a.php:1'])

    def test_plural_parse(self):
        e = poutil.parse_string(PLURAL)[0]
        self.assertEqual(e.msgid_plural, '%d items')
        self.assertEqual(e.plurals, {0: '%d Ding', 1: '%d Dinge'})

    def test_flags(self):
        e = poutil.parse_string(BOTH)[0]
        self.assertEqual(e.flags, ['fuzzy', 'auto-english-fallback'])
        self.assertTrue(e.is_fuzzy)


class ObsoleteTest(unittest.TestCase):
    def test_all_obsolete_forms(self):
        for block in (OBS_S, OBS_P, OBS_C):
            with self.subTest(block=block[:15]):
                e = poutil.parse_string(block)[0]
                self.assertTrue(e.obsolete)
                self.assertTrue(e.msgid)
                self.assertFalse(e.is_header)

    def test_obsolete_values(self):
        e = poutil.parse_string(OBS_S)[0]
        self.assertEqual((e.msgid, e.msgstr), ('Old', 'Alt'))
        p = poutil.parse_string(OBS_P)[0]
        self.assertEqual((p.msgid, p.msgid_plural), ('%d old', '%d olds'))
        self.assertEqual(p.plurals, {0: '%d alt', 1: '%d alte'})
        c = poutil.parse_string(OBS_C)[0]
        self.assertEqual((c.msgid, c.msgstr), ('Gone', 'Weg'))

    def test_obsolete_never_rewritten(self):
        e = poutil.parse_string(OBS_S)[0]
        e.msgstr = 'Neu'
        # no raw line starts with msgstr, so render keeps the original block
        self.assertEqual(e.render(), OBS_S)


class EditTest(unittest.TestCase):
    def test_untouched_is_identical(self):
        e = poutil.parse_string(FUZZY)[0]
        self.assertFalse(e.dirty)
        self.assertEqual(e.render(), FUZZY)

    def test_same_value_not_dirty(self):
        e = poutil.parse_string(FUZZY)[0]
        e.msgstr = 'Speichern'
        self.assertFalse(e.dirty)

    def test_msgstr_edit(self):
        e = poutil.parse_string(MULTILINE)[0]
        e.msgstr = 'a "q"\n'
        self.assertEqual(e.render(),
                         '#: a.php:1\nmsgid ""\n"first line\\n"\n"second line"\n'
                         'msgstr "a \\"q\\"\\n"')

    def test_set_plural(self):
        e = poutil.parse_string(PLURAL)[0]
        e.set_plural(1, '%d Sachen')
        self.assertEqual(e.render(), PLURAL.replace('%d Dinge', '%d Sachen'))

    def test_remove_one_flag_keeps_the_other(self):
        e = poutil.parse_string(BOTH)[0]
        self.assertTrue(e.remove_flags('fuzzy'))
        self.assertEqual(e.render(),
                         '#, auto-english-fallback\nmsgid "Close"\nmsgstr "Close"')

    def test_remove_last_flag_drops_line(self):
        e = poutil.parse_string(FALLBACK)[0]
        e.remove_flags('auto-english-fallback')
        e.msgstr = 'Abbrechen'
        self.assertEqual(e.render(), 'msgid "Cancel"\nmsgstr "Abbrechen"')

    def test_clear_fuzzy(self):
        e = poutil.parse_string(FUZZY)[0]
        self.assertTrue(e.clear_fuzzy())
        self.assertFalse(e.is_fuzzy)
        self.assertEqual(e.render(), 'msgid "Save"\nmsgstr "Speichern"')

    def test_remove_absent_flag_is_noop(self):
        e = poutil.parse_string(FUZZY)[0]
        self.assertFalse(e.remove_flags('auto-english-fallback'))
        self.assertFalse(e.dirty)

    def test_edit_only_touches_its_block(self):
        entries = poutil.parse_string(doc(FUZZY, FALLBACK, tail=''))
        entries[1].msgstr = 'X'
        self.assertEqual(poutil.render(entries),
                         doc(FUZZY, '#, auto-english-fallback\nmsgid "Cancel"\nmsgstr "X"',
                             tail=''))

    def test_line_spans(self):
        entries = poutil.parse_string(doc(FUZZY, FALLBACK, tail=''))
        self.assertEqual(poutil.line_spans(entries), [(1, 3), (5, 7)])
        self.assertIs(poutil.find_by_line(entries, 6), entries[1])


if __name__ == '__main__':
    unittest.main()
