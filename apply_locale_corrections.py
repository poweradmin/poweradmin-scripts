#!/usr/bin/env python3
"""Apply LLM-curated regex corrections to msgstr lines of a .po file.

Usage: python3 apply_locale_corrections.py <locale>
Example: python3 apply_locale_corrections.py da_DK

Corrections fix systematic Argos MT mistakes (wrong word sense, broken spacing,
inconsistent DNS terminology). The dicts here are hand-curated based on review
of actual MT output - each entry has a reason.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

ROOT = poutil.ROOT


def _subs_da():
    """Danish: fix Argos's recurring word-sense and spacing issues."""
    return [
        # "wizard" -> Argos picks the magic sense; software guide is "guide"/"guider"
        (r"\btroldmænd\b", "guider"),
        (r"\bTroldmænd\b", "Guider"),
        (r"\btroldmand\b", "guide"),
        (r"\bTroldmand\b", "Guide"),
        # "config file" - Argos prefers "indstillingsfil" but Danish docs use "konfigurationsfil"
        (r"\bindstillingsfil\b", "konfigurationsfil"),
        (r"\bIndstillingsfil\b", "Konfigurationsfil"),
        (r"\bindstillingsfilen\b", "konfigurationsfilen"),
        (r"\bIndstillingsfilen\b", "Konfigurationsfilen"),
        # Remove stray space after hyphen in compound words (Argos bug)
        (r"\bzone- ", "zone-"),
        (r"\bZone- ", "Zone-"),
        # "record" noun - the file settled on the English word, 334 entries to 47,
        # so these Argos artifacts go straight there rather than through "post".
        (r"\bOpgørelsen blev\b", "Recorden blev"),
        (r"\bOpgørelser\b", "Records"),
        (r"\bopgørelser\b", "records"),
        # "Optag" in record context (means recording button)
        (r"\bOptag oprettet\b", "Record oprettet"),
        (r"\bOptag opdateret\b", "Record opdateret"),
        (r"\bOptag slettet\b", "Record slettet"),
        # The remaining "post" spellings, only where the source really is about a
        # record. Danish "post" is also mail, and postkasse/Postfix/postsystemer
        # must survive - whole-word anchoring is what keeps them out of reach.
        ((r"\brecords?\b", None), r"\bposter\b", "records"),
        ((r"\brecords?\b", None), r"\bPoster\b", "Records"),
        ((r"\brecords?\b", None), r"\bposten\b", "recorden"),
        ((r"\brecords?\b", None), r"\bPosten\b", "Recorden"),
        ((r"\brecords?\b", None), r"\bposttyper\b", "recordtyper"),
        ((r"\brecords?\b", None), r"\bposttype\b", "recordtype"),
        ((r"\brecords?\b", None), r"\bpostnavnet\b", "recordnavnet"),
        ((r"\brecords?\b", None), r"\bPostnavnet\b", "Recordnavnet"),
        ((r"\brecords?\b", None), r"\bpostnavn\b", "recordnavn"),
        ((r"\brecords?\b", None), r"\bpost\b", "record"),
        ((r"\brecords?\b", None), r"\bPost\b", "Record"),
        # "skuespiller" (actor as in performer) -> "udfører" (the one performing the action)
        (r"\bskuespilleren\b", "udføreren"),
        (r"\bSkuespilleren\b", "Udføreren"),
        # "returopgørelse" -> "returerklæring" (return statement in code)
        (r"\breturopgørelse\b", "return-erklæring"),
        # "Standard session krypteringsnøgle bruges" - grammar issue
        (r"Standard session krypteringsnøgle bruges, skal du", "Standard sessionkrypteringsnøgle anvendes - du skal"),
        # "save" verb - if Argos used "spare" anywhere
        (r"\bSpare\b", "Gem"),
        (r"\bspare\b", "gem"),
    ]


def _subs_el():
    """Greek: DNS terminology + UI wizard sense fixes."""
    return [
        # "wizard" -> Argos picks "μάγος" (magician); software guide is "οδηγός"
        (r"\bμάγοι\b", "οδηγοί"),
        (r"\bΜάγοι\b", "Οδηγοί"),
        (r"\bμάγος\b", "οδηγός"),
        (r"\bΜάγος\b", "Οδηγός"),
        (r"\bμάγου\b", "οδηγού"),
        (r"\bΜάγου\b", "Οδηγού"),
        (r"\bμάγοι DNS\b", "οδηγοί DNS"),
        (r"\bΜάγοι DNS\b", "Οδηγοί DNS"),
        (r"\bDNS μάγοι\b", "DNS οδηγοί"),
        (r"\bΟι μάγοι DNS\b", "Οι οδηγοί DNS"),
        # "record" noun in DNS context -> "εγγραφή" not "αρχείο" (file)
        (r"\bαρχεία σε αυτή τη ζώνη\b", "εγγραφές σε αυτή τη ζώνη"),
        (r"\bαρχεία σε αυτήν τη ζώνη\b", "εγγραφές σε αυτήν τη ζώνη"),
        # Remove stray spaces after hyphen
        (r"\be- ", "e-"),
        (r"\bE- ", "E-"),
    ]


def _subs_sl():
    """Slovenian: DNS terminology + UI wizard sense fixes."""
    return [
        # "wizard" -> Argos picks "čarovnik" (magician); software helper is "pomočnik"
        (r"\bČarovniki\b", "Pomočniki"),
        (r"\bčarovniki\b", "pomočniki"),
        (r"\bČarovnik\b", "Pomočnik"),
        (r"\bčarovnik\b", "pomočnik"),
        (r"\bčarovnika\b", "pomočnika"),
        (r"\bČarovnika\b", "Pomočnika"),
        # Remove stray spaces after hyphen
        (r"\be- ", "e-"),
        (r"\bE- ", "E-"),
        # "razsuti tovor" (bulk cargo) -> "množični" for bulk operations
        (r"\brazsutega tovora\b", "množične registracije"),
        (r"\bRegistracija razsutega tovora\b", "Množična registracija"),
        # "kanonično naročilo" (canonical purchase order) -> "kanonični vrstni red"
        (r"\bkanoničnem naročilu\b", "kanoničnem vrstnem redu"),
        (r"\bkanonično naročilo\b", "kanonični vrstni red"),
        # Fix "» install / «" path spacing
        (r"»\s*install\s*/\s*«", "»install/«"),
    ]


def _subs_bg():
    """Bulgarian: DNS terminology + UI wizard sense fixes."""
    return [
        # "wizard" -> Argos picks "магьосник" (magician); software helper is "помощник"
        (r"\bМагьосниците\b", "Помощниците"),
        (r"\bмагьосниците\b", "помощниците"),
        (r"\bМагьосник\b", "Помощник"),
        (r"\bмагьосник\b", "помощник"),
        (r"\bМагьосници\b", "Помощници"),
        (r"\bмагьосници\b", "помощници"),
        (r"\bмагьосника\b", "помощника"),
        (r"\bМагьосника\b", "Помощника"),
    ]


def _subs_ga():
    """Irish: most IT terms keep English; fix obvious mistranslations."""
    return [
        # Argos repeated the whole translation for short single-word sources,
        # e.g. "Type" -> "Cineál Cineál Cineál Cineál". Anchored to the entire
        # msgstr so only these degenerate entries collapse.
        (r"^(\S+)(?: \1)+$", r"\1"),
    ]


def _subs_mt():
    """Maltese: DNS terminology fixes."""
    return []


def _subs_ms():
    """Malay: DNS terminology fixes."""
    return [
        # Argos duplicated words mid-sentence throughout this locale, e.g.
        # "Zona Zona tidak ditemukan" and "Catatan Perubahan Catatan Catatan".
        # Malay reduplication is hyphenated ("buku-buku"), never space-separated,
        # so collapsing a repeated run is safe. The 3+ char floor keeps IPv6 and
        # record-format examples like "xx xx" intact.
        (r"\b(\w{3,})\b(?: \1\b)+", r"\1"),
        # Argos split "E-mel" (email) across the hyphen
        (r"\bE- mel\b", "E-mel"),

        # Argos produced Indonesian vocabulary rather than Malay. These pairs have
        # no competing sense in this UI, so they substitute unconditionally.
        (r"\bditemukan\b", "dijumpai"),
        (r"\bDitemukan\b", "Dijumpai"),
        (r"\bprioritas\b", "keutamaan"),
        (r"\bPrioritas\b", "Keutamaan"),
        (r"\bcocok\b", "sepadan"),
        (r"\bKelompok\b", "Kumpulan"),
        (r"\bkelompok\b", "kumpulan"),
        (r"\bberkas\b", "fail"),
        (r"\bBerkas\b", "Fail"),
        (r"\bsilakan\b", "sila"),
        (r"\bSilakan\b", "Sila"),
        (r"\bgalat\b", "ralat"),
        (r"\bGalat\b", "Ralat"),
        (r"\bsertifikat\b", "sijil"),
        (r"\bSertifikat\b", "Sijil"),
        (r"\bdinonaktifkan\b", "dilumpuhkan"),
        (r"\bdiperbarui\b", "dikemas kini"),
        (r"\bnomor\b", "nombor"),
        (r"\bNomor\b", "Nombor"),
        (r"\btombol\b", "butang"),
        (r"\bpersentase\b", "peratusan"),
        (r"\bPersentase\b", "Peratusan"),
        (r"\bpengaturan\b", "tetapan"),
        (r"\bPengaturan\b", "Tetapan"),
        (r"\bkebijakan\b", "dasar"),
        (r"\bKebijakan\b", "Dasar"),
        (r"\bkomentar\b", "komen"),
        (r"\bKomentar\b", "Komen"),
        (r"\btidak valid\b", "tidak sah"),
        (r"\bTidak valid\b", "Tidak sah"),
        (r"\bdihapus\b", "dipadam"),
        (r"\bDihapus\b", "Dipadam"),
        (r"\bkarena\b", "kerana"),
        (r"\bKarena\b", "Kerana"),
        (r"\bmengirim\b", "menghantar"),
        (r"\btipe\b", "jenis"),
        (r"\bTipe\b", "Jenis"),
        (r"\bkeamanan\b", "keselamatan"),
        (r"\bKeamanan\b", "Keselamatan"),
        (r"\bbisa\b", "boleh"),
        # "rekor" is the Indonesian spelling; the DNS term is "rekod"
        (r"\brekor\b", "rekod"),
        (r"\bRekor\b", "Rekod"),
        (r"\brekaman\b", "rekod"),
        (r"\bRekaman\b", "Rekod"),

        # "catatan" renders both Record and Note, so it only becomes "rekod" when
        # the English source is about a record. Same for "rekaman".
        ((r"\brecords?\b", r"\b(note|log|comment)\b"), r"\bCatatan\b", "Rekod"),
        ((r"\brecords?\b", r"\b(note|log|comment)\b"), r"\bcatatan\b", "rekod"),
        ((r"\bpermission", None), r"\bIzin\b", "Kebenaran"),
        ((r"\bpermission", None), r"\bizin\b", "kebenaran"),
    ]


def _subs_id():
    """Indonesian: normalize terminology that drifted between synonyms."""
    return [
        # "rekod" is Malay. This file settled on "rekaman" for a DNS record
        # (562 entries against 98), so the stray Malay forms move to it.
        (r"\brekod\b", "rekaman"),
        (r"\bRekod\b", "Rekaman"),

        # "templat" is the Indonesian spelling and already dominates 189 to 63.
        # Indonesian has no plural -s, so "templates" collapses to the same word.
        # A slash counts as a word boundary, so the lookaround is what keeps the
        # literal path templates/emails/custom/ from being rewritten; the \b alone
        # already excludes the underscored config key default_zone_template.
        (r"(?<![/\\])\btemplates?\b(?![/\\])", "templat"),
        (r"(?<![/\\])\bTemplates?\b(?![/\\])", "Templat"),

        # "catatan" renders both Record and Note, so it only becomes "rekaman"
        # when the English source is about a record.
        ((r"\brecords?\b", r"\b(note|log|comment)\b"), r"\bCatatan\b", "Rekaman"),
        ((r"\brecords?\b", r"\b(note|log|comment)\b"), r"\bcatatan\b", "rekaman"),
    ]


def _subs_sr():
    """Serbian: keep API in Latin like every other acronym in this file."""
    return [
        # The file is Cyrillic throughout but leaves DNSSEC, PowerDNS and URL in
        # Latin, and already writes API that way in 28 entries against 59. The
        # acronym also has to match the api.* config keys users search for.
        (r"\bАПИ\b", "API"),
    ]


def _subs_pt_br():
    """pt_BR refinements after pt_PT seed: BR-natural phrasing."""
    return [
        # "Não tem permissão" is European; BR more naturally says "Você não tem permissão"
        (r"\bNão tem permissão\b", "Você não tem permissão"),
        # "Utilize" -> "Use" (BR uses both; Use is more frequent in software UI)
        (r"\bUtilize\b", "Use"),
        (r"\butilize\b", "use"),
    ]


def _subs_sq():
    """Albanian: wizard sense fix (magjistar -> ndihmës)."""
    return [
        (r"\bmagjistar\b", "ndihmës"),
        (r"\bMagjistar\b", "Ndihmës"),
        (r"\bmagjistari\b", "ndihmësi"),
        (r"\bMagjistari\b", "Ndihmësi"),
        (r"\bmagjistarë\b", "ndihmës"),
        (r"\bMagjistarë\b", "Ndihmës"),
    ]


def _subs_hi():
    """Hindi: wizard sense fix (jaadugar -> sahaayak)."""
    return [
        (r"जादूगर", "सहायक"),
    ]


def _subs_th():
    """Thai: wizard sense fix."""
    return [
        (r"พ่อมด", "ตัวช่วย"),
    ]


def _subs_zh_tw():
    """zh_TW vocabulary fixes: zhconv only converts characters, not Mainland vs Taiwan words."""
    return [
        # software/computing vocabulary differences
        (r"配置文件", "設定檔"),       # config file
        (r"配置", "設定"),             # config (general)
        (r"設置", "設定"),             # settings
        (r"程序", "程式"),             # program (computer)
        (r"創建", "建立"),             # create
        (r"默認", "預設"),             # default
        (r"用戶", "使用者"),           # user
        (r"信息", "資訊"),             # information
        (r"軟件", "軟體"),             # software
        (r"網絡", "網路"),             # network
        (r"網絡接口", "網路介面"),     # network interface
        (r"接口", "介面"),             # interface
        (r"服務器", "伺服器"),         # server
        (r"數據庫", "資料庫"),         # database
        (r"數據", "資料"),             # data
        (r"鼠標", "滑鼠"),             # mouse
        (r"視頻", "影片"),             # video
        (r"打印", "列印"),             # print
        (r"幫助", "說明"),             # help
        (r"屏幕", "螢幕"),             # screen
        (r"質量", "品質"),             # quality
        (r"水平", "水準"),             # level/standard
        (r"在線", "線上"),             # online
        (r"離線", "離線"),             # offline (same)
        (r"主機", "主機"),             # host (same)
        (r"備份", "備份"),             # backup (same)
        # zhconv may keep "未找到" Mainland phrasing
        (r"未找到", "找不到"),
    ]


def _subs_bs():
    """Bosnian refinements after hr_HR seed: BS-specific lexicon and month names.

    Bosnian and Croatian are mutually intelligible; only the words that diverge in
    BS standard get rewritten. The big ones for DNS-admin UI are:
      - server/system terminology: HR \"poslužitelj\"/\"sustav\" -> BS \"server\"/\"sistem\"
      - dot/exact: HR \"točka\"/\"točno\" -> BS \"tačka\"/\"tačno\" (t before k/n)
      - months: HR siječanj/veljača/... -> BS januar/februar/...
    """
    return [
        # === server: HR \"poslužitelj\" -> BS \"server\" ===
        (r"\bposlužiteljima\b", "serverima"),
        (r"\bposlužitelje\b", "servere"),
        (r"\bposlužitelju\b", "serveru"),
        (r"\bposlužitelja\b", "servera"),
        (r"\bposlužitelji\b", "serveri"),
        (r"\bposlužiteljem\b", "serverom"),
        (r"\bposlužitelj\b", "server"),
        (r"\bPoslužiteljima\b", "Serverima"),
        (r"\bPoslužitelje\b", "Servere"),
        (r"\bPoslužitelju\b", "Serveru"),
        (r"\bPoslužitelja\b", "Servera"),
        (r"\bPoslužitelji\b", "Serveri"),
        (r"\bPoslužitelj\b", "Server"),
        # === system: HR \"sustav\" -> BS \"sistem\" ===
        (r"\bsustavima\b", "sistemima"),
        (r"\bsustave\b", "sisteme"),
        (r"\bsustavu\b", "sistemu"),
        (r"\bsustava\b", "sistema"),
        (r"\bsustavi\b", "sistemi"),
        (r"\bsustav\b", "sistem"),
        (r"\bSustavima\b", "Sistemima"),
        (r"\bSustave\b", "Sisteme"),
        (r"\bSustavu\b", "Sistemu"),
        (r"\bSustava\b", "Sistema"),
        (r"\bSustavi\b", "Sistemi"),
        (r"\bSustav\b", "Sistem"),
        # === dot/point/exact: HR \"točk-\"/\"točn-\" -> BS \"tačk-\"/\"tačn-\" ===
        (r"\btočka\b", "tačka"),
        (r"\btočke\b", "tačke"),
        (r"\btočki\b", "tački"),
        (r"\btočku\b", "tačku"),
        (r"\btočkom\b", "tačkom"),
        (r"\btočkama\b", "tačkama"),
        (r"\bTočka\b", "Tačka"),
        (r"\bTočke\b", "Tačke"),
        (r"\bTočku\b", "Tačku"),
        (r"\btočno\b", "tačno"),
        (r"\bTočno\b", "Tačno"),
        (r"\btočan\b", "tačan"),
        (r"\btočna\b", "tačna"),
        (r"\btočni\b", "tačni"),
        (r"\bTočni\b", "Tačni"),
        (r"\btočnost\b", "tačnost"),
        (r"\btočnosti\b", "tačnosti"),
        # colon: HR \"dvotočka\" (literally \"two-dots\") -> BS \"dvotačka\"
        (r"\bdvotočka\b", "dvotačka"),
        (r"\bdvotočke\b", "dvotačke"),
        (r"\bdvotočku\b", "dvotačku"),
        (r"\bdvotočkom\b", "dvotačkom"),
        # === print: HR \"tisak\" -> BS \"štampa\" ===
        (r"\btisak\b", "štampa"),
        (r"\bTisak\b", "Štampa"),
        (r"\btiskati\b", "štampati"),
        (r"\btiskanje\b", "štampanje"),
        # === months: HR Slavic -> BS international ===
        (r"\bsiječanj\b", "januar"),
        (r"\bSiječanj\b", "Januar"),
        (r"\bveljača\b", "februar"),
        (r"\bVeljača\b", "Februar"),
        (r"\božujak\b", "mart"),
        (r"\bOžujak\b", "Mart"),
        (r"\btravanj\b", "april"),
        (r"\bTravanj\b", "April"),
        (r"\bsvibanj\b", "maj"),
        (r"\bSvibanj\b", "Maj"),
        (r"\blipanj\b", "juni"),
        (r"\bLipanj\b", "Juni"),
        (r"\bsrpanj\b", "juli"),
        (r"\bSrpanj\b", "Juli"),
        (r"\bkolovoz\b", "august"),
        (r"\bKolovoz\b", "August"),
        (r"\brujan\b", "septembar"),
        (r"\bRujan\b", "Septembar"),
        (r"\blistopad\b", "oktobar"),
        (r"\bListopad\b", "Oktobar"),
        (r"\bstudeni\b", "novembar"),
        (r"\bStudeni\b", "Novembar"),
        (r"\bprosinac\b", "decembar"),
        (r"\bProsinac\b", "Decembar"),
        # === week: HR tjedan -> BS sedmica ===
        (r"\btjedan\b", "sedmica"),
        (r"\bTjedan\b", "Sedmica"),
        (r"\btjedna\b", "sedmice"),
        (r"\btjedno\b", "sedmično"),
        (r"\bTjedno\b", "Sedmično"),
        # === thousand: HR tisuća -> BS hiljada ===
        (r"\btisuća\b", "hiljada"),
        (r"\bTisuća\b", "Hiljada"),
        (r"\btisuću\b", "hiljadu"),
        (r"\btisućama\b", "hiljadama"),
        # === per/according to: HR sukladno -> BS u skladu sa ===
        (r"\bsukladno\b", "u skladu sa"),
        (r"\bSukladno\b", "U skladu sa"),
    ]


def _subs_ar():
    """Arabic: wizard sense fix (sahir -> mu'aawin)."""
    return [
        (r"ساحر", "معالج"),
        (r"السحرة", "المعالجات"),
    ]


def _subs_fa():
    """Farsi: wizard sense fix."""
    return [
        (r"جادوگر", "دستیار"),
        (r"جادوگران", "دستیاران"),
    ]


def _subs_he():
    """Hebrew: wizard sense fix."""
    return [
        (r"קוסם", "אשף"),
        (r"קוסמים", "אשפים"),
    ]


SUBS_BY_LOCALE = {
    "da_DK": _subs_da(),
    "el_GR": _subs_el(),
    "sl_SI": _subs_sl(),
    "bg_BG": _subs_bg(),
    "ga_IE": _subs_ga(),
    "mt_MT": _subs_mt(),
    "ms_MY": _subs_ms(),
    "id_ID": _subs_id(),
    "pt_BR": _subs_pt_br(),
    "zh_TW": _subs_zh_tw(),
    "sq_AL": _subs_sq(),
    "hi_IN": _subs_hi(),
    "th_TH": _subs_th(),
    "ar_SA": _subs_ar(),
    "fa_IR": _subs_fa(),
    "he_IL": _subs_he(),
    "bs_BA": _subs_bs(),
    "sr_RS": _subs_sr(),
}


def _matches_guard(entry, guard):
    """A guard is (include_pattern, exclude_pattern); either may be None."""
    include, exclude = guard
    if include and not re.search(include, entry.msgid, re.IGNORECASE):
        return False
    if exclude and re.search(exclude, entry.msgid, re.IGNORECASE):
        return False
    return True


def apply_corrections(po_path: str, subs):
    """Apply substitutions to the msgstr of every entry.

    A rule is either a 2-tuple (pattern, replacement) applied unconditionally, or a
    3-tuple (guard, pattern, replacement) where guard is (include, exclude) matched
    against the English msgid. The guarded form exists because a single translated
    word can render two different sources - Malay "catatan" is both Record and Note -
    so a blind substitution would corrupt the entries it does not mean to touch.
    """
    entries = poutil.parse(po_path)

    changes = 0
    for entry in entries:
        if entry.obsolete or entry.is_header:
            continue

        def rewrite(text):
            # An English fallback is not a translation, so rewriting single words
            # inside it only produces a mixed-language hybrid. merge_messages.py
            # owns those entries; leave them for a real translation pass.
            if text.strip() in (entry.msgid.strip(), (entry.msgid_plural or '').strip()):
                return text
            for rule in subs:
                if len(rule) == 3:
                    guard, pattern, repl = rule
                    if not _matches_guard(entry, guard):
                        continue
                else:
                    pattern, repl = rule
                text = re.sub(pattern, repl, text)
            return text

        if entry.plurals:
            for n in sorted(entry.plurals):
                new = rewrite(entry.plurals[n])
                if new != entry.plurals[n]:
                    entry.set_plural(n, new)
                    changes += 1
        elif entry.msgstr:
            new = rewrite(entry.msgstr)
            if new != entry.msgstr:
                entry.msgstr = new
                changes += 1

    poutil.write(po_path, entries)
    print(f"Applied {changes} substitutions to {po_path}")
    return changes


# Config keys, table names and file names. These are code: a translated or
# de-underscored copy sends the user looking for something that does not exist.
_IDENTIFIER = re.compile(
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b"
    r"|\b(?:dns|api|misc|db|ldap|mail|pdns)\.[a-z_.]+\b"
    r"|\b[\w-]+\.(?:php|html|twig|js|css|sql|dat|json|ya?ml|conf|ini)\b"
)


def _mangled_pattern(token):
    """Match the token with its separators padded, spaced or turned into spaces."""
    return re.escape(token).replace(r"_", r"[\s_]*").replace(r"\.", r"\s*\.\s*")


def restore_identifiers(po_path: str):
    """Rewrite identifiers whose separators were mangled back to the literal form.

    Only touches entries where the token survives intact apart from its separators.
    Where the translator replaced or truncated the token there is nothing to key
    off, so those are left for a human rather than guessed at.
    """
    entries = poutil.parse(po_path)

    changes = 0
    for entry in entries:
        if entry.obsolete or entry.is_header or not entry.msgid or not entry.msgstr:
            continue
        if entry.msgstr.strip() == entry.msgid.strip():
            continue

        text = entry.msgstr
        for token in sorted(set(_IDENTIFIER.findall(entry.msgid)), key=len, reverse=True):
            if token in text:
                continue
            text = re.sub(_mangled_pattern(token), token, text, flags=re.IGNORECASE)

        if text != entry.msgstr:
            entry.msgstr = text
            changes += 1

    if changes:
        poutil.write(po_path, entries)
    print(f"Restored identifiers in {changes} entries in {po_path}")
    return changes


# The translator glued a stray capital Z (sometimes ZZ) onto placeholders, so
# "got %d." renders as "got 64Z.". A real translation never puts a bare capital
# Z straight after a placeholder, which is what makes this safe to strip.
_PLACEHOLDER_LEAK = re.compile(r"(%(?:\d+\$)?[sdfucxXob])Z+")


def strip_placeholder_leaks(po_path: str):
    """Remove stray letters the translator appended to printf placeholders."""
    entries = poutil.parse(po_path)

    changes = 0
    for entry in entries:
        if entry.obsolete or entry.is_header or not entry.msgid:
            continue

        def fix(text):
            # Leave it alone when the source really does have a Z there.
            if not text or _PLACEHOLDER_LEAK.search(entry.msgid):
                return text
            return _PLACEHOLDER_LEAK.sub(r"\1", text)

        if entry.plurals:
            for n in sorted(entry.plurals):
                new = fix(entry.plurals[n])
                if new != entry.plurals[n]:
                    entry.set_plural(n, new)
                    changes += 1
        elif entry.msgstr:
            new = fix(entry.msgstr)
            if new != entry.msgstr:
                entry.msgstr = new
                changes += 1

    if changes:
        poutil.write(po_path, entries)
    print(f"Stripped placeholder leaks in {changes} entries in {po_path}")
    return changes


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <locale> [--identifiers|--placeholders]", file=sys.stderr)
        sys.exit(1)
    locale = sys.argv[1]
    identifiers_only = "--identifiers" in sys.argv[2:]
    placeholders_only = "--placeholders" in sys.argv[2:]
    if not (identifiers_only or placeholders_only) and locale not in SUBS_BY_LOCALE:
        print(f"Unknown locale: {locale}", file=sys.stderr)
        sys.exit(1)
    po_path = os.path.join(ROOT, f"locale/{locale}/LC_MESSAGES/messages.po")
    if not os.path.exists(po_path):
        print(f"Not found: {po_path}", file=sys.stderr)
        sys.exit(1)
    if identifiers_only:
        restore_identifiers(po_path)
    elif placeholders_only:
        strip_placeholder_leaks(po_path)
    else:
        apply_corrections(po_path, SUBS_BY_LOCALE[locale])


if __name__ == "__main__":
    main()
