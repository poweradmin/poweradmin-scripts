#!/usr/bin/env python3
"""Check translation catalogues for the damage classes a past MT import left behind.

Usage:
  python3 scripts/check_translation_integrity.py [--locale=xx_XX] [--class=name,...]
                                                 [--examples=N] [--quiet]

Exits non-zero if any hard class reports a hit. Hard classes are the ones that
break the string at runtime or state something factually different from the
source; soft classes are reported but never fail the run, because each has a
known false-positive mode documented on its checker.

Classes
  placeholder  printf set differs from the msgid (hard)
  leak         a letter glued onto a placeholder, e.g. "%sZ" (hard)
  tags         HTML tag multiset differs (hard)
  tokens       [BRACKET] token multiset differs (hard)
  identifiers  a config key, table name or path is not verbatim (hard)
  trailing     msgid ends in whitespace but the translation does not (hard)
  boilerplate  text from outside this application, e.g. Twitter chrome (hard)
  repetition   a short token repeated until it is most of the string (hard)
  mixedscript  a word mixes Latin with Greek or Cyrillic, or an acronym was
               rewritten wholesale in the target script, e.g. DNS as "ДНС" (hard)
  ipliteral    an IPv4 or IPv6 example address differs from the source (hard)
  nearmiss     a technical acronym came through misspelt, e.g. AAAA as "AAA" (hard)
  literalmask  a format mask such as YYYYMMDDnn or xxxx:xxxx is not verbatim (hard)
  protocoldowngrade  HTTPS rendered as HTTP, or IPv6 as IPv4 (hard)
  antonym_collision  two msgids that are opposites share one translation, e.g.
               "Server Running" and "Server Not Running" (hard)
  fragment_punctuation  a msgid the code appends to was closed off with ")", "?"
               or "." so the appended value renders after it (hard)
  numerals     a quantity stated in the msgid is not stated in the translation (soft)
  truncation   translation under half the source length, non-CJK only (soft)
  rrtype       a record type or protocol name is missing entirely (soft)
  crosswire    the translation appears to render a different msgid (soft)
  englishleak  an English word left untranslated inside a non-Latin script (soft)
  msgstr_collapse  distinct msgids came back sharing one translation (soft)
  negation_loss    the msgid negates something and the translation does not (soft)
  diacritic    a word is spelt without its accents while the accented spelling
               dominates the same catalogue, e.g. "metadonnees" in fr_FR (soft)
  term_consistency  a source term is rendered with something other than the
               agreed target wording from locale_terms.json (soft)

Plural entries are checked too: poutil keeps their translations in `plurals` and
leaves `msgstr` empty, so filtering on `msgstr` alone skipped 12 entries per
catalogue in every class. Each plural form is compared against `msgid_plural`.
"""
import difflib
import itertools
import json
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

HARD = ('placeholder', 'leak', 'tags', 'tokens', 'identifiers', 'trailing', 'boilerplate',
        'repetition', 'mixedscript', 'ipliteral', 'nearmiss', 'literalmask',
        'protocoldowngrade', 'antonym_collision', 'fragment_punctuation',
        'escape_artifact', 'unlocalized', 'plural_forms')
SOFT = ('numerals', 'truncation', 'rrtype', 'crosswire', 'englishleak',
        'msgstr_collapse', 'negation_loss', 'diacritic', 'term_consistency')

# Chinese, Japanese and Korean are far more compact than English, so the length
# ratio that finds dropped clauses elsewhere flags healthy text here.
CJK = {'zh_CN', 'zh_TW', 'ja_JP', 'ko_KR'}

# Catalogues written in a script other than Latin. An English word standing in
# one of these is visible at a glance, which is what makes `englishleak` worth
# running there and hopeless everywhere else: in a Latin-script target there is
# no way to tell a leaked English word from a cognate the language really uses.
NONLATIN = {'ar_SA', 'bg_BG', 'el_GR', 'fa_IR', 'he_IL', 'hi_IN', 'ja_JP', 'ko_KR',
            'ru_RU', 'sr_RS', 'th_TH', 'uk_UA', 'zh_CN', 'zh_TW'}

# Unicode name prefixes the writing system of each non-Latin catalogue uses. A
# translation carrying none of them is either still English or, as ru_RU and
# uk_UA both held for the zone-metadata strings, a Latin transliteration
# ("Redaktirovat' metadannye") that reads as gibberish in the running UI.
SCRIPT_OF = {
    'ar_SA': ('ARABIC',), 'fa_IR': ('ARABIC',),
    'he_IL': ('HEBREW',), 'el_GR': ('GREEK',),
    'bg_BG': ('CYRILLIC',), 'ru_RU': ('CYRILLIC',),
    'uk_UA': ('CYRILLIC',), 'sr_RS': ('CYRILLIC',),
    'hi_IN': ('DEVANAGARI',), 'th_TH': ('THAI',),
    'ja_JP': ('CJK', 'HIRAGANA', 'KATAKANA'), 'ko_KR': ('HANGUL', 'CJK'),
    'zh_CN': ('CJK',), 'zh_TW': ('CJK',),
}
# Words that stay Latin in every catalogue, so a msgid built only from them
# needs no target-script character: "API URL" is a legitimate "URL API".
SCRIPTLESS = re.compile(r'^(?:[A-Z0-9]{2,}|\W+|\d+)$')

# Flags, width and precision are part of the spec: "0x%04X" broken into "0x% 4X"
# is a real defect that a bare "%[sdfucxXob]" pattern reads as no placeholder at all.
# The space flag is deliberately excluded - it is legal C but unused here, and it
# makes the literal "100% uptime" parse as a placeholder.
SPEC = r'[-+#0]*\d*(?:\.\d+)?[sdfucxXobeEgG]'
PRINTF = re.compile(rf'%(?:\d+\$)?{SPEC}|%%')
LEAK = re.compile(rf'%(?:\d+\$)?{SPEC}[A-Za-z]')


def _has_leak(text):
    """An escaped %% is a literal percent sign, never a placeholder.

    Languages that suffix percentages (hu_HU "100%%-ot", tr_TR "%%50'si") would
    otherwise read the second % as a spec and flag the suffix as a glued letter.
    """
    return bool(LEAK.search(text.replace('%%', '\x00\x00')))
# Real markup only. Angle brackets are also used for metavariables such as
# <priority> or <hash>._openpgpkey.<domain>, which translators legitimately
# render in the target language - matching those would be almost all noise.
TAG = re.compile(r'</?(?:code|strong|em|b|i|u|a|br|p|span|div|ul|ol|li|small|sup|sub)\b[^<>]*>',
                 re.I)
TOKEN = re.compile(r'\[[A-Z0-9_]+\]')
# Numbers. Three token shapes tried in order: a group-separated figure
# (1 000 000, 1.000.000), a decimal, then a plain run. Each is reduced to its
# digits alone, which makes "42849672.95" and "42.849.672,95" the same number and
# is what removes the decimal- and thousands-separator noise that made this class
# unreadable.
NUMBER = re.compile(r'\d{1,3}(?:[.,    ]\d{3})+(?:[.,]\d+)?'
                    r'|\d+[.,]\d+'
                    r'|\d+')
RANGE = re.compile(r'(\d+)\s*[-‐-―]\s*(\d+)')
# Spans whose digits are part of a name, not a quantity: URLs, printf specs,
# algorithm and record-type names (Ed25519, SHA-256, NSEC3, IPv4, base64),
# ordinals, and IPv4/IPv6 literals, which `ipliteral` owns.
NUMBER_STRIP = re.compile(
    r'(?:https?://|www\.)\S+'
    r'|%(?:\d+\$)?[-+#0]*\d*(?:\.\d+)?[a-zA-Z]'
    r'|\b[A-Za-z]+[0-9][A-Za-z0-9]*\b'
    r'|\b[A-Za-z]+-[0-9][A-Za-z0-9-]*\b'
    r'|\b[0-9]+(?:st|nd|rd|th)\b'
    r'|\b[0-9]+[A-Za-z]+\b'
    r'|(?<![0-9A-Za-z.])\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?'
    r'|(?<![0-9A-Za-z:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:/\d{1,3})?',
    re.I)
# A citation written "RFC-2317" would otherwise be eaten by the name rule above
# while the msgid's "RFC 2317" is not, so every locale that hyphenates reported
# every RFC reference it has.
CITATION = re.compile(r'\b(rfc|bcp|std)[\s‐-―-]+(?=\d)', re.I)
# Digits outside ASCII, so Persian "۴۲", Devanagari "४२", Thai "๔๒" and
# Arabic-Indic "٤٢" compare equal to "42" instead of reporting as a loss.
NON_ASCII_DIGITS = {cp: str(unicodedata.digit(chr(cp)))
                    for cp in range(0x600, 0x1E950)
                    if unicodedata.category(chr(cp)) == 'Nd' and not chr(cp).isascii()}
IDENTIFIER = re.compile(
    r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b'
    r'|\b(?:dns|api|misc|db|ldap|mail|pdns)\.[a-z_.]+\b'
    r'|\b[\w-]+\.(?:php|html|twig|js|css|sql|dat|json|ya?ml|conf|ini)\b'
)
# Chrome from other products. Anchored so Danish "citationstegn" and French
# "Félicitations" do not match on the "citation" substring. The second group is
# warez and subtitle-release chrome the import spliced in; the Persian entries
# match the full phrase because "دانلود" alone legitimately renders "Download".
BOILERPLATE = re.compile(
    r'\b(?:tweet|tweets|retweet|twitter|facebook|instagram|wikipedia|accessdate'
    r'|hashtag|opensubtitles|addic7ed|yify|synced by|ripped by)\b'
    r'|دانلود بازی|دانلود زیرنویس|دانلود فیلم|زیرنویس فارسی'
    r'|titrat u sollen', re.I
)
# Wiki edit-link chrome, e.g. Hebrew "[עריכת קוד מקור | עריכה]". Matched structurally
# rather than by phrase so it covers any language: a bracketed group with a pipe
# separator is wiki markup, never one of this application's [TOKEN]s.
WIKICHROME = re.compile(r'\[[^\[\]]*\|[^\[\]]*\]')
# Acronyms only: hyphen excluded so "DNS-Assistenten" yields DNS, and a 3-char
# floor so uppercase emphasis words like ALL and KEY stay out.
ACRONYM = re.compile(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{2,}(?![A-Za-z0-9])')
# Record types and protocol names, which survive verbatim in every language.
# Names that are also ordinary English words (KEY, SIG, URI, CERT, LOC, RP,
# ALIAS) are excluded, because translating those is correct.
WORD = re.compile(r'[^\W\d_]{2,}', re.UNICODE)
# Boundaries are ASCII-only on purpose: Korean attaches particles directly to
# an address ("192.168.1.0/24의"), and a \w boundary read that as a mismatch.
# The trailing dot of a sentence is allowed; a dot that starts another label
# is not, so "1.1.168.192.in-addr.arpa" is never matched in part.
IPV4 = re.compile(r'(?<![0-9A-Za-z.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?'
                  r'(?![0-9A-Za-z]|\.[0-9A-Za-z])')
# Two to four dotted groups, so a mangled address that has lost an octet
# ("192.0.2/24", "0.0.0") is still recognisable as the wreck of one. Matched only
# against a specific missing source address, never on its own, because on its own
# this also matches version and RFC section numbers.
DOTTED = re.compile(r'(?<![0-9A-Za-z.])\d{1,3}(?:\.\d{1,3}){1,3}(?:/\d{1,3})?'
                    r'(?![0-9A-Za-z]|\.[0-9A-Za-z])')
# Colon-separated hex groups, deliberately permissive: it has to match the
# damaged forms ("fec0:/10", ":1", ":::") as well as intact literals.
COLONHEX = re.compile(r'(?<![0-9A-Za-z:])(?=[0-9A-Fa-f]{0,4}:)'
                      r'[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){1,7}(?:/\d{1,3})?'
                      r'(?![0-9A-Za-z:])')
# Format masks the user has to type back verbatim: YYYYMMDDnn, YYYYMMDDHHmmSS,
# and the EUI/NID group forms xx-xx-xx-xx-xx-xx and xxxx:xxxx:xxxx:xxxx. The
# length floor and the doubled-character requirement are what keep ordinary
# source tokens over the same letters (DS, SSH, DH, mx) out of the set.
MASK = re.compile(r'(?<![A-Za-z0-9])[YMDHmSxn]{2,}(?:[:-][YMDHmSxn]{2,})*(?![A-Za-z0-9])')
DOUBLED = re.compile(r'(.)\1')
# Protocol names that must not be traded for a weaker one. Case-insensitive
# because the damage is in the name, not its casing.
HTTPS_NAME = re.compile(r'(?<![A-Za-z0-9])https(?![A-Za-z0-9])', re.I)
HTTP_NAME = re.compile(r'(?<![A-Za-z0-9])http(?![A-Za-z0-9])', re.I)
IPV6_NAME = re.compile(r'(?<![A-Za-z0-9])ipv6(?![A-Za-z0-9])', re.I)
IPV4_NAME = re.compile(r'(?<![A-Za-z0-9])ipv4(?![A-Za-z0-9])', re.I)
IP_SHORT = re.compile(r'(?<![A-Za-z0-9])ip[46](?![A-Za-z0-9])', re.I)
RRTYPE = frozenset('''
    SOA CNAME AAAA CAA DNSKEY RRSIG NSEC NSEC3 TLSA SSHFP NAPTR HINFO SPF DKIM DMARC
    TSIG DNSSEC SVCB ZONEMD EUI48 EUI64 IPSECKEY OPENPGPKEY SMIMEA CSYNC DHCID
    TXT SRV PTR MX
'''.split())
SIGNIFICANT = re.compile(r'(?<![A-Za-z0-9])(?:[A-Z][A-Za-z0-9]{2,}|\d+)(?![A-Za-z0-9])')
# An acronym written in another script is a different string, so a Cyrillic
# "ДНС" never matches the DNS it names. Two ways this happens: homoglyphs, which
# look identical, and phonetic transliteration, which is what the import actually
# produced. `mixedscript` sees neither - a fully converted acronym is not mixed.
HOMOGLYPH = str.maketrans(
    'АВСЕНІЈКМОРЅТУХΑΒΕΖΗΙΚΜΝΟΡΤΥΧ',
    'ABCEHIJKMOPSTYXABEZHIKMNOPTYX',
)
TRANSLIT = str.maketrans(
    'АБВГДЕЗИЙКЛМНОПРСТУФЫЭ',
    'ABVGDEZIYKLMNOPRSTUFYE',
)
CAPRUN = re.compile(r'[А-ЯЁЀ-ЏΑ-Ω]{3,}')
STOPWORDS = {'The', 'And', 'For', 'You', 'Not', 'This', 'That', 'Use', 'Using',
             'Please', 'Only', 'All', 'Each', 'New'}

# Every uppercase run the source strings use, split by whether translating it is
# correct. The source vocabulary is a closed set of about 200 tokens, so listing
# the translatable ones is cheaper and far more precise than trying to tell an
# acronym from a word by shape. Anything not listed here is treated as technical
# and must survive verbatim. Borderline names are listed as ordinary on purpose:
# a term left out only costs recall, whereas a translatable word left in makes
# every locale that renders it correctly look damaged.
ORDINARY_CAPS = frozenset('''
    ALIAS ALL ALLOW BEGIN CERT COUNTER CRITICAL DEPRECATED DOMAIN EDIT END
    EXPERIMENTAL FROM GET HOSTMASTER IMPORTANT KEY LOC MAIL MUST NATIVE NO NOT
    NOTE NOTIFY OK ONCE ORIGIN POST PRIVATE PUBLIC RECOMMENDED REQUIRE RP SEP
    SERIAL SERVER SHOULD SIG STRONGLY TYPE URI WARNING ZONE
'''.split())
UPPERRUN = re.compile(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,}(?![A-Za-z0-9])')

# Everything a translation may legitimately carry in Latin letters: markup,
# bracket tokens, printf specs, URLs, hostnames and paths, config keys, and
# quoted or parenthesised spans, which hold UI labels quoted back at the reader
# ("Save As") and glosses that name the English term after translating it
# ("(replay attack)"). Both of those are good practice, not leakage.
LEAK_STRIP = re.compile(
    r'<[^<>]*>'
    r'|\[[A-Z0-9_]+\]'
    r'|%(?:\d+\$)?[-+#0]*\d*(?:\.\d+)?[a-zA-Z]|%%'
    r'|(?:https?://|www\.)\S+|\b[\w-]+(?:\.[\w-]+)+\b|/\S+'
    r'|\b[a-zA-Z][a-zA-Z0-9]*(?:[_-][a-zA-Z0-9]+)+\b'
    r'|"[^"]*"|\'[^\']*\'|[“”][^“”]*[“”]'
    r'|\([^()]*\)'
)
LATINWORD = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]{4,}(?![A-Za-z0-9])')
# Ordinary English the interface uses, restricted to words that are never a term
# of art here. Deliberately not a general word list: DNS and hosting vocabulary
# (apex, digest, wildcard, backend, selector, replay, canonical) is routinely
# kept in Latin on purpose in these locales, and every attempt to include it by
# shape rather than by name produced far more noise than findings. Words that
# are also SQL keywords or product names (select, insert, update, delete, save)
# are left out for the same reason: they appear untranslated in the privileges
# hint on purpose.
PROSE = frozenset('''
    about addresses authentication before cannot changed checked configuration
    configure credentials dashboard disable disabled display download edit
    editing emails enable enabled enter existing expected guidelines
    information invalid layer login logins logout logs management misses
    missing must options password permission permissions please preview
    properties queried recovery rejected review security selected selection
    session settings unknown updated username users zones
'''.split())


# Polarity. The negating prefixes are applied to the other word of a pair rather
# than listed pair by pair, so "sign/unsign" also covers signing/unsigning and
# signed/unsigned without enumerating every inflection. Enumerated over the whole
# source vocabulary, that rule produces exactly seven word pairs that are not
# polarity at all, listed in NOT_POLAR; "de-" is left out of the prefix set
# entirely because sign/design, fine/define and signed/designed all collide there,
# and its one real pair (activate/deactivate) is cheaper to list explicitly.
POLAR_PREFIX = ('un', 'in', 'dis')
NOT_POLAR = {'der', 'less', 'like', 'port', 'able', 'direction', 'line'}
POLAR_PAIRS = [('enable', 'disable'), ('enabled', 'disabled'), ('enabling', 'disabling'),
               ('show', 'hide'), ('shown', 'hidden'), ('showing', 'hiding'),
               ('add', 'remove'), ('added', 'removed'), ('adding', 'removing'),
               ('activate', 'deactivate'), ('activated', 'deactivated'),
               ('activating', 'deactivating'), ('active', 'inactive')]
POLAR_MAP = defaultdict(set)
for _a, _b in POLAR_PAIRS:
    POLAR_MAP[_a].add(_b)
    POLAR_MAP[_b].add(_a)
# Words whose presence flips the sense of a sentence, used both by
# `antonym_collision` and by `negation_loss` on the English side.
EN_NEGATION = frozenset('''
    not no never none cannot can't don't doesn't won't isn't aren't wasn't
    weren't shouldn't couldn't wouldn't hasn't haven't didn't without nor
    neither nothing
'''.split())
ENWORD = re.compile(r"[A-Za-z']+")
# Function words a sentence cannot end on, so a msgid ending in one is a
# fragment with something appended after it at runtime.
FRAGMENT_TAIL = frozenset('''
    a an the and or of to for in on at by with from into as is are be was were
    than that this these those about over under between per
'''.split())
# Auxiliaries only. Wh-words are excluded because a heading such as "How it
# works" is a complete phrase, and the two locales that render it with a
# question mark are doing nothing wrong.
QUESTION_OPENER = re.compile(
    r'(?:are|is|do|does|did|can|could|will|would|should|have|has)\b', re.I)
# Irregular inflection pairs, which the plural strip below cannot reach. Without
# these, every singular/plural message pair reads as a collapse in the languages
# that do not mark plural at all - Chinese, Japanese, Korean, Thai, Vietnamese,
# Malay - where translating both alike is correct.
MORPH_PAIRS = [('has', 'have'), ('is', 'are'), ('this', 'these'), ('that', 'those'),
               ('was', 'were'), ('doe', 'do'), ('it', 'them'), ('wa', 'were')]
MORPH_MAP = defaultdict(set)
for _a, _b in MORPH_PAIRS:
    MORPH_MAP[_a].add(_b)
    MORPH_MAP[_b].add(_a)
# English word pairs most languages have only one word for. Excluding them costs
# recall on a real collapse, and buys a class small enough that somebody reads it.
SYNONYM_PAIRS = [('delete', 'remove'), ('deleted', 'removed'), ('deleting', 'removing')]
SYNONYMS = defaultdict(set)
for _a, _b in SYNONYM_PAIRS:
    SYNONYMS[_a].add(_b)
    SYNONYMS[_b].add(_a)


# English negation on the source side. Only explicit markers: an "un-" or "in-"
# prefixed adjective was tried as well and had to be dropped, because most
# languages render "invalid" and "unavailable" with a positive-form word of their
# own and the arm reported roughly 180 entries per locale, nearly all correct.
EN_NEGATED = re.compile(
    r"(?<![A-Za-z'])(?:not|no|cannot|can't|never|nor|neither|nothing|without"
    r"|won't|don't|doesn't|isn't|aren't|didn't|shouldn't|couldn't|wouldn't"
    r"|hasn't|haven't|wasn't|weren't)(?![A-Za-z'])", re.I)
# Spans where an English "no" is a literal rather than a negation: the quoted
# DMARC policy value "none", the "p=none" form, and the SVCB parameter name
# "no-default-alpn". Without this the same dozen entries report in every locale.
EN_LITERAL = re.compile(r'"[^"]*"|\'[^\']*\'|[“”][^“”]*[“”]|\b\w+=\w+'
                        r'|\b[a-zA-Z][a-zA-Z0-9]*(?:[_-][a-zA-Z0-9]+)+\b')

# Negation markers per target language, calibrated by running the check over all
# 43 catalogues and reading what came out. The notation is deliberate:
#   word     matches as a whole word          ("nem", "ikke")
#   word-    matches at a word start          ("ne-" for Czech nemáte, nelze)
#   -word    matches at a word end            ("-maton" for Finnish tukematon)
#   -word-   matches anywhere                 (Turkish infixes)
# Locales in CLITIC are matched as plain substrings throughout, because they
# either write without spaces (Chinese, Japanese, Korean, Thai) or attach
# conjunctions and relativisers directly to the negated word (Arabic "ولا",
# Hebrew "שאין", Persian "نمی‌توان").
#
# The tables are deliberately over-broad. Missing a marker turns a correct
# translation into a false positive, while an over-broad marker only costs
# recall, so every ambiguous form is included.
NEGATION_MARKERS = {
    'ar_SA': 'لا ليس ليست لست غير لم لن دون بدون عدم لسنا لستم ولا يمكن فشل '
             'أبدا أبداً مطلقا لاشيء',
    'bg_BG': 'не- ни- без нито няма- липс- недост-',
    'bs_BA': 'ne- ni- bez nema niti nije nemate',
    'cs_CZ': 'ne- ni- bez nikdy žádn- ani nelze nic nikdo zakáz-',
    'da_DK': 'ikke ingen intet uden aldrig hverken u- mangler nej',
    'de_DE': 'nicht kein- nie ohne nichts weder un- fehlt nein niemals niemand',
    'el_GR': 'δεν δε μη μην όχι χωρίς ούτε ουδ- ανεπ- αδυνα- απο- μη- ποτέ κανέν- καμία '
             'καμιά κανείς τίποτα ουδέποτε',
    'es_ES': 'no sin ningún ninguna ningun nunca ni jamás tampoco falta nada nadie',
    'et_EE': 'ei pole pol- ära ilma ega ühtegi mitte- puudu- eba- -ta -tu -mata -matu '
             'kunagi ükski keegi väl- harva',
    'fa_IR': 'نمی نیست ندار نکن نشد نباید بدون هیچ غیر عدم ناموفق نا نمیت خیر نه نبود '
             'نشده نخواه هرگز نباش نشو نشون نکرد نمانده ناتوان',
    'fi_FI': 'ei en et emme ette eivät eikä ettei älä ilman ilman- epä- puuttu- ei- '
             '-maton -mätön -matta -mättä -mattom- -mätöm- koskaan mikään kukaan harvoin',
    'fr_FR': "ne n' n’ n'- n’- pas aucun aucune sans jamais ni non impossible manque "
             "personne rien nul introuvable inexistant inconnu indisponible insuffisant",
    'ga_IE': 'ní ní- níl nach gan gan- cha neamh- ná níor nár riamh choíche aon faic '
             'éinne mura-',
    'he_IL': 'לא אין ללא בלי אינ אסור אל נכשל ואין ואינ שלא אף לעולם כלום בלעד חסר',
    'hi_IN': 'नहीं नही मत बिना बगैर न कोई',
    'hr_HR': 'ne- ni- bez nema niti nije nemate',
    'hu_HU': 'nem ne nincs- sincs- sem nélkül nélkül- -nélkül- tilos mentes -mentes '
             '-talan -telen -atlan -etlen hiány- soha semmi senki',
    'id_ID': 'tidak tak bukan jangan tanpa belum tiada gagal takkan',
    'it_IT': 'non senza nessun nessuna mai né impossibile manca niente nulla',
    'ja_JP': 'ない なく なし ありませ ませ ぬ ず 不 未 無 非 失敗 いいえ ざる なけれ 決して 一切 除 以外',
    'ko_KR': '안 않 없 못 미 불 비 아니 아닙 아닌 아님 아닐 아니라 아니오 아니요 마세 마십 말아 '
             '절대 결코 아무 금지 제외 실패',
    'lt_LT': 'ne ne- ni- be nėra jok- negal- niekada niekas',
    'lv_LV': 'ne- nē nē- bez -bez- nav nekad neviens nedr- trūk- izņem-',
    'ms_MY': 'tidak tak bukan jangan tanpa belum tiada gagal takkan',
    'nb_NO': 'ikke ingen uten aldri ei intet hverken mangler nei',
    'nl_NL': 'niet geen nooit zonder nee on- ontbreekt niets niemand',
    'pl_PL': 'nie- ni- bez żad- brak ani nigdy nic nikt',
    'pt_BR': 'não nao sem nenhum nenhuma nunca nem jamais falta nada ninguém',
    'pt_PT': 'não nao sem nenhum nenhuma nunca nem jamais falta nada ninguém',
    'ro_RO': 'nu fără nici nici- ne- imposibil lipse- niciun niciuna niciodată nimic nimeni',
    'ru_RU': 'не- ни- без нет нельзя невозможно отсутств-',
    'sk_SK': 'ne- ni- bez nikdy žiad- ani nemož- chýba nič nikto zakáz- zabrán-',
    'sl_SI': 'ne- ni- brez nima niti',
    'sq_AL': "nuk s' mos pa pa- jo asnjë askush ska kurrë asgjë as-",
    'sr_RS': 'не- ни- без нема нити није ne- ni- bez nema nije',
    'sv_SE': 'inte ej ingen inga inget intet utan aldrig icke saknas o- nej',
    'th_TH': 'ไม่ ไร้ ปราศจาก ห้าม มิ ล้มเหลว อย่า',
    'tr_TR': 'değil değil- yok hiç hiç- hiçbir asla olmadan başarısız hayır '
             '-maz- -mez- -madı- -medi- -ama- -eme- -mıyor- -miyor- -muyor- -müyor- '
             '-maya- -meye- -mayı- -meyi- -mayın- -meyin- -mayan- -meyen- -madan- -meden- '
             '-masın- -mesin- -mamış- -memiş- -mama- -meme- -maks- -meks- -mekt- '
             '-sız- -siz- -suz- -süz-',
    'uk_UA': 'не- ні- без немає нема неможливо відсутн-',
    'vi_VN': 'không chưa đừng chẳng chớ thiếu vô',
    'zh_CN': '不 无 没 未 非 勿 别 禁 失败 缺 否',
    'zh_TW': '不 無 沒 未 非 勿 別 禁 失敗 缺 否',
}
CLITIC = {'ar_SA', 'fa_IR', 'he_IL', 'ja_JP', 'ko_KR', 'th_TH', 'zh_CN', 'zh_TW'}


def _negation_regex(locale):
    """Compile one locale's marker table. Word edges are unicode letter classes,
    because \\b treats a Greek or Cyrillic letter as a word character but the
    ASCII shorthand classes do not behave usefully next to combining marks."""
    start, end = r'(?<![^\W\d_])', r'(?![^\W\d_])'
    parts = []
    for marker in NEGATION_MARKERS[locale].split():
        if locale in CLITIC:
            parts.append(re.escape(marker.strip('-')))
        elif marker.startswith('-') and marker.endswith('-'):
            parts.append(re.escape(marker[1:-1]))
        elif marker.startswith('-'):
            parts.append(re.escape(marker[1:]) + end)
        elif marker.endswith('-'):
            parts.append(start + re.escape(marker[:-1]))
        else:
            parts.append(start + re.escape(marker) + end)
    return re.compile('|'.join(parts), re.I)


NEGATION_RE = {loc: _negation_regex(loc) for loc in NEGATION_MARKERS}


def _negation_loss(src, dst, locale):
    """The msgid negates something and the translation carries no negation at all.

    Soft, and three false-positive modes survive by design.

    Restructuring - "Could not send X" comes back as "Error sending X",
    "Cannot connect" as "Connection failed", "Page Not Found" as French
    "Page introuvable". The sentence is right and the marker is gone. Nothing
    mechanical separates this from a dropped negation.

    Morphology - Turkish negates with an infix and Finnish, Estonian and
    Hungarian with a caritive suffix, all of which vary with vowel harmony and
    consonant gradation. The tables list the forms this corpus actually uses;
    an unlisted form reads as a loss.

    Marker gaps - any negation word a language uses that is not in its table is
    a false positive, which is why the tables err heavily towards over-matching.

    The strongest hits, and the ones worth reading first, are short msgids built
    around a standalone "not" or "no": those are the "Server Not Running" and
    "No SAML providers are configured" shape, where the translation states the
    opposite of the source.
    """
    if locale not in NEGATION_RE:
        return False
    if not EN_NEGATED.search(EN_LITERAL.sub(' ', src)):
        return False
    # An English negation word carried through verbatim is not a loss: it is a
    # literal the translation kept, e.g. the enum label "(No key)".
    if EN_NEGATED.search(dst):
        return False
    return not NEGATION_RE[locale].search(dst)


def _placeholders(text):
    """Positional forms are legitimate reordering, so %1$d compares as %d."""
    return sorted(re.sub(r'\d+\$', '', p) for p in PRINTF.findall(text))


def _signature(text):
    return {t for t in SIGNIFICANT.findall(text) if t not in STOPWORDS}


def _rescripted_acronym(src, dst):
    """An acronym from the msgid rewritten in the target's own script.

    Only reported when the Latin form is absent from the translation, and only
    on an exact match after conversion, so a genuine target-language word in
    capitals ("ВАЖНО" for IMPORTANT) can never collide with it.
    """
    wanted = {a for a in ACRONYM.findall(src) if a not in dst}
    if not wanted:
        return False
    return any(run.translate(table) in wanted
               for run in CAPRUN.findall(dst)
               for table in (HOMOGLYPH, TRANSLIT))


def _is_subsequence(short, long_):
    it = iter(long_)
    return all(ch in it for ch in short)


def _near_miss(src, dst):
    """An uppercase source token that came back misspelt rather than translated.

    Only fires when the correct token is absent and the translation carries an
    uppercase Latin run close enough to be a corruption of it. Two arms, because
    the two token kinds need opposite treatment:

    tech - a term that is never translated (record types, protocol and algorithm
    names, RCODEs). Any similar-looking replacement is damage, so a similarity
    ratio is enough. Exact anagrams are excluded: several languages localise an
    initialism by reordering it, e.g. French MFA as "AMF", which is correct.

    del - an ordinary English word set in capitals for emphasis. These are
    supposed to be translated, and an uppercase translation ("MUST NOT" as "TIDAK
    BOLEH", NOTE as "NOTA") looks exactly like corruption to any edit-distance
    test, so similarity is useless here. Only an internal deletion is reported -
    the target must be a strict subsequence of the source, share its first two
    letters and keep most of its length, which is what NOTE as "NOE" and
    EXPERIMENTAL as "EXPERIMAL" look like and no real translation does. A cognate
    that merely drops a suffix (PRIVATE as Danish "PRIVAT") is a prefix, not an
    internal deletion, and is excluded. The cost of this restraint is that a
    substitution such as CRITICAL as "CRITATIKE" goes unreported: nothing
    mechanical separates it from a legitimate uppercase translation.
    """
    src_toks = set(UPPERRUN.findall(src))
    candidates = [t for t in set(UPPERRUN.findall(dst)) if t not in src_toks and t not in src]
    if not candidates:
        return False
    for token in src_toks:
        if len(token) < 3 or token in dst:
            continue
        for cand in candidates:
            if token in ORDINARY_CAPS:
                if (len(cand) >= 3 and len(token) > len(cand) >= len(token) * 0.7
                        and token[:2] == cand[:2] and cand != token[:len(cand)]
                        and _is_subsequence(cand, token)):
                    return True
                continue
            if sorted(token) == sorted(cand):
                continue
            ratio = difflib.SequenceMatcher(None, token, cand).ratio()
            overlap = len(set(token) & set(cand)) / len(set(token))
            if ratio >= 0.7 or (overlap >= 0.75 and ratio >= 0.5
                                and abs(len(token) - len(cand)) <= 2):
                return True
    return False


def _ip_literal(src, dst):
    """An example address that came back different from the one in the msgid.

    Three arms. The first is the original whole-address comparison. The other two
    were added after checking this class against the damage it was meant to catch:
    on real pre-fix catalogues it fired on "192.0.2.0/24" becoming "192.0.2.24"
    but stayed silent on "192.0.2.0/24" becoming "192.0.2/24", on "0.0.0.0"
    becoming "0.0.0" and on "10.0.0.0/20" becoming "10.0.0/20". The reason is that
    a truncated address no longer parses as one, which leaves `dst_ips` empty and
    trips the guard below, so the worse the damage the quieter the check got. IPv6
    was not covered at all, so "::1" as ":1" and "fec0::/10" as "fec0:/10" passed
    as well.
    """
    src_ips, dst_ips = set(IPV4.findall(src)), set(IPV4.findall(dst))
    # Only when the translation carries addresses of its own: a translation
    # that drops the example entirely is a different defect.
    if src_ips and dst_ips and src_ips != dst_ips:
        return True

    missing = [a for a in src_ips if a not in dst]
    if missing:
        strays = [t for t in set(DOTTED.findall(dst)) if t not in src]
        # Sharing the leading group is what makes a stray number the wreck of
        # this address rather than a section number that happens to have dots.
        if any(a.split('.')[0] == t.split('.')[0] for a in missing for t in strays):
            return True

    src_v6 = {t for t in COLONHEX.findall(src) if '::' in t or t.count(':') >= 3}
    missing = [a for a in src_v6 if a not in dst]
    if missing:
        strays = [t for t in set(COLONHEX.findall(dst)) if t not in src]
        return any(difflib.SequenceMatcher(None, a, t).ratio() >= 0.6
                   for a in missing for t in strays)
    return False


def _protocol_downgrade(src, dst):
    """A protocol name swapped for a different one, always in the weaker direction.

    Reported only when the correct name is absent and the wrong one is present,
    so a translation that simply drops the mention is left to other classes.
    """
    if HTTPS_NAME.search(src) and not HTTPS_NAME.search(dst) and HTTP_NAME.search(dst):
        return True
    if IPV6_NAME.search(src) and not IPV6_NAME.search(dst) and IPV4_NAME.search(dst):
        return True
    if IPV4_NAME.search(src) and not IPV4_NAME.search(dst) and IPV6_NAME.search(dst):
        return True
    # "IP4" and "IP6" are not names of anything; they are IPv4 and IPv6 with the
    # version marker eaten.
    return bool(IP_SHORT.search(dst) and not IP_SHORT.search(src)
                and (IPV4_NAME.search(src) or IPV6_NAME.search(src)))


def _numeric_text(text):
    """Digits normalised to ASCII, name-borne digits removed. The citation rule
    runs first: it turns "RFC-2317" into "RFC 2317" so the name rule below does
    not swallow the RFC number along with the hyphen."""
    text = CITATION.sub(lambda m: m.group(1) + ' ', text.translate(NON_ASCII_DIGITS))
    return NUMBER_STRIP.sub(' ', text)


def _numbers(text, minimum=1):
    return {n.lstrip('0') or '0'
            for n in (re.sub(r'\D', '', t) for t in NUMBER.findall(_numeric_text(text)))
            if len(n) >= minimum}


def _ranges(text):
    return {(a.lstrip('0') or '0', b.lstrip('0') or '0')
            for a, b in RANGE.findall(_numeric_text(text))}


def _numbers_lost(src, dst):
    """A quantity stated in the msgid that the translation does not state.

    Two-digit floor, because at one digit the class fills with legitimate
    spelled-out small numbers - "must be 0 or empty" as Arabic "صفر", "1 zone" as
    "one zone", "4 fields" as "four fields" - which are correct translations. The
    cost is that a lost lone "0" goes unreported, e.g. the unsigned range
    "(0-4294967295)" rendered "(-4294967295)".

    The range arm buys part of that back: an "a-b" range in the msgid that the
    translation does not state as a range is reported, but only when an endpoint
    is missing outright, so writing the range in words - Arabic "from 240 to 255",
    Persian "از 240 تا 255" - does not count.
    """
    if _numbers(src, 2) - _numbers(dst, 2):
        return True
    lost = _ranges(src) - _ranges(dst)
    if not lost:
        return False
    present = _numbers(dst)
    return any(not set(pair) <= present for pair in lost)


def _fragment_punctuation(src, dst):
    """A msgid that continues at runtime, closed off by the translation.

    These msgids are half a sentence: the code appends a key ID, a zone name or
    a count straight after them. A translation that finishes the sentence turns
    "(ID" plus " 5" into "(ID) 5", and "delete the slave zone" plus " example.com"
    into "delete the slave zone? example.com".

    Four shapes of unfinished msgid, each paired with the punctuation that closes
    it: an unclosed bracket answered by ")", a trailing colon or a trailing
    function word answered by a full stop, and an inverted question with no
    question mark answered by one. The colon arm is the loosest of the four - a
    label whose translation ends "." rather than ":" would be caught by it and is
    a smaller problem than the rest - but no catalogue produced one.
    """
    s, d = src.rstrip(), dst.rstrip()
    if not s or not d:
        return False
    if s.count('(') > s.count(')') and d.endswith(')'):
        return True
    if s.endswith(':') and d[-1] in '?.!':
        return True
    if not s[-1].isalnum():
        return False
    if s.split()[-1].strip('.,;:!?()[]"\'').lower() in FRAGMENT_TAIL and d[-1] in '?.!':
        return True
    return bool(QUESTION_OPENER.match(s) and d.endswith('?'))


def _masks(text):
    return {m for m in MASK.findall(text) if len(m) >= 6 and DOUBLED.search(m)}


def _english_leak(src, dst):
    """An ordinary English word left standing inside a non-Latin translation."""
    leaked = {w.lower() for w in LATINWORD.findall(LEAK_STRIP.sub(' ', dst))
              if not w.isupper()} & PROSE
    if not leaked:
        return False
    source = {w.lower() for w in LATINWORD.findall(LEAK_STRIP.sub(' ', src))}
    return bool(leaked & source)


def _mixes_scripts(word):
    """True when one word draws letters from Latin and from Greek or Cyrillic.

    The import spliced words together mid-token, leaving forms such as Greek
    "WARNINGΟΠΟΙΗΣΗ" and Bulgarian "ДНКME" that read as words but are neither.
    """
    found = set()
    for ch in word:
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for script in ('LATIN', 'GREEK', 'CYRILLIC'):
            if name.startswith(script):
                found.add(script)
    return 'LATIN' in found and bool(found & {'GREEK', 'CYRILLIC'})


def _unlocalized(src, dst, locale):
    """True when a non-Latin catalogue renders prose without its own script.

    Requires two ordinary words in the source, so acronym-only labels and bare
    code samples do not fire. Note this catches what `is_untranslated` cannot:
    a transliteration differs from the msgid, so the echo test reads it as
    translated.
    """
    scripts = SCRIPT_OF.get(locale)
    if not scripts or not dst.strip():
        return False
    # Markup and tokens are copied through verbatim, so words inside them are
    # not prose the translator was ever asked to render.
    prose = TOKEN.sub(' ', TAG.sub(' ', src))
    words = [w for w in LATINWORD.findall(prose) if not SCRIPTLESS.match(w)]
    if len(words) < 2:
        return False
    for ch in dst:
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        if name.startswith(scripts):
            return False
    return True


def _escape_artifact(src, dst):
    """True when the translation carries a backslash the source does not.

    A quote inside a .po string is always written `\\"`, so a translation that
    went through one escaping round too many stores `\\\\"` and prints a literal
    backslash to the user. Found 16 such entries each in zh_CN and zh_TW.
    """
    return '\\"' in dst and '\\"' not in src


def _en_words(text):
    return [w.lower() for w in ENWORD.findall(text)]


def _is_polar(x, y):
    """True when two English words are the same word with its sense reversed."""
    if y in POLAR_MAP.get(x, ()):
        return True
    for base, marked in ((x, y), (y, x)):
        if len(base) >= 3 and base not in NOT_POLAR:
            if any(marked == prefix + base for prefix in POLAR_PREFIX):
                return True
    return False


def _polarity_variants(a, b):
    """How msgids `a` and `b` relate, when they are one text with opposite polarity.

    Returns 'swap' for a polarity word exchanged in place ("Set as default"
    against "Unset as default"), 'extended' when that swap also has the longer
    msgid carrying a whole sentence the shorter one does not, 'negation' for a
    negation word inserted ("Server Running" against "Server Not Running"), and
    None otherwise.

    The swap arm compares only the words the two msgids share at the front,
    which is what the 'extended' case needs: the sweep found "Zone signing
    requested successfully, but verification failed. Check DNSSEC keys." paired
    with "Zone unsigning requested successfully, but verification failed.".
    Three shared words are required there, so a bare "Enable" cannot pair with an
    unrelated "Disable ..." string.
    """
    wa, wb = _en_words(a), _en_words(b)
    n = min(len(wa), len(wb))
    if n >= 3 or (n and len(wa) == len(wb)):
        diff = [i for i in range(n) if wa[i] != wb[i]]
        if len(diff) == 1 and _is_polar(wa[diff[0]], wb[diff[0]]):
            if len(wa) == len(wb):
                return 'swap'
            if n >= 3:
                return 'extended'

    short, long_ = sorted((wa, wb), key=len)
    if 0 < len(long_) - len(short) <= 2:
        added = [w for w in long_ if w in EN_NEGATION and long_.count(w) > short.count(w)]
        if added and ([w for w in long_ if w not in EN_NEGATION]
                      == [w for w in short if w not in EN_NEGATION]):
            return 'negation'
    return None


def _shared_translation(x, y, relation):
    """Equal translations, or - only for 'extended' - the shorter standing as the
    whole start of the longer.

    The prefix form exists for the pair where one msgid carries an extra
    sentence: the shared opening is the part that collapsed. It is confined to
    that case because in a verb-final language the negation lands at the end of
    the sentence, which makes a correct positive translation a prefix of its
    correct negative counterpart - Persian renders "Server Running" as "سرور در
    حال اجرا" and "Server Not Running" as the same string plus "نیست". Comparing
    those as a prefix reported a healthy pair as collapsed.
    """
    x, y = x.strip(), y.strip()
    if x == y:
        return True
    if relation != 'extended':
        return False
    short, long_ = sorted((x, y), key=len)
    return len(short) >= 15 and long_.startswith(short)


def _antonym_collisions(heads):
    """msgid pairs that are opposites of each other yet share one translation."""
    by_translation = defaultdict(list)
    for src, dst in heads:
        # Bucketed on the opening so the whole file is not compared pairwise.
        # The cut matches the floor in `_shared_translation`, so a prefix pair
        # always lands in the same bucket as an exact one.
        by_translation[dst.strip()[:15]].append((src, dst))

    found = []
    for group in by_translation.values():
        if len(group) < 2:
            continue
        for (src_a, dst_a), (src_b, dst_b) in itertools.combinations(group, 2):
            relation = _polarity_variants(src_a, src_b)
            if relation and _shared_translation(dst_a, dst_b, relation):
                found.append((f'{src_a}  ||  {src_b}', dst_a))
    return found


def _stem(word):
    """Crude plural strip. The excluded endings are the ones that are not plurals
    at all: "this" must not become "thi", or the singular/plural pair
    "this record"/"these records" stops looking morphological and gets reported."""
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'is', 'us', 'as')):
        return word[:-1]
    return word


def _msgid_key(text):
    """Word tuple with the differences no translation has to carry removed:
    case, articles, punctuation and the plural s. Two msgids with the same key
    are the same string for this purpose and never count as a collapse."""
    return tuple(_stem(w.lower()) for w in ENWORD.findall(text)
                 if w.lower() not in ('a', 'an', 'the'))


def _same_word(x, y):
    """One word in two shapes: an inflection, or an irregular pair."""
    if y in MORPH_MAP.get(x, ()):
        return True
    short, long_ = sorted((x, y), key=len)
    return long_.startswith(short) and len(long_) - len(short) <= 3


def _load_json(name, default):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


DNT_LITERALS = {e['term'] for e in _load_json('dnt_glossary.json', {}).get('literal', [])}
# term -> locale -> accepted renderings. Only terms listed here are checked, so
# an empty file simply turns term_consistency off.
LOCALE_TERMS = _load_json('locale_terms.json', {})

ACCENT_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _deaccent(word):
    """The word with every combining mark stripped, casefolded."""
    stripped = ''.join(c for c in unicodedata.normalize('NFD', word)
                       if not unicodedata.combining(c))
    return stripped.casefold()


# German-style transliteration, where the mark becomes a letter rather than
# being dropped. Checked separately from accent stripping because "fuer" and
# "für" do not share a deaccented form.
TRANSLIT = (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss'),
            ('Ä', 'Ae'), ('Ö', 'Oe'), ('Ü', 'Ue'), ('å', 'aa'), ('Å', 'Aa'))


def _translit(word):
    for mark, plain in TRANSLIT:
        word = word.replace(mark, plain)
    return word.casefold()


def _diacritic_hits(heads, locale):
    """Words spelt without their marks, where the catalogue spells them with
    marks elsewhere. Covers dropped accents ("metadonnees") and German-style
    transliteration ("fuer").

    Frequency alone cannot do this. In fr_FR the damaged "metadonnees" occurs 11
    times against 13 accented, so it reads as an accepted variant, while the
    perfectly good French "Supprime" occurs once against 20 "supprimé" and reads
    as damage. Nor can a dictionary-free rule tell "utilise" from "utilisé",
    since both are real words.

    So evidence comes from company. Pass one finds entries carrying two or more
    bare words whose marked spelling overwhelmingly dominates the catalogue,
    which is a combination clean prose does not produce. Pass two takes every
    bare spelling those entries used and flags the rest of the catalogue for it.
    A word that only ever appears alone in otherwise clean text is never learned,
    which is what keeps "utilise" and "Supprime" out.

    Soft: loanwords are legitimately spelt both ways in some languages.
    """
    variants = defaultdict(Counter)
    for _, dst in heads:
        for word in ACCENT_WORD.findall(_placeholder_mask(dst)):
            variants[_deaccent(word)][word] += 1
            if _translit(word) != word.casefold():
                variants[_translit(word)][word] += 1

    def counts_for(word):
        seen = variants[_deaccent(word)] or variants[word.casefold()]
        bare = sum(n for w, n in seen.items()
                   if _deaccent(w) == w.casefold() and _translit(w) == w.casefold())
        return bare, sum(seen.values()) - bare

    def bare_words(src, dst):
        out = set()
        for word in ACCENT_WORD.findall(_placeholder_mask(dst)):
            if _deaccent(word) != word.casefold() or _translit(word) != word.casefold():
                continue
            if word in DNT_LITERALS:
                continue
            # A word the English source also uses is a loanword or a product
            # name, not a dropped mark.
            if any(_deaccent(w) == _deaccent(word) for w in ACCENT_WORD.findall(src)):
                continue
            # The marked spelling has to be at least as common, or ordinary
            # function words ("para", "tem") get learned off one damaged entry
            # and drag in most of the catalogue.
            bare, marked = counts_for(word)
            if not marked or marked < bare:
                continue
            out.add(word)
        return out

    def strong(word):
        """Marked spelling dominates enough that the bare one is hard to defend."""
        bare, marked = counts_for(word)
        return marked >= 5 and marked >= 5 * bare

    def unmarked(dst):
        """No marked character anywhere in the translation."""
        return all(_deaccent(w) == w.casefold() and _translit(w) == w.casefold()
                   for w in ACCENT_WORD.findall(dst))

    # A string an MT pass stripped carries no marks at all, which is what
    # separates it from ordinary prose in a densely accented language. Without
    # this, Portuguese and Vietnamese seed on clean sentences - they have too
    # many legitimate bare/marked word pairs - and the second pass then flags
    # most of the catalogue.
    per_entry = [(src, dst, bare_words(src, dst)) for src, dst in heads]
    seeds = [words for _, dst, words in per_entry
             if unmarked(dst) and sum(1 for w in words if strong(w)) >= 2]
    damaged = {w.casefold() for words in seeds for w in words}

    for src, dst, words in per_entry:
        if any(w.casefold() in damaged for w in words):
            yield src, dst


def _placeholder_mask(text):
    """Blank out placeholders, identifiers and paths so words inside them are
    not read as prose."""
    text = PRINTF.sub(' ', text)
    text = IDENTIFIER.sub(' ', text)
    text = TOKEN.sub(' ', text)
    return TAG.sub(' ', text)


def _term_hits(heads, locale):
    """Entries that render a source term with something other than the agreed
    wording for this locale.

    Config driven rather than inferred: with no word alignment there is no way
    to tell a synonym from a mistranslation mechanically, so the accepted
    renderings live in locale_terms.json and the check is only as wide as that
    file. Seeded from a translation review; extend it as terms get settled.

    Soft, because a msgid can carry the term inside a literal that should stay
    in English - a parenthetical list of table names, for instance - and no
    mechanical test separates that from a missed translation.
    """
    for term, per_locale in LOCALE_TERMS.items():
        if term.startswith('_'):
            continue
        accepted = per_locale.get(locale)
        if not accepted:
            continue
        for src, dst in heads:
            if term not in src.casefold():
                continue
            if not any(form in dst for form in accepted):
                yield src, dst


def _msgstr_collapses(heads, ratio):
    """Distinct msgids that came back sharing one translation.

    Two arms.

    Compression - a group of msgids whose shared translation is far shorter than
    any of them, so information was dropped rather than merely reworded. The
    floor is relative to the locale's own median translation/source length ratio,
    which is what keeps Chinese (median 0.37) from reporting its whole catalogue
    while Albanian (1.10) still reports its collapsed entries. Measured at 0.5,
    0.6 and 0.7 of that median: 0.5 misses real cases such as "Created at" and
    "Created by" both rendered "Создан", 0.7 fills up with legitimate plural and
    synonym pairs, so 0.6 is where the hits are worth reading.

    Substitution - two msgids identical but for one word, translated identically.
    This is what "Failed to bind to LDAP server!" against "Failed to connect to
    LDAP server!" looks like. Four words are required so that two one-word labels
    cannot pair up, which is where nearly all the noise was.

    Soft, and it cannot be otherwise: English near-synonyms that most languages
    render with a single word (delete/remove, search/lookup, manage/administer,
    critical/important) are indistinguishable from a real collapse by any
    mechanical test. delete/remove alone accounted for about a fifth of the raw
    hits and is excluded by name; the rest are left in and have to be read.
    """
    by_translation = defaultdict(list)
    for src, dst in heads:
        by_translation[dst.strip()].append(src)

    found = []
    for dst, ids in by_translation.items():
        if len(ids) < 2 or len({_msgid_key(i) for i in ids}) < 2:
            continue
        if all(len(dst) < ratio * len(i) for i in ids):
            found.append((' || '.join(sorted(ids)), dst))
            continue
        for a, b in itertools.combinations(sorted(ids), 2):
            wa, wb = _msgid_key(a), _msgid_key(b)
            if len(wa) != len(wb) or len(wa) < 4:
                continue
            diff = [i for i in range(len(wa)) if wa[i] != wb[i]]
            if len(diff) == 1:
                x, y = wa[diff[0]], wb[diff[0]]
                if not _same_word(x, y) and y not in SYNONYMS.get(x, ()):
                    found.append((f'{a}  ||  {b}', dst))
                    break
    return found


def _views(entry):
    """The (source, translation) pairs to check for one entry.

    poutil keeps plural translations in `plurals` and leaves `msgstr` empty, so
    filtering on `msgstr` skipped every plural entry - 12 per catalogue, never
    checked by any class. Each plural form is compared against `msgid_plural`
    rather than `msgid` because the two source forms differ only in the count
    word, which no class here keys on, and `msgid_plural` is the form most target
    plural forms correspond to.
    """
    if entry.msgid_plural:
        src = entry.msgid_plural
        return [(src, v) for v in entry.plurals.values()
                if v and v != src and v != entry.msgid]
    if entry.msgstr and entry.msgstr != entry.msgid:
        return [(entry.msgid, entry.msgstr)]
    return []


def check_entry(src, dst, locale):
    """Return the hit classes for one source/translation pair."""
    hits = []

    if _placeholders(src) != _placeholders(dst):
        hits.append('placeholder')
    if _has_leak(dst) and not _has_leak(src):
        hits.append('leak')
    if sorted(TAG.findall(src)) != sorted(TAG.findall(dst)):
        hits.append('tags')
    if sorted(TOKEN.findall(src)) != sorted(TOKEN.findall(dst)):
        hits.append('tokens')
    if any(tok not in dst for tok in set(IDENTIFIER.findall(src))):
        hits.append('identifiers')
    # Checked against pre-fix catalogues: this caught every one of the 362 dropped
    # trailing spaces those hold, including the 32 in el_GR. The one boundary
    # mismatch it does not report is a trailing space added where the msgid has
    # none, which is cosmetic rather than a broken concatenation, so it stays out.
    if src != src.rstrip() and dst.rstrip() == dst:
        hits.append('trailing')
    if BOILERPLATE.search(dst) and not BOILERPLATE.search(src):
        hits.append('boilerplate')
    if WIKICHROME.search(dst) and not WIKICHROME.search(src):
        hits.append('boilerplate')

    if any(_mixes_scripts(w) for w in WORD.findall(dst)) or _rescripted_acronym(src, dst):
        hits.append('mixedscript')
    if _near_miss(src, dst):
        hits.append('nearmiss')
    # A mask is a literal the reader has to type back, so anything short of an
    # exact copy is a defect. Both failure modes count: the mask rewritten with
    # the wrong number of groups or in target-language letters (Slovenian
    # "LLLLMMDDHHmmSS", Danish "xx- xx- xx-" with a space after each separator),
    # and the mask dropped while the sentence still promises a format.
    if any(m not in dst for m in _masks(src)):
        hits.append('literalmask')
    if _protocol_downgrade(src, dst):
        hits.append('protocoldowngrade')
    if _ip_literal(src, dst):
        hits.append('ipliteral')
    if _fragment_punctuation(src, dst):
        hits.append('fragment_punctuation')
    if _escape_artifact(src, dst):
        hits.append('escape_artifact')
    if _unlocalized(src, dst, locale):
        hits.append('unlocalized')

    words = dst.split()
    if len(words) >= 6:
        token, count = Counter(words).most_common(1)[0]
        if len(token) <= 2 and count >= 6 and count >= len(words) * 0.4:
            hits.append('repetition')

    # Soft: mostly dropped clauses that happened to carry the number, which is a
    # prompt to read the entry rather than proof the figure itself was altered.
    if _numbers_lost(src, dst):
        hits.append('numerals')
    if locale not in CJK and len(re.findall(r'\S+', src)) >= 8 and len(dst) < len(src) * 0.5:
        hits.append('truncation')
    # Soft: matched as a plain substring on the target so a glued form such as
    # Japanese "NullMXレコード" still counts as present.
    if any(t not in dst for t in RRTYPE
           if re.search(rf'(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])', src)):
        hits.append('rrtype')
    # Soft: a handful of the words listed are terms some locales keep in English
    # on purpose, "Dashboard" and "Multi-Factor Authentication" most often, so a
    # hit means read the entry rather than assume damage.
    if locale in NONLATIN and _english_leak(src, dst):
        hits.append('englishleak')
    if _negation_loss(src, dst, locale):
        hits.append('negation_loss')

    return hits


def _plural_forms_faults(locale, entries):
    """Header rule disagreeing with plural_forms.json, or a wrong form count.

    A catalogue whose header says two forms cannot hold the third form its
    language needs, and gettext picks by index - so a miscounted entry silently
    renders the wrong string rather than failing.
    """
    faults = []
    declared = poutil.header_plural_rule(entries)
    if declared is None:
        return [('Plural-Forms', 'header declares no Plural-Forms rule')]
    try:
        expected = poutil.plural_rule(locale.split('_')[0].lower())
    except KeyError as exc:
        return [('Plural-Forms', str(exc))]
    if not poutil.same_plural_rule(declared, expected):
        faults.append(('Plural-Forms', f'{declared} does not match {expected}'))
    count = poutil.plural_spec(declared)[0]
    for entry in entries:
        if entry.obsolete or entry.is_header or not entry.msgid_plural:
            continue
        if sorted(entry.plurals) != list(range(count)):
            faults.append((entry.msgid,
                           f'has forms {sorted(entry.plurals)}, header declares {count}'))
    return faults


def check_locale(locale, examples=0):
    entries = poutil.parse(poutil.po_path(locale))
    pairs = []
    for entry in entries:
        if not entry.msgid or entry.obsolete or entry.is_header:
            continue
        views = _views(entry)
        if views:
            pairs.append(views)

    counts = Counter()
    samples = defaultdict(list)
    for views in pairs:
        # One entry counts once per class however many plural forms trip it,
        # so the numbers stay comparable with the pre-plural runs.
        hits = set()
        for src, dst in views:
            hits.update(check_entry(src, dst, locale))
        for cls in hits:
            counts[cls] += 1
            if len(samples[cls]) < examples:
                samples[cls].append(views[0])

    heads = [v[0] for v in pairs]
    for src, dst in _antonym_collisions(heads):
        counts['antonym_collision'] += 1
        if len(samples['antonym_collision']) < examples:
            samples['antonym_collision'].append((src, dst))

    lengths = [len(d) / len(s) for s, d in heads if len(s) >= 8]
    median = statistics.median(lengths) if lengths else 1.0
    for src, dst in _msgstr_collapses(heads, 0.6 * median):
        counts['msgstr_collapse'] += 1
        if len(samples['msgstr_collapse']) < examples:
            samples['msgstr_collapse'].append((src, dst))

    # Both need the whole catalogue: one keys on how this locale spells a word
    # elsewhere, the other on an agreed rendering shared across entries.
    for cls, hits in (('diacritic', _diacritic_hits(heads, locale)),
                      ('term_consistency', _term_hits(heads, locale))):
        for src, dst in hits:
            counts[cls] += 1
            if len(samples[cls]) < examples:
                samples[cls].append((src, dst))

    # Cross-wire needs the whole file: a translation carrying none of its own
    # source's tokens but matching a nearby source's is evidence of a swap.
    sigs_src = [_signature(s) for s, _ in heads]
    sigs_dst = [_signature(d) for _, d in heads]
    for i, (src_text, dst_text) in enumerate(heads):
        dst, src = sigs_dst[i], sigs_src[i]
        if len(dst) < 2 or len(src) < 2 or (dst & src):
            continue
        window = range(max(0, i - 80), min(len(heads), i + 81))
        best = max((len(dst & sigs_src[j]) for j in window if j != i), default=0)
        if best >= 2 and best >= len(dst) * 0.5:
            counts['crosswire'] += 1
            if len(samples['crosswire']) < examples:
                samples['crosswire'].append((src_text, dst_text))

    for where, detail in _plural_forms_faults(locale, entries):
        counts['plural_forms'] += 1
        if len(samples['plural_forms']) < examples:
            samples['plural_forms'].append((where, detail))

    return len(pairs), counts, samples


def main():
    args = sys.argv[1:]
    only = next((a.split('=', 1)[1] for a in args if a.startswith('--locale=')), None)
    wanted = next((a.split('=', 1)[1].split(',') for a in args if a.startswith('--class=')), None)
    examples = int(next((a.split('=', 1)[1] for a in args if a.startswith('--examples=')), 0))
    quiet = '--quiet' in args

    locales = [only] if only else [l for l in sorted(poutil.locales()) if l != 'en_EN']
    classes = wanted or list(HARD + SOFT)

    totals = Counter()
    rows = []
    for locale in locales:
        if not os.path.isfile(poutil.po_path(locale)):
            print(f'Error: no catalogue for {locale}', file=sys.stderr)
            return 2
        n, counts, samples = check_locale(locale, examples)
        counts = Counter({k: v for k, v in counts.items() if k in classes})
        totals.update(counts)
        if counts:
            rows.append((locale, n, counts, samples))

    width = max((len(c) for c in classes), default=10)
    if not quiet:
        for locale, n, counts, samples in rows:
            print(f'{locale}  ({n} translated)')
            for cls, hits in counts.most_common():
                mark = '' if cls in HARD else '  (soft)'
                print(f'    {cls:<{width}} {hits:>5}{mark}')
                for src, dst in samples.get(cls, []):
                    print(f'        id : {src[:88]}')
                    print(f'        str: {dst[:88]}')
        print()

    print('total')
    for cls in classes:
        if totals[cls]:
            print(f'    {cls:<{width}} {totals[cls]:>5}' + ('' if cls in HARD else '  (soft)'))
    if not totals:
        print('    clean')

    return 1 if any(totals[c] for c in HARD if c in classes) else 0


if __name__ == '__main__':
    sys.exit(main())
