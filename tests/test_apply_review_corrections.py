import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import apply_review_corrections as arc  # noqa: E402
import poutil  # noqa: E402

# Literal matchers in the (term, pattern, skipped_locales) shape load_dnt() returns,
# so the gate is exercised without depending on the shipped glossary contents.
DNT = [('SOA', re.compile(r'(?<![A-Za-z0-9])SOA(?![A-Za-z0-9])'), set()),
       ('PTR', re.compile(r'(?<![A-Za-z0-9])PTR(?![A-Za-z0-9])'), {'xx_XX'})]


def gate(msgid, new, old=None, locale='de_DE'):
    return arc.gate(msgid, new, old, locale, DNT)


class GateTest(unittest.TestCase):
    def assertRejected(self, msgid, new, fragment, **kw):
        bad = gate(msgid, new, **kw)
        self.assertTrue(any(fragment in b for b in bad), bad)

    def test_placeholders(self):
        self.assertEqual(gate('Use %s now', 'Jetzt %s benutzen'), [])
        self.assertRejected('Use %s now', 'Jetzt benutzen', 'placeholder')

    def test_positional_reordering_allowed(self):
        self.assertEqual(gate('%1$s of %2$s', '%2$s von %1$s'), [])

    def test_hex_and_percent_literal(self):
        self.assertEqual(gate('Code %04X', 'Kode %04X!'), [])
        self.assertRejected('Code %04X', 'Kode %X', 'placeholder')
        self.assertEqual(gate('100%% done', 'zu 100%% fertig'), [])
        self.assertRejected('100%% done', 'zu 100% fertig', 'placeholder')

    def test_html_tags(self):
        self.assertEqual(gate('Click <b>here</b>', 'Hier <b>klicken</b>'), [])
        self.assertRejected('Click <b>here</b>', 'Hier klicken', 'HTML tags')
        self.assertRejected('Click <b>here</b>', 'Hier <b>klicken', 'HTML tags')

    def test_tokens(self):
        self.assertEqual(gate('Hi [NAME]', 'Hallo [NAME]'), [])
        self.assertRejected('Hi [NAME]', 'Hallo [NAMEN]', '[TOKEN]')

    def test_ip_literal(self):
        self.assertEqual(gate('Host 10.0.0.1 is up', 'Host 10.0.0.1 ist da'), [])
        self.assertRejected('Host 10.0.0.1 is up', 'Host 10.0.0.2 ist da', 'IP literals')
        self.assertRejected('Host 10.0.0.1 is up', 'Host ist da', 'IP literals')

    def test_identifier(self):
        self.assertEqual(gate('Set pdns_db_name', 'pdns_db_name setzen'), [])
        self.assertRejected('Set pdns_db_name', 'Datenbank setzen', 'identifiers dropped')

    def test_whitespace_runs(self):
        self.assertEqual(gate('  Name: ', '  Name: '.replace('Name', 'Titel')), [])
        self.assertRejected('  Name: ', ' Titel: ', 'whitespace')
        self.assertRejected('Name: ', 'Titel:', 'whitespace')
        self.assertRejected('Name', 'Titel ', 'whitespace')

    def test_dnt_literals(self):
        self.assertEqual(gate('SOA record', 'SOA Eintrag'), [])
        self.assertEqual(gate('SOA record', 'soa Eintrag'), [])
        self.assertRejected('SOA record', 'Eintrag', 'do-not-translate')

    def test_dnt_locale_exception(self):
        self.assertEqual(gate('PTR record', 'Eintrag', locale='xx_XX'), [])
        self.assertRejected('PTR record', 'Eintrag', 'do-not-translate')

    def test_english_fallback_and_unchanged(self):
        self.assertRejected('Save', 'Speichern', 'untranslated English fallback', old='Save')
        self.assertEqual(gate('Save', 'Speichern', old='Sichern'), [])
        self.assertRejected('Save', 'Save', 'still the English source')
        self.assertRejected('Save', ' ', 'empty')

    def test_plural_form_old_none_skips_fallback_rule(self):
        self.assertEqual(gate('%d item', '%d Ding', old=None), [])


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def review(self, name, data):
        with open(os.path.join(self.tmp.name, name), 'w', encoding='utf-8') as fh:
            json.dump(data, fh)

    def run_quiet(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = fn(*args)
        return result, out.getvalue()

    PO = ('msgid ""\nmsgstr ""\n"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n'
          'msgid "Save"\nmsgstr "Save"\n\n'
          'msgid "%d item"\nmsgid_plural "%d items"\n'
          'msgstr[0] "%d item"\nmsgstr[1] "%d items"\n')

    def test_msgstr_correction_for_plural_entry_refused(self):
        self.review('OUT_de_DE_term.json', {'%d item': '%d Ding'})
        entries = poutil.parse_string(self.PO)
        result, out = self.run_quiet(arc.apply_msgstr, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertIsNone(result)
        self.assertIn('plural entry: use --plurals', out)

    def test_msgstr_valid_applies_and_clears_flag(self):
        self.review('OUT_de_DE_term.json', {'Save': 'Speichern'})
        po = self.PO.replace('msgid "Save"\nmsgstr "Save"',
                             '#, fuzzy\nmsgid "Save"\nmsgstr "Sichern"')
        entries = poutil.parse_string(po)
        (fixes, write), _ = self.run_quiet(arc.apply_msgstr, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertEqual(list(fixes), ['Save'])
        self.assertEqual(write(), 1)
        out = poutil.render(entries)
        self.assertIn('msgstr "Speichern"', out)
        self.assertNotIn('fuzzy', out)

    def test_msgstr_correction_of_english_fallback_refused(self):
        self.review('OUT_de_DE_term.json', {'Save': 'Speichern'})
        entries = poutil.parse_string(self.PO)
        result, out = self.run_quiet(arc.apply_msgstr, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertIsNone(result)
        self.assertIn('untranslated English fallback', out)

    def test_msgstr_unknown_msgid_aborts_all(self):
        self.review('OUT_de_DE_term.json', {'Save': 'Speichern', 'Nope': 'Nein'})
        entries = poutil.parse_string(self.PO)
        result, out = self.run_quiet(arc.apply_msgstr, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertIsNone(result)
        self.assertIn('msgid not in catalogue', out)
        self.assertEqual(entries[1].msgstr, 'Save')
        self.assertFalse(entries[1].dirty)

    def test_conflict_within_family_exits(self):
        self.review('OUT_de_DE_term1.json', {'Save': 'A'})
        self.review('OUT_de_DE_term2.json', {'Save': 'B'})
        with self.assertRaises(SystemExit) as ctx:
            arc.collect_msgstr('de_DE', self.tmp.name)
        self.assertIn('CONFLICT', str(ctx.exception))

    def test_later_family_overrides_earlier(self):
        self.review('OUT_de_DE_term.json', {'Save': 'A'})
        self.review('OUT_de_DE_fix.json', {'Save': 'B'})
        fixes, _ = self.run_quiet(arc.collect_msgstr, 'de_DE', self.tmp.name)
        self.assertEqual(list(fixes), ['Save'])
        self.assertEqual(fixes['Save'], 'B')

    def test_plural_files_ignored_in_msgstr_mode(self):
        self.review('OUT_de_DE_plr1.json', {'%d item': {'0': '%d Ding'}})
        fixes, _ = self.run_quiet(arc.collect_msgstr, 'de_DE', self.tmp.name)
        self.assertEqual(fixes, {})

    def test_plurals_apply(self):
        self.review('OUT_de_DE_plr1.json', {'%d item': {'0': '%d Ding', '1': '%d Dinge'}})
        entries = poutil.parse_string(self.PO)
        (fixes, write), _ = self.run_quiet(arc.apply_plurals, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertEqual(write(), 2)
        self.assertEqual(entries[2].plurals, {0: '%d Ding', 1: '%d Dinge'})

    def test_plurals_index_out_of_range_refused(self):
        for bad in ('2', '-1'):
            with self.subTest(index=bad):
                self.review('OUT_de_DE_plr1.json', {'%d item': {bad: '%d Ding'}})
                entries = poutil.parse_string(self.PO)
                result, out = self.run_quiet(arc.apply_plurals, 'de_DE', 'x.po', entries,
                                             self.tmp.name)
                self.assertIsNone(result)
                self.assertIn('outside 0..1', out)

    def test_plurals_on_singular_entry_refused(self):
        self.review('OUT_de_DE_plr1.json', {'Save': {'0': 'Speichern'}})
        entries = poutil.parse_string(self.PO)
        result, out = self.run_quiet(arc.apply_plurals, 'de_DE', 'x.po', entries, self.tmp.name)
        self.assertIsNone(result)
        self.assertIn('not a plural entry', out)


class LoadDntTest(unittest.TestCase):
    def test_shipped_glossary_loads(self):
        dnt = arc.load_dnt()
        self.assertTrue(dnt)
        term, pattern, skip = dnt[0]
        self.assertTrue(pattern.search(term))
        self.assertIsInstance(skip, set)


if __name__ == '__main__':
    unittest.main()
