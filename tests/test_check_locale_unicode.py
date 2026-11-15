import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import check_locale_unicode as clu  # noqa: E402

SAMPLES = {
    'ru': 'Привет, мир',
    'el': 'Γειά σου κόσμε',
    'ar': 'مرحبا بالعالم',
    'vi': 'Xin chào Việt Nam',
    'de': 'Größe der Straße',
}
CLEAN_LATIN = 'café naïve señor Ångström Größe façade'


def mojibake(text, codec):
    """UTF-8 bytes misread as the codec; None when the codec cannot decode them."""
    try:
        return text.encode('utf-8').decode(codec)
    except UnicodeDecodeError:
        return None


class MojibakeTest(unittest.TestCase):
    def test_detected_and_repaired_byte_exact(self):
        for lang, text in SAMPLES.items():
            for codec in ('latin-1', 'cp1252'):
                broken = mojibake(text, codec)
                if broken is None:
                    continue
                with self.subTest(lang=lang, codec=codec):
                    self.assertNotEqual(broken, text)
                    hits = clu.find_mojibake(broken)
                    self.assertTrue(hits)
                    self.assertEqual(clu.repair_mojibake(broken), text)
                    self.assertEqual(clu.repair_mojibake(broken).encode('utf-8'),
                                     text.encode('utf-8'))

    def test_find_returns_repaired_bytes(self):
        broken = mojibake('é', 'latin-1')
        (offset, line, seq, raw), = clu.find_mojibake('x ' + broken)
        self.assertEqual((offset, line), (2, 1))
        self.assertEqual(raw, 'é'.encode('utf-8'))
        self.assertEqual(seq, broken.encode('utf-8'))

    def test_cp1252_punctuation_run(self):
        # right single quote U+2019 is E2 80 99 in UTF-8
        broken = 'â€™'
        self.assertEqual(clu.repair_mojibake('it' + broken + 's'), 'it’s')

    def test_line_number(self):
        broken = mojibake('é', 'latin-1')
        self.assertEqual(clu.find_mojibake('a\nb\n' + broken)[0][1], 3)

    def test_clean_scripts_no_hits(self):
        for lang, text in SAMPLES.items():
            with self.subTest(lang=lang):
                self.assertEqual(clu.find_mojibake(text), [])
                self.assertEqual(clu.repair_mojibake(text), text)

    def test_legit_accented_latin_untouched(self):
        self.assertEqual(clu.find_mojibake(CLEAN_LATIN), [])
        self.assertEqual(clu.repair_mojibake(CLEAN_LATIN), CLEAN_LATIN)

    def test_adjacent_accents_that_are_not_utf8_untouched(self):
        # Ã followed by a letter, not a continuation byte
        self.assertEqual(clu.find_mojibake('Ãb'), [])

    def test_legit_pairs_that_reverse_into_unused_scripts_untouched(self):
        # "ß«" and "É»" decode to valid NKo / IPA code points, which no locale uses
        for text in ('»Fuß«', 'É»', 'À x'):
            with self.subTest(text=text):
                self.assertEqual(clu.find_mojibake(text), [])
                self.assertEqual(clu.repair_mojibake(text), text)


class HiddenAndMtTest(unittest.TestCase):
    def test_zero_width_flagged(self):
        hits = clu.find_hidden('a​b', 'de_DE')
        self.assertEqual([(h[0], h[1], h[3]) for h in hits], [(1, 2, 'zero-width')])

    def test_zwnj_legit_in_persian(self):
        self.assertEqual(clu.find_hidden('a‌b', 'fa_IR'), [])
        self.assertTrue(clu.find_hidden('a‌b', 'de_DE'))

    def test_mt_music_note(self):
        po = 'msgid "OK"\nmsgstr "♪ OK ♪"\n'
        (lineno, content, chars), = clu.find_mt_artifacts(po, 'ms_MY')
        self.assertEqual(chars, {'♪': 2})

    def test_mt_char_in_msgid_is_deliberate(self):
        po = 'msgid "♪"\nmsgstr "♪"\n'
        self.assertEqual(clu.find_mt_artifacts(po, 'ms_MY'), [])

    def test_greek_only_legit_in_el(self):
        po = 'msgid "alpha"\nmsgstr "α"\n'
        self.assertTrue(clu.find_mt_artifacts(po, 'de_DE'))
        self.assertEqual(clu.find_mt_artifacts(po, 'el_GR'), [])


if __name__ == '__main__':
    unittest.main()
