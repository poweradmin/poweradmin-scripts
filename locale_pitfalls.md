# Locale pitfalls

`scripts/locale_pitfalls.json` is the list of mistakes the machine translation actually made
in Poweradmin's catalogues, mined from the repair sweep rather than guessed at. It answers two
questions: what to check first when reviewing an existing locale, and what to warn a translator
about before they start a new one.

It does not overlap `scripts/dnt_glossary.json`. That file lists literals that must survive
byte-identical. This one covers the wrong-meaning classes a literal check cannot see.

## What is in it

| Part | Contents |
| --- | --- |
| `universal.word_sense` | English source words whose wrong sense was picked in several unrelated languages, with the locales that did it, a repair count, and one real before/after example |
| `universal.structural` | Failure classes that are not word-sense problems - dropped negations, lost trailing spaces, mangled acronyms, hallucinated content |
| `per_locale.<loc>.rules` | Confirmed bad renderings for one language, in the shape `apply_locale_corrections.py` applies |
| `per_locale.<loc>.review_only` | Substitutions that cannot be made safe. Report them, never apply them |

`locale_count` is the field to sort by. A trap seen in seven unrelated languages will be in the
eighth too.

## Reviewing an existing locale

1. **Run the mechanical passes first**, so the per-entry review is not spent on things a script
   can fix:

   ```bash
   python3 scripts/apply_locale_corrections.py <locale> --trailing
   python3 scripts/apply_locale_corrections.py <locale> --identifiers
   python3 scripts/apply_locale_corrections.py <locale> --placeholders
   ```

2. **Dry-run the pitfall rules** for that locale. Read every proposed change before writing:

   ```bash
   python3 scripts/apply_locale_corrections.py <locale> --pitfalls --dry-run
   python3 scripts/apply_locale_corrections.py <locale> --pitfalls
   ```

   The run also prints the `review_only` entries for that locale - known problems that need a
   human decision.

   A rule that fires on text a reviewer already accepted is a bug in the rule, not a find. If a
   dry run shows that, delete the rule and move it to `review_only` with the reason.

3. **Work the universal list top down.** For each `word_sense` entry, search the catalogue for
   the wrong sense in that language and check every hit. `record`, `colon`, `forward`, `digest`,
   `table` and `key` are where the volume is.

4. **Check the structural classes**, which no word search finds:
   - antonym msgid pairs sharing one msgstr (`Set as default` / `Unset as default`,
     `Server Running` / `Server Not Running`, `Sign Zone` / `Unsign Zone`)
   - `NO` or `NOT` copied through in English while the verb stays affirmative
   - msgids ending in `": "` whose msgstr lost the trailing space
   - `(ID` and `Are you sure you want to delete` gaining a closing paren or a question mark
   - `MUST` / `MUST NOT` / `NOT RECOMMENDED` and the `CRITICAL:` / `IMPORTANT:` prefixes
     flattened into plain statements
   - a message collapsed to a fragment, or fluent text that belongs to some other application

5. **Finish with a per-entry read** for the classes nothing mechanical catches - fluent-but-wrong
   and content-from-another-message. The brief in the review queue drives that pass.

## Briefing a new locale

Hand the translator, or the model doing the first pass, the terms from `universal.word_sense`
with their `intended` gloss. That is the whole point of the file: those senses were chosen wrong
in language after language, so stating the intended sense up front is cheaper than repairing it.

The short version to put in front of anyone starting from scratch:

- **record** is a DNS resource record - a row of zone data. Not a music recording, not a sports
  record, not a file, not a note, not a registry entry. This one trap accounts for more repairs
  than every other combined.
- **key** is cryptographic. Not a keyboard key, not a lock key, not the adjective "crucial".
- **zone** is a DNS zone. Not a geographic area and never a time zone.
- **table** is a database table. **port** is a TCP/UDP number. **host** is a named machine.
- **hash** is a digest, not hashish. **digest** is a digest, not digestion. **salt** is the
  NSEC3 salt, not the condiment.
- **colon** is the `:` character, not the large intestine, and "colon-separated" does not mean
  "colonised".
- **flags** are numeric bits. **string** is text. **space** is the space character.
  **character** is a text character, not a personality.
- **view** is a PowerDNS network view or a UI screen, not an opinion.
- **order** is sort order, not a purchase order and not a command.
- **master** / **supermaster** / **slave** are PowerDNS roles. Not craftsmen, not Superman, not
  people held in slavery.
- **wildcard** is `*`, not a playing card. **native** is the NATIVE zone type, not an indigenous
  person. **custom** means user-supplied, not border customs. **forward** is the opposite of
  reverse, not "ahead". **deprecated** means superseded, not financially depreciated.
  **issue** / **issuewild** are CAA tags about certificate issuance, not topics or problems.
- **leave empty** means leave the field blank, not depart.
- **unsign** removes a DNSSEC signature; an **unsigned** integer is non-negative. Different
  words in most languages.

Plus the hard rules that caused real regressions:

- Never drop, add or invert a negation. Never copy an emphatic `NO` or `NOT` through in English.
- Keep `MUST`, `MUST NOT`, `SHOULD NOT`, `NOT RECOMMENDED` and the `CRITICAL:` / `IMPORTANT:` /
  `WARNING:` prefixes at full strength.
- Record type and protocol names stay in Latin letters, spelled exactly. `AAAA` is not `AAA`,
  `SRV` is not `SVV`, `DNSSEC` is not `DNSEC`. Never transliterate them into the target script.
- Preserve trailing whitespace, printf placeholders, HTML tags, `[BRACKET_TOKENS]`, config keys,
  file paths and example addresses exactly.
- If a message ends mid-sentence it is a concatenation fragment. Leave it unfinished.

## Regenerating

The rules and the evidence were mined from the repair commits and the pending review slices.
Editing the file by hand is fine - it is data, not generated code, and nothing rewrites it
automatically. When adding a `per_locale` rule:

- only add one where the same wrong rendering occurred more than once in that locale
- dry-run it over the live catalogue first and read every hit
- for ASCII patterns use `(?<![/\\\w-]) ... (?![/\\\w-])` rather than `\b`. A `\b`-anchored rule
  once rewrote the literal path `templates/emails/custom/`, because `\b` treats `/` as a
  boundary. Acronym rules use `(?<![A-Za-z0-9]) ... (?![A-Za-z0-9])` instead, so a trailing
  hyphen in `DNSEC-signeret` still matches while `AAA` stays out of `AAAA`
- guard on the English msgid whenever the translated word has a second legitimate sense
- if you cannot make it safe, put it in `review_only` with the reason
