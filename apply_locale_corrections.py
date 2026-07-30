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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        # "record" noun - normalize to "post" (Danish DNS docs use both, "post" is clearer)
        (r"\bOpgørelsen blev\b", "Posten blev"),
        (r"\bOpgørelser\b", "Poster"),
        (r"\bopgørelser\b", "poster"),
        # "Optag" in record context (means recording button) -> "Post"
        (r"\bOptag oprettet\b", "Post oprettet"),
        (r"\bOptag opdateret\b", "Post opdateret"),
        (r"\bOptag slettet\b", "Post slettet"),
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
    "pt_BR": _subs_pt_br(),
    "zh_TW": _subs_zh_tw(),
    "sq_AL": _subs_sq(),
    "hi_IN": _subs_hi(),
    "th_TH": _subs_th(),
    "ar_SA": _subs_ar(),
    "fa_IR": _subs_fa(),
    "he_IL": _subs_he(),
    "bs_BA": _subs_bs(),
}


def apply_corrections(po_path: str, subs):
    """Walk the .po file and apply substitutions to msgstr lines AND their continuations.

    Tracks an in_msgstr state so multi-line msgstr blocks (where a leading `msgstr ""`
    is followed by indented `"..."` continuation lines) get processed too.
    """
    with open(po_path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    changes = 0
    new_lines = []
    in_msgstr = False
    for line in lines:
        if line.startswith("msgstr"):
            in_msgstr = True
        elif line.startswith("msgid") or line.startswith("#") or not line.strip():
            in_msgstr = False

        if in_msgstr and '"' in line:
            m = re.match(r'^((?:msgstr(?:\[\d+\])?\s+)?")(.*)("$)', line)
            if m:
                prefix, content, suffix = m.group(1), m.group(2), m.group(3)
                new_content = content
                for pattern, repl in subs:
                    new_content = re.sub(pattern, repl, new_content)
                if new_content != content:
                    changes += 1
                line = prefix + new_content + suffix
        new_lines.append(line)

    with open(po_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines))

    print(f"Applied {changes} substitutions to {po_path}")
    return changes


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <locale>", file=sys.stderr)
        sys.exit(1)
    locale = sys.argv[1]
    if locale not in SUBS_BY_LOCALE:
        print(f"Unknown locale: {locale}", file=sys.stderr)
        sys.exit(1)
    po_path = os.path.join(ROOT, f"locale/{locale}/LC_MESSAGES/messages.po")
    if not os.path.exists(po_path):
        print(f"Not found: {po_path}", file=sys.stderr)
        sys.exit(1)
    apply_corrections(po_path, SUBS_BY_LOCALE[locale])


if __name__ == "__main__":
    main()
