import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import poutil  # noqa: E402

# Real rule strings from the shipped catalogues, kept inline so no catalogue is read.
RU = ('nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : '
      'n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? 1 : 2);')
UK = ('nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : '
      'n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);')


def po_header(rule):
    return poutil.parse_string(
        'msgid ""\nmsgstr ""\n"Plural-Forms: ' + rule.replace('"', '\\"') + '\\n"\n')


class StringEscapeTest(unittest.TestCase):
    def test_single_pass_unescape(self):
        # "C:\\new" in a .po file is C, colon, one backslash, then "new"
        self.assertEqual(poutil.extract_string('"C:\\\\new"'), 'C:\\new')
        self.assertNotIn('\n', poutil.extract_string('"C:\\\\new"'))

    def test_known_escapes(self):
        self.assertEqual(poutil.extract_string(r'"a\tb\rc\"d\ne"'), 'a\tb\rc"d\ne')

    def test_unknown_escape_preserved(self):
        self.assertEqual(poutil.extract_string(r'"\d+ \%"'), r'\d+ \%')

    def test_unquoted_input_untouched(self):
        self.assertEqual(poutil.extract_string('  bare  '), 'bare')
        self.assertEqual(poutil.extract_string('"'), '"')

    def test_format_string(self):
        self.assertEqual(poutil.format_string('a\\b"c\nd\te\r'), 'a\\\\b\\"c\\nd\\te\\r')

    def test_round_trip(self):
        for text in ('plain', 'C:\\new', 'tab\there', 'cr\r\n', 'say "hi"',
                     '\\n literal', '\\\\', '', 'ünï "q" \\"x\\"', '%s\\%d'):
            with self.subTest(text=text):
                quoted = '"' + poutil.format_string(text) + '"'
                self.assertEqual(poutil.extract_string(quoted), text)


class PluralRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'plural_forms.json')
        with open(path, encoding='utf-8') as fh:
            cls.rules = json.load(fh)['rules']

    def test_every_rule_is_evaluable_and_in_range(self):
        self.assertTrue(self.rules)
        for iso, rule in self.rules.items():
            with self.subTest(iso=iso):
                count, pick = poutil.plural_spec(rule)
                self.assertGreaterEqual(count, 1)
                for n in range(201):
                    self.assertIn(pick(n), range(count), f'n={n}')

    def test_nplurals_matches_text(self):
        for iso, rule in self.rules.items():
            with self.subTest(iso=iso):
                declared = int(rule.split('nplurals=')[1].split(';')[0])
                self.assertEqual(poutil.plural_spec(rule)[0], declared)

    def test_plural_rule_lookup(self):
        self.assertEqual(poutil.plural_rule('ru'), self.rules['ru'])

    def test_unknown_iso_raises(self):
        with self.assertRaises(KeyError):
            poutil.plural_rule('xx')

    def test_russian_picks(self):
        _, pick = poutil.plural_spec(RU)
        self.assertEqual([pick(n) for n in (1, 2, 5, 11, 21, 22, 25)], [0, 1, 2, 2, 0, 1, 2])

    def test_ru_and_uk_spellings_equal(self):
        self.assertNotEqual(RU, UK)
        self.assertTrue(poutil.same_plural_rule(RU, UK))

    def test_shipped_ru_uk_rules_equal(self):
        self.assertTrue(poutil.same_plural_rule(self.rules['ru'], self.rules['uk']))

    def test_different_rules_differ(self):
        self.assertFalse(poutil.same_plural_rule(RU, 'nplurals=2; plural=(n != 1);'))
        self.assertFalse(poutil.same_plural_rule(
            'nplurals=2; plural=(n != 1);', 'nplurals=2; plural=(n > 1);'))

    def test_header_plural_rule(self):
        self.assertEqual(poutil.header_plural_rule(po_header(RU)), RU)
        self.assertIsNone(poutil.header_plural_rule(poutil.parse_string('msgid "a"\nmsgstr "b"')))


class UntranslatedTest(unittest.TestCase):
    def entry(self, text):
        return poutil.parse_string(text)[0]

    def test_empty_msgstr(self):
        self.assertTrue(poutil.is_untranslated(self.entry('msgid "Save"\nmsgstr ""')))

    def test_echo(self):
        e = self.entry('msgid "Save"\nmsgstr "Save"')
        self.assertTrue(poutil.is_untranslated(e, 'de_DE'))
        self.assertFalse(poutil.is_untranslated(e, 'en_EN'))

    def test_translated(self):
        self.assertFalse(poutil.is_untranslated(self.entry('msgid "Save"\nmsgstr "Speichern"')))

    def test_fallback_flag_with_echo(self):
        e = self.entry('#, auto-english-fallback\nmsgid "Save"\nmsgstr "Save"')
        self.assertTrue(poutil.is_untranslated(e, 'de_DE'))

    def test_plural_echoing_msgid_plural(self):
        e = self.entry('msgid "%d item"\nmsgid_plural "%d items"\n'
                       'msgstr[0] "%d Ding"\nmsgstr[1] "%d items"')
        self.assertTrue(poutil.is_untranslated(e, 'de_DE'))
        self.assertFalse(poutil.is_untranslated(e, 'en_EN'))

    def test_plural_translated_and_empty(self):
        done = self.entry('msgid "%d item"\nmsgid_plural "%d items"\n'
                          'msgstr[0] "%d Ding"\nmsgstr[1] "%d Dinge"')
        self.assertFalse(poutil.is_untranslated(done, 'de_DE'))
        empty = self.entry('msgid "%d item"\nmsgid_plural "%d items"\n'
                           'msgstr[0] "%d Ding"\nmsgstr[1] ""')
        self.assertTrue(poutil.is_untranslated(empty, 'de_DE'))

    def test_header_and_obsolete_never_untranslated(self):
        self.assertFalse(poutil.is_untranslated(self.entry('msgid ""\nmsgstr ""')))
        self.assertFalse(poutil.is_untranslated(self.entry('#~ msgid "Old"\n#~ msgstr ""')))


class ExcludedTest(unittest.TestCase):
    EX = ['DNS', 'Poweradmin']

    def test_exact(self):
        self.assertTrue(poutil.is_excluded('DNS', self.EX))

    def test_all_words_excluded_case_insensitive(self):
        self.assertTrue(poutil.is_excluded('dns poweradmin', self.EX))

    def test_prose_not_excluded(self):
        self.assertFalse(poutil.is_excluded('Save the DNS zone', self.EX))

    def test_short_allcaps_is_acronym(self):
        self.assertTrue(poutil.is_excluded('TTL', self.EX))
        self.assertFalse(poutil.is_excluded('LONGER', self.EX))

    def test_empty_exclusions(self):
        self.assertFalse(poutil.is_excluded('DNS', []))


class BackupTest(unittest.TestCase):
    def test_backups_in_the_same_second_do_not_collide(self):
        import tempfile
        from unittest import mock
        fixed = poutil.datetime(2026, 1, 2, 3, 4, 5)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'messages.po')
            with open(path, 'w') as fh:
                fh.write('one')
            with mock.patch.object(poutil, 'datetime') as dt:
                dt.now.return_value = fixed
                first = poutil.backup(path)
                with open(path, 'w') as fh:
                    fh.write('two')
                second = poutil.backup(path)
            self.assertNotEqual(first, second)
            self.assertEqual(open(first).read(), 'one')
            self.assertEqual(open(second).read(), 'two')


if __name__ == '__main__':
    unittest.main()
