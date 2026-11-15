import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import check_translation_integrity as cti  # noqa: E402


class TranslitTest(unittest.TestCase):
    def test_cyrillic_translit_table(self):
        self.assertEqual('ДНС'.translate(cti.TRANSLIT), 'DNS')
        self.assertEqual('АПИ'.translate(cti.TRANSLIT), 'API')

    def test_rescripted_acronym_cyrillic(self):
        self.assertTrue(cti._rescripted_acronym('Edit DNS zone', 'Редактировать ДНС зону'))

    def test_latin_acronym_kept_is_fine(self):
        self.assertFalse(cti._rescripted_acronym('Edit DNS zone', 'Редактировать DNS зону'))

    def test_genuine_capitalised_word_not_flagged(self):
        self.assertFalse(cti._rescripted_acronym('IMPORTANT note', 'ВАЖНО заметка'))

    def test_homoglyph_form(self):
        # Cyrillic A, R, I look identical to the Latin API
        self.assertTrue(cti._rescripted_acronym('Use API', 'Использовать \u0410\u0420\u0406'))

    def test_umlaut_translit(self):
        self.assertEqual(cti._translit('Füße'), 'fuesse')
        self.assertEqual(cti._translit('Äpfel'), 'aepfel')
        self.assertEqual(cti._translit('fuer'), cti._translit('für'))


class CheckEntryTest(unittest.TestCase):
    def hits(self, src, dst, locale='de_DE'):
        return cti.check_entry(src, dst, locale)

    def test_clean_pair(self):
        self.assertEqual(self.hits('Save the file', 'Datei speichern'), [])

    def test_clean_pair_with_placeholder_and_tag(self):
        self.assertEqual(self.hits('Delete <b>%s</b>', '<b>%s</b> löschen'), [])

    def test_dropped_placeholder(self):
        self.assertIn('placeholder', self.hits('Delete %s items', 'Elemente löschen'))

    def test_broken_tag(self):
        self.assertIn('tags', self.hits('Click <b>here</b>', 'Hier <b>klicken'))

    def test_dropped_token(self):
        self.assertIn('tokens', self.hits('Hi [NAME]', 'Hallo'))

    def test_dropped_identifier(self):
        self.assertIn('identifiers', self.hits('See pdns_db_name', 'Siehe Datenbank'))

    def test_trailing_space_lost(self):
        self.assertIn('trailing', self.hits('Name: ', 'Name:'))

    def test_rescripted_acronym_flagged_as_mixedscript(self):
        self.assertIn('mixedscript',
                      self.hits('Edit DNS zone', 'Редактировать ДНС зону', 'ru_RU'))

    def test_placeholder_leak(self):
        self.assertIn('leak', self.hits('Count: %d', 'Anzahl: %dx'))


if __name__ == '__main__':
    unittest.main()
