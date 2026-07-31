#!/usr/bin/env python3
"""Build scripts/dnt_glossary.json from derived sources plus hand-curated evidence.

Derived:
  - record type names   <- lib/Domain/Model/RecordType.php constants
  - config identifiers  <- config/settings.defaults.php flattened keys
Everything else is hand-curated from the per-entry review sweep.

Every literal is validated against the msgid corpus (en_EN catalogue + POT);
terms present in no msgid are dropped and reported.
"""
import json
import os
import re
import subprocess
import sys

ROOT = '/Users/edmondas/Projects/poweradmin'
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import poutil  # noqa: E402

OUT = os.path.join(ROOT, 'scripts', 'dnt_glossary.json')

# Token boundary: '/', '\', '.' and '-' are part of a literal, not separators.
# A leading '.' is allowed so `in-addr.arpa` is still seen inside
# `192.in-addr.arpa`, and a trailing '.' so `example.com` is seen in
# `example.com.`.
BOUND_L = r'(?<![A-Za-z0-9_\\/-])'
BOUND_R = r'(?![A-Za-z0-9_\\/-])'


def matcher(term):
    flags = 0 if any(c.isupper() for c in term) else re.IGNORECASE
    return re.compile(BOUND_L + re.escape(term) + BOUND_R, flags)


# ---------------------------------------------------------------- msgid corpus
def corpus():
    ids = set()
    for p in ('locale/en_EN/LC_MESSAGES/messages.po', 'locale/i18n-template-php.pot'):
        for e in poutil.parse(os.path.join(ROOT, p)):
            if e.obsolete or e.is_header:
                continue
            ids.add(e.msgid)
            if e.msgid_plural:
                ids.add(e.msgid_plural)
    return sorted(ids)


# ------------------------------------------------------------- derived sources
def record_types():
    src = open(os.path.join(ROOT, 'lib/Domain/Model/RecordType.php')).read()
    return sorted(set(re.findall(r"^\s*public const ([A-Z][A-Z0-9]*) = '\1';",
                                 src, re.M)))


def config_keys():
    php = r'''
$c = require "config/settings.defaults.php";
$out = [];
$walk = function ($arr, $prefix) use (&$walk, &$out) {
    foreach ($arr as $k => $v) {
        if (!is_string($k)) { continue; }
        $path = $prefix === "" ? $k : "$prefix.$k";
        $out[] = $path;
        if (is_array($v)) { $walk($v, $path); }
    }
};
$walk($c, "");
echo implode("\n", $out);
'''
    r = subprocess.run(['php', '-r', php], cwd=ROOT, capture_output=True, text=True)
    r.check_returncode()
    # Bare single-word keys ("host", "name", "type", "port") are ordinary English
    # words; only dotted paths and snake_case names are unambiguous literals.
    # Messages often name the leaf key alone ("zone_ownership_mode"), so emit
    # both the full path and any snake_case leaf.
    keys = set()
    for k in r.stdout.split('\n'):
        if not k:
            continue
        if '.' in k or '_' in k:
            keys.add(k)
        leaf = k.rsplit('.', 1)[-1]
        if '_' in leaf:
            keys.add(leaf)
    return sorted(keys)


# ------------------------------------------------------- hand-curated literals
HAND = [
    # group, term, note
    ('example-names', 'example.com', 'RFC 2606 reserved example domain; MT produced "παράδειγμα.com"'),
    ('example-names', 'www.example.com', ''),
    ('example-names', 'mail.example.com', ''),
    ('example-names', 'hostmaster.example.net', ''),
    ('example-names', 'example.net', ''),
    ('example-names', 'domain.tld', 'placeholder domain in format examples'),
    ('example-names', 'a.b.c.d', 'placeholder IPv4 shape'),
    ('example-names', 'outlook.com', ''),
    ('example-names', 'mail.protection.outlook.com', 'Microsoft 365 MX host'),
    ('example-names', 'spf.protection.outlook.com', ''),
    ('example-names', 'google.com', ''),
    ('example-names', 'isc.org', ''),
    ('example-names', 'dlv.isc.org', 'decommissioned DLV registry, a real name'),
    ('example-names', 'localhost', 'MT produced "τοπικό host"'),
    ('example-names', '2001:db8', 'RFC 3849 documentation prefix'),
    ('example-names', '00-00-5E', 'IANA OUI example'),
    ('example-names', 'bc1q', 'WALLET example address prefix'),

    ('dns-suffix', 'in-addr.arpa', ''),
    ('dns-suffix', 'ip6.arpa', ''),
    ('dns-suffix', 'e164.arpa', ''),
    ('dns-suffix', '_smimecert', 'SMIMEA owner-name label'),
    ('dns-suffix', '_dmarc', 'DMARC owner-name label'),

    ('path', 'install/', 'MT produced "εγκατάσταση/", pointing at a directory that does not exist'),
    ('path', 'config/settings.php', ''),
    ('path', 'templates/emails/custom/', ''),
    ('path', 'settings.php', ''),
    ('path', 'index.php', ''),
    ('path', 'nginx.conf', ''),
    ('path', 'nginx.conf.example', 'MT produced "nginx.conf.παράδειγμα"'),
    ('path', 'pdns.conf', ''),
    ('path', 'cert.pem', ''),

    ('config', 'max_input_vars', 'PHP ini setting, not in settings.defaults.php'),
    ('config', 'setSOAParams()', 'function name'),
    ('config', 'contactemail', 'SVCB/HTTPS and ACME parameter name'),
    ('config', 'contactphone', ''),
    ('config', 'accounturi', ''),
    ('config', 'soaminimum', 'CSYNC flag name'),
    ('config', 'record_type_defaults', 'Poweradmin table name'),
    ('config', 'groups_only', 'zone_ownership_mode value'),
    ('config', 'users_only', 'zone_ownership_mode value'),

    ('field-list', 'primary-ns hostmaster serial refresh retry expire minimum',
     'SOA field order shown as a literal format string'),
    ('field-list', 'name,type,content,priority,ttl,comment', 'bulk-import column order'),
    ('field-list', 'name,type,content', ''),
    ('field-list', 'name,SRV,"weight port target",priority,ttl', ''),
    ('field-list', 'name,SRV,target,weight,port,ttl', ''),
    ('field-name', 'algorithm-name', 'TSIG/TKEY wire field'),
    ('field-name', 'inception-time', ''),
    ('field-name', 'expiration-time', ''),
    ('field-name', 'key-data', ''),
    ('field-name', 'key-tag', ''),
    ('field-name', 'digest-type', ''),
    ('field-name', 'hash-algorithm', ''),
    ('field-name', 'matching-type', ''),
    ('field-name', 'certificate-data', ''),
    ('field-name', 'original-id', ''),
    ('field-name', 'other-len', ''),
    ('field-name', 'fudge', 'TSIG field name, not an English word here'),

    ('protocol-value', 'issuewild', 'CAA tag'),
    ('protocol-value', 'iodef', 'CAA tag'),
    ('protocol-value', 'v=spf1', ''),
    ('protocol-value', 'v=DMARC1', ''),
    ('protocol-value', 'DMARC1', ''),
    ('protocol-value', 'p=none', 'DMARC policy tag shown verbatim'),
    ('protocol-value', 't=y', 'DKIM testing-mode tag'),
    ('protocol-value', 'afrf', 'DMARC report format'),
    ('protocol-value', 'adkim', ''),
    ('protocol-value', 'aspf', ''),
    ('protocol-value', 'rua', ''),
    ('protocol-value', 'ruf', ''),
    ('protocol-value', 'include/a/mx', 'SPF mechanism list shown as a literal'),
    ('protocol-value', 'no-default-alpn', 'SVCB/HTTPS parameter'),
    ('protocol-value', 'NATIVE', 'PowerDNS zone kind'),
    ('protocol-value', 'DANE-EE', ''),
    ('protocol-value', 'PKIX-EE', ''),
    ('protocol-value', 'E2U', 'ENUM service field'),
    ('protocol-value', 'SIG(0)', ''),
    ('protocol-value', '$ORIGIN', 'BIND zone-file directive'),
    ('protocol-value', '$TTL', 'BIND zone-file directive'),

    ('command', 'ssh-keygen -r hostname', ''),
    ('command', 'VerifyHostKeyDNS yes', 'ssh_config directive and value'),
    ('command', '--print-dane-records', 'GnuPG flag'),
    ('command', 'openssl', ''),
    ('command', 'x509', ''),
    ('command', '-pubkey', ''),
    ('command', '-noout', ''),
    ('command', '-pubin', ''),
    ('command', '-outform', ''),
    ('command', '-sha256', ''),

    ('encoding', 'base64', 'MT produced "βάσης64", "βάση 64", "bazë 64"'),
    ('encoding', 'Base32hex', ''),
    ('encoding', 'Punycode', ''),
    ('encoding', 'PEM', ''),
    ('encoding', 'DER', ''),
    ('encoding', 'ASCII', ''),
    ('encoding', 'NUL', 'the ASCII control character name'),

    ('filter-syntax', 'type:txt', ''),
    ('filter-syntax', 'content:spf', ''),
    ('filter-syntax', 'zone..variant', 'view/variant naming syntax'),
    ('filter-syntax', 'key=value', ''),

    ('format-token', 'xx-xx-xx-xx-xx-xx', 'EUI48 shape'),
    ('format-token', 'xx-xx-xx-xx-xx-xx-xx-xx', 'EUI64 shape'),
    ('format-token', 'YYYYMMDDHHmmSS', 'RRSIG timestamp shape'),
    ('format-token', 'xxxx:xxxx:xxxx:xxxx', 'NID shape'),
    ('format-token', '%serial%', 'template substitution token, not a printf placeholder'),
    ('format-token', '%account%', ''),
    ('format-token', '%date%', ''),

    ('product', 'PowerDNS', 'MT produced "energji"/"Ισχύς DNS"'),
    ('product', 'Poweradmin', ''),
    ('product', 'MySQL', ''),
    ('product', 'MariaDB', ''),
    ('product', 'PostgreSQL', ''),
    ('product', 'SQLite', ''),
    ('product', 'BIND', ''),
    ('product', 'GnuPG', ''),
    ('product', 'OpenSSH', ''),
    ('product', 'Postfix', ''),
    ('product', 'Exim', ''),
    ('product', 'PHP', ''),
    ('product', 'PDNS', ''),

    ('acronym', 'DNS', ''),
    ('acronym', 'DNSSEC', ''),
    ('acronym', 'RFC', ''),
    ('acronym', 'API', ''),
    ('acronym', 'TTL', ''),
    ('acronym', 'MFA', ''),
    ('acronym', 'OIDC', ''),
    ('acronym', 'SAML', ''),
    ('acronym', 'LDAP', ''),
    ('acronym', 'LDAPS', ''),
    ('acronym', 'WHOIS', ''),
    ('acronym', 'RDAP', ''),
    ('acronym', 'DMARC', ''),
    ('acronym', 'DKIM', ''),
    ('acronym', 'FQDN', ''),
    ('acronym', 'CIDR', ''),
    ('acronym', 'AXFR', ''),
    ('acronym', 'NOTIFY', 'DNS opcode'),
    ('acronym', 'RCODE', ''),
    ('acronym', 'KSK', ''),
    ('acronym', 'ZSK', ''),
    ('acronym', 'SEP', 'DNSKEY flag name'),
    ('acronym', 'DANE', ''),
    ('acronym', 'PKIX', ''),
    ('acronym', 'SPKI', ''),
    ('acronym', 'PKI', ''),
    ('acronym', 'PGP', ''),
    ('acronym', 'IPKIX', 'CERT type mnemonic'),
    ('acronym', 'ISPKI', ''),
    ('acronym', 'IPGP', ''),
    ('acronym', 'IACPKIX', ''),
    ('acronym', 'ILNP', ''),
    ('acronym', 'ENUM', 'E.164 number mapping, not the word "enum"'),
    ('acronym', 'IANA', ''),
    ('acronym', 'IETF', ''),
    ('acronym', 'OUI', ''),
    ('acronym', 'AFI', ''),
    ('acronym', 'AFS', ''),
    ('acronym', 'DCE', ''),
    ('acronym', 'IDN', ''),
    ('acronym', 'MIME', ''),
    ('acronym', 'SMTP', ''),
    ('acronym', 'TCP', ''),
    ('acronym', 'UDP', ''),
    ('acronym', 'HTTP', ''),
    ('acronym', 'HTTPS', ''),
    ('acronym', 'FTP', ''),
    ('acronym', 'SFTP', ''),
    ('acronym', 'SSH', ''),
    ('acronym', 'TLS', ''),
    ('acronym', 'SSL', ''),
    ('acronym', 'DTLS', ''),
    ('acronym', 'ALPN', ''),
    ('acronym', 'CSRF', ''),
    ('acronym', 'CSV', ''),
    ('acronym', 'JSON', ''),
    ('acronym', 'SQL', ''),
    ('acronym', 'REST', ''),
    ('acronym', 'UNIX', ''),
    ('acronym', 'GET', 'HTTP method'),
    ('acronym', 'POST', 'HTTP method'),
    ('acronym', 'QR', ''),
    ('acronym', 'RMAILBX', 'MINFO field'),
    ('acronym', 'EMAILBX', 'MINFO field'),
    ('acronym', 'RNAME', 'SOA field'),
    ('acronym', 'BADSIG', 'TSIG error name'),
    ('acronym', 'BADKEY', ''),
    ('acronym', 'BADTIME', ''),
    ('acronym', 'BADTRUNC', ''),

    ('algorithm', 'RSA', ''),
    ('algorithm', 'DSA', ''),
    ('algorithm', 'ECDSA', ''),
    ('algorithm', 'Ed25519', ''),
    ('algorithm', 'ED25519', ''),
    ('algorithm', 'ED448', ''),
    ('algorithm', 'RSASHA1', ''),
    ('algorithm', 'RSASHA256', ''),
    ('algorithm', 'RSASHA512', ''),
    ('algorithm', 'MD5', ''),
    ('algorithm', 'SHA1', ''),
    ('algorithm', 'SHA256', ''),
    ('algorithm', 'SHA-256', ''),
    ('algorithm', 'SHA-1', ''),
    ('algorithm', 'DH', 'Diffie-Hellman mnemonic in DNSKEY algorithm lists'),
    # Compounds: a slash is part of a literal, so "SSL" is not seen inside
    # "SSL/TLS" and the joined form has to be listed in its own right.
    ('algorithm', 'RSA/MD5', ''),
    ('algorithm', 'DSA/SHA1', ''),
    ('algorithm', 'RSA/SHA-1', ''),
    ('algorithm', 'RSA/SHA-256', ''),
    ('algorithm', 'RSASHA1-NSEC3-SHA1', ''),
    ('acronym', 'SSL/TLS', ''),
    ('acronym', 'S/MIME', ''),
    ('acronym', 'TCP/UDP', ''),
    ('acronym', 'HTTP/HTTPS', ''),
    ('acronym', 'CSV/JSON', ''),
    ('acronym', 'DNS-over-TLS', ''),

    ('pdns-term', 'supermaster', 'PowerDNS feature name, lowercase in the UI'),
    ('pdns-term', 'autoprimary', 'PowerDNS feature name, lowercase in the UI'),
]

# Record types that are also ordinary English words or English articles; the
# msgid side cannot tell the two apart, so they stay advisory.
RECORD_TYPE_ADVISORY = {
    'A': 'also the English article "a"; msgid "A record" and "A zone must..." are indistinguishable',
    'KEY': 'the KEY record type, but msgids also use "KEY" as caps emphasis of the ordinary word ("Only the PUBLIC KEY goes in this DNS record")',
}

ADVISORY = [
    ('spf-mechanism', 'all', 'SPF mechanism, and the commonest English word in the catalogue'),
    ('spf-mechanism', 'include', 'SPF mechanism and an ordinary verb'),
    ('spf-mechanism', 'a', 'SPF mechanism and the English article'),
    ('spf-mechanism', 'mx', 'SPF mechanism; the uppercase MX record type is enforced instead'),
    ('spf-mechanism', 'redirect', 'SPF modifier and an ordinary verb'),
    ('spf-mechanism', 'exp', 'SPF modifier; too short to match safely'),
    ('spf-mechanism', 'ip4', 'SPF mechanism; also written as prose'),
    ('spf-mechanism', 'ip6', 'SPF mechanism; also written as prose'),
    ('spf-mechanism', 'exists', 'SPF mechanism and an ordinary verb'),
    ('spf-mechanism', 'ptr', 'SPF mechanism; the uppercase PTR record type is enforced instead'),

    ('caa-tag', 'issue', 'CAA tag and an ordinary noun/verb'),

    ('dmarc-value', 'none', 'DMARC policy value and an ordinary word; the literal "p=none" is enforced instead'),
    ('dmarc-value', 'quarantine', 'DMARC policy value and an ordinary word'),
    ('dmarc-value', 'reject', 'DMARC policy value and an ordinary verb'),
    ('dmarc-value', 'pct', 'DMARC tag; appears in prose about percentages'),
    ('dmarc-value', 'sp', 'DMARC tag; too short to match safely'),
    ('dmarc-value', 'fo', 'DMARC tag; too short to match safely'),
    ('dmarc-value', 'rf', 'DMARC tag; too short to match safely'),
    ('dmarc-value', 'ri', 'DMARC tag; too short to match safely'),

    ('dnssec-value', 'secure', 'DNSSEC validation state and an ordinary adjective, including inside "insecure"'),
    ('dnssec-value', 'insecure', 'DNSSEC validation state and an ordinary adjective'),
    ('dnssec-value', 'bogus', 'DNSSEC validation state and an ordinary adjective'),

    ('lua-keyword', 'function', 'Lua keyword inside LUA record docs and an ordinary noun'),
    ('lua-keyword', 'return', 'Lua keyword and an ordinary verb'),
    ('lua-keyword', 'end', 'Lua keyword and an ordinary noun/verb'),

    ('csync-flag', 'immediate', 'CSYNC flag name quoted in the message, and an ordinary adjective'),

    ('field-name', 'mac', 'TSIG field name, but MAC also means the hardware address in EUI48 messages'),
    ('field-name', 'timestamp', 'TSIG field name and an ordinary noun'),
    ('field-name', 'serial', 'SOA field name and an ordinary noun'),
    ('field-name', 'scheme', 'ZONEMD field name and an ordinary noun'),
    ('field-name', 'error', 'TSIG/TKEY field name and an ordinary noun'),
    ('field-name', 'mode', 'TKEY field name and an ordinary noun'),
    ('field-name', 'digest', 'DS/ZONEMD field name and an ordinary noun'),

    ('acronym', 'ID', 'widely localized ("Kimlik", "Ausweis"); keep Latin where the surrounding locale does'),
    ('acronym', 'IP', 'usually kept, but legitimately expanded in some scripts'),
    ('acronym', 'URL', 'usually kept, but legitimately expanded in some scripts'),
    ('acronym', 'CA', 'certificate authority; some locales expand it'),
    ('acronym', 'OS', 'HINFO field name and an ordinary two-letter string'),
    ('acronym', 'CPU', 'HINFO field name; some locales translate it'),
    ('acronym', 'MAC', 'hardware address, and the TSIG field of the same name'),
    ('acronym', 'DB', 'shorthand for database in settings labels'),
    ('acronym', 'UI', 'often translated as part of a longer phrase'),
    ('acronym', 'RR', 'resource record; some locales expand it'),
    ('acronym', 'TLD', 'appears both as the bracket token [TLD] and as prose'),
    ('acronym', 'BEGIN', 'PEM marker, but written as an ordinary word in "BEGIN/END markers"'),
    ('acronym', 'END', 'PEM marker, but written as an ordinary word in "BEGIN/END markers"'),

    ('emphasis', 'MUST', 'RFC 2119 emphasis; translating it in caps is correct'),
    ('emphasis', 'NOT', 'RFC 2119 emphasis; translating it in caps is correct'),
    ('emphasis', 'SHOULD', 'RFC 2119 emphasis'),
    ('emphasis', 'RECOMMENDED', 'RFC 2119 emphasis'),
    ('emphasis', 'REQUIRE', 'caps emphasis'),
    ('emphasis', 'CRITICAL', 'caps prefix; translate but keep the caps'),
    ('emphasis', 'IMPORTANT', 'caps prefix; translate but keep the caps'),
    ('emphasis', 'WARNING', 'caps prefix; translate but keep the caps'),
    ('emphasis', 'NOTE', 'caps prefix; translate but keep the caps'),
    ('emphasis', 'PUBLIC', 'caps emphasis in the DKIM key messages'),
    ('emphasis', 'PRIVATE', 'caps emphasis in the DKIM key messages'),

    ('role', 'primary', 'PowerDNS role name and an ordinary adjective'),
    ('role', 'secondary', 'PowerDNS role name and an ordinary adjective'),
    ('role', 'master', 'PowerDNS role name and an ordinary noun'),
    ('role', 'slave', 'PowerDNS role name and an ordinary noun'),
    ('role', 'native', 'lowercase prose form; the uppercase zone kind NATIVE is enforced'),
]


def main():
    ids = corpus()
    dropped = []

    entries, seen = [], set()

    def add(group, term, note, source):
        if term in seen:
            return
        seen.add(term)
        m = matcher(term)
        if not any(m.search(i) for i in ids):
            dropped.append((group, term))
            return
        e = {'term': term, 'group': group, 'source': source}
        if note:
            e['note'] = note
        entries.append(e)

    for t in record_types():
        if t in RECORD_TYPE_ADVISORY:
            continue
        add('record-type', t, '', 'lib/Domain/Model/RecordType.php')
    for k in config_keys():
        add('config', k, '', 'config/settings.defaults.php')
    for group, term, note in HAND:
        add(group, term, note, 'review-sweep')

    adv, adv_seen = [], set()

    def add_adv(group, term, note, source):
        if term in adv_seen:
            return
        adv_seen.add(term)
        adv.append({'term': term, 'group': group, 'note': note, 'source': source})

    for t, note in sorted(RECORD_TYPE_ADVISORY.items()):
        add_adv('record-type', t, note, 'lib/Domain/Model/RecordType.php')
    for group, term, note in ADVISORY:
        add_adv(group, term, note, 'review-sweep')

    entries.sort(key=lambda e: (e['group'], e['term'].lower()))
    adv.sort(key=lambda e: (e['group'], e['term'].lower()))

    doc = {
        '_meta': {
            'purpose': 'Do-not-translate glossary for the Poweradmin gettext catalogues.',
            'literal': ('Tokens that must appear byte-identical in the msgstr whenever they '
                        'appear in the msgid. Safe to enforce mechanically.'),
            'advisory': ('Terms that are usually but not always do-not-translate, or that are '
                         'ordinary English words in some contexts. Reviewer guidance only, '
                         'never machine-enforced.'),
            'matching': {
                'boundary_left': BOUND_L,
                'boundary_right': BOUND_R,
                'rule': ("'/', '\\', '.' and '-' are part of a literal, not word boundaries, so a "
                         "\\b-anchored rule cannot rewrite half of templates/emails/custom/. A "
                         "leading '.' is allowed so in-addr.arpa is still found inside "
                         "192.in-addr.arpa, and a trailing '.' so example.com is found in "
                         "'example.com.'."),
                'case': ('A term containing an uppercase letter is matched case-sensitively on the '
                         'msgid side, so the KEY record type does not fire on the ordinary word '
                         '"key". All-lowercase terms are matched case-insensitively. Presence in '
                         'the translation is always checked case-insensitively, because a casing '
                         'change is not the defect class this catches.'),
            },
            'regenerate': ('python3 scripts/build_dnt_glossary.py. '
                           'Record types come from the public const list in '
                           'lib/Domain/Model/RecordType.php; config identifiers from the '
                           'flattened keys of config/settings.defaults.php (bare single-word keys '
                           'such as host/name/type/port are excluded as ordinary English words). '
                           'Every literal is validated to appear in at least one msgid in '
                           'locale/en_EN/LC_MESSAGES/messages.po or locale/i18n-template-php.pot.'),
        },
        'literal': entries,
        'advisory': adv,
    }
    with open(OUT, 'w') as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write('\n')

    print(f'literal={len(entries)} advisory={len(adv)}')
    cfg = sum(1 for g, _ in dropped if g == 'config')
    print(f'dropped {len(dropped)} absent from every msgid '
          f'({cfg} unreferenced config keys, listed with -v):')
    for g, t in dropped:
        if g != 'config' or '-v' in sys.argv:
            print(f'  {g:16s} {t}')


if __name__ == '__main__':
    main()
