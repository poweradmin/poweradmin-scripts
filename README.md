# poweradmin-scripts

Maintenance tooling for [Poweradmin](https://github.com/poweradmin/poweradmin). Clone this repo as `scripts/`
inside a poweradmin checkout: every script resolves the project root as its own parent directory, and the parent
repo gitignores `/scripts`.

```
poweradmin/
  lib/  locale/  templates/  vendor/
  scripts/          <- this repo
```

Run scripts from the project root (`./scripts/<name>`), not from inside `scripts/`.

## Requirements

Python 3 and GNU gettext (`xgettext`, `msgmerge`, `msgfmt`, `msguniq`, `msgattrib`, `msgen`, `msginit`) on `PATH`.
Everything is stdlib; there is nothing to `pip install`.

## Tests

```
python3 -m unittest discover -s scripts/tests     # from the project root
```

Stdlib `unittest` over the shared parser and the gates, on in-memory fixtures. The suite never reads or writes
the real catalogues and skips the cases that need gettext binaries when they are missing.

## Localization pipeline

The three stages, in order. `update_messages.py` runs them all; the merge step regenerates the template
itself, so stage 1 does not need a separate run.

| Stage | Script | Writes |
|---|---|---|
| 1. Extract | `extract_strings.py` | `locale/i18n-template-php.pot` |
| 2. Merge | `merge_messages.py` | every `locale/*/LC_MESSAGES/messages.po` (+ timestamped backups) |
| 3. Compile | `compile_messages.py` | every `locale/*/LC_MESSAGES/messages.mo` |

Extraction scans `lib/**/*.php` and `install/helpers/**/*.php` with `xgettext`, plus Twig templates for
`{% trans %}...{% endtrans %}` and `'string'|trans`. **The template scan is line based**, so a `{% trans %}` block
must sit on a single line to be picked up.

Merging fills any empty `msgstr` with the English source and flags it `#, auto-english-fallback`.
It refuses a regenerated template that has no msgids or lost more than 20% of them (a failed extraction would
otherwise obsolete every string in all 43 catalogues), and any gettext failure restores the catalogue's backup
and exits non-zero.

### Adding new strings to every locale

New source strings reach the catalogues through the merge, not by hand:

```
python3 scripts/merge_messages.py       # regenerates the .pot, then merges into all 43
python3 scripts/compile_messages.py
composer locale:verify
```

Every new entry lands holding the English source with a `#, auto-english-fallback` flag. **That flag is
the handle**: it names exactly which entries are new and untranslated in a given locale, which is what
`extract_untranslated.py` selects on. Translate them per locale with the round trip below.

For a handful of strings, edit the `.po` files directly instead. A full merge rewrites all 43 catalogues
and leaves a timestamped backup beside each one, which is a lot of churn for three entries.

### Translating an existing locale

```
python3 scripts/extract_untranslated.py <locale>     # -> <locale>_untranslated.json
# fill in the translations
python3 scripts/import_translations.py <locale>_untranslated.json
python3 scripts/compile_messages.py
```

`import_translations.py` also takes `<locale> --dict=<file.json>` for a flat `{msgid: translation}` map.
A **plural** msgid takes a `{"0": form, "1": form, ...}` map with one key per form the locale declares;
a bare string there is an error rather than a skipped entry. Both forms only fill entries that still need
translating unless you pass `--force`.

### Applying reviewed corrections

```
python3 scripts/apply_review_corrections.py <locale> [--plurals] [--dir=DIR]
```

Reads `DIR/OUT_<locale>_*.json` and applies them behind a gate: identical placeholders, HTML tags,
`[TOKEN]`s, whitespace, identifiers, IP literals and do-not-translate literals. One failure aborts the
whole locale, so a bad correction can never land half-applied. Reviewers must emit JSON rather than edit
`.po` files - parallel writes to one catalogue lose updates.

### Adding a new locale

The machine-translation bootstrap was removed once every shipped locale existed. Create the catalogue with
`msginit` against `locale/i18n-template-php.pot`, add its ISO code to `plural_forms.json` if missing, then
translate it with the round trip above.

`apply_locale_corrections.py` holds hand-curated per-locale substitution tables (add a `_subs_<lang>()` function
and register it in `SUBS_BY_LOCALE`) plus repair modes: `--identifiers`, `--placeholders`, `--trailing` and
`--pitfalls` (rules from `locale_pitfalls.json`, explained in `locale_pitfalls.md`). Every mode takes `--dry-run`.

### Checks

| Script | Purpose |
|---|---|
| `check_translations.py` | empty and untranslated entries; exits 1 on findings. Its untranslated rule is simpler than `poutil.is_untranslated()` (no fallback flag or short-word handling), so its counts can differ from the stats |
| `check_locale_unicode.py` | mojibake, hidden Unicode, MT artifacts; `--fix` repairs in place |
| `check_translation_stats.py` | per-locale coverage, separating real translations from English fallbacks (also `composer locale:stats`) |
| `check_translation_integrity.py` | the damage classes - HARD ones exit 1, SOFT ones report only |

`composer locale:verify` in the parent repo runs the integrity and unicode checks plus msgfmt validation
and a .po/.mo drift check. **It cannot run in CI**: this repo is gitignored by the parent, so a CI checkout
has no `scripts/` directory and is limited to what gettext alone provides. Run it locally before pushing.

### Plural forms

`plural_forms.json` is the only table of gettext plural rules; `merge_messages.py` reads it and fails loudly on an unknown ISO code rather than defaulting to two
forms, which is wrong for every 3-, 4-, 5- and 6-form language.

`check_translation_integrity.py` also reads it, to validate each catalogue's header.

Read a catalogue's rule with `poutil.header_plural_rule()`, never a regex over the raw file - 12 catalogues
wrap the header across several quoted lines. Compare two rules with `poutil.same_plural_rule()`, which
evaluates both over n=0..200; ru_RU and uk_UA ship different spellings of the identical Russian rule.

### cleanup_obsolete_translations.py

Removes entries no longer present in the `.pot`, plus obsolete blocks in both forms: gettext's `#~` lines and
the `# OBSOLETE:` comments `merge_messages.py` writes. Matching is on the full msgid, so multi-line entries are
handled correctly.

Before removing anything it searches the source tree for every candidate as a complete literal. A candidate that
is still in use means the template is stale, and the run is refused until `extract_strings.py` regenerates it.

Flags: `--dry-run`, `--stats-only`, `--verify-only`, `--skip-verify`, `--locale=`, `--module=`, `--force-check`,
`--no-backup`. Unknown flags are rejected. `--force-check` runs `msgmerge` first; with `--dry-run` it merges a
temp copy, never the catalogue.

`harvest_module_translations.py` copies translations that exist only in `lib/Module/*/locale` into the main
catalogues. Master and 4.5.x no longer ship module catalogues; it and the `--module=` flags stay for 4.4.x.

## Other tooling

Release and maintenance helpers (`pre-release-check.sh`, `toggle_install.sh`, `e2e-sweep.sh`, `update_*.sh`,
`update_*_servers.php`, `update_copyright.py`) and `proxy_test/`,
an end to end check for `NO_PROXY` handling. See each file's header for usage.

- `format.sh` runs `composer format:all` with dev dependencies, then restores the committed vendor/ whatever the
  outcome.
- `create_sqlite_db.sh <db-file> [pdns-schema-version]` builds a new SQLite database holding the PowerDNS schema
  (newest `sql/pdns/<N>` by default) and the Poweradmin tables, ready for the installer.
- The data updaters (`update_tlds.sh`, `update_public_suffix.sh`, `update_rdap_servers.php`,
  `update_whois_servers.php`) refuse a download that is empty or much smaller than the current file, and replace
  the file atomically.
