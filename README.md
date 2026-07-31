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
Everything is stdlib except `translate_new_locale.py`; see `requirements.txt`.

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

### Adding a new locale by machine translation

```
python3 scripts/translate_new_locale.py <locale> <iso639>   # Argos, offline, resumable
python3 scripts/fix_sentinel_leaks.py <locale>              # repair mangled placeholder sentinels
python3 scripts/apply_locale_corrections.py <locale>        # per-locale terminology fixes
python3 scripts/extract_failing_entries.py <locale>         # msgfmt failures -> JSON to hand-fix
python3 scripts/fallback_to_english.py <locale>             # last resort for unrecoverable entries
python3 scripts/compile_messages.py
```

Placeholders (`%s`, HTML tags) are masked as `ZZ<n>ZZ` sentinels before translation so the engine cannot reorder or
translate them. Some models mangle the sentinel anyway, which is what `fix_sentinel_leaks.py` repairs.

`apply_locale_corrections.py` holds hand-curated per-locale substitution tables. Add a `_subs_<lang>()` function and
register it in `SUBS_BY_LOCALE` to cover a new locale.

### Checks

| Script | Purpose |
|---|---|
| `check_translations.py` | empty and untranslated entries; exits 1 on findings |
| `check_locale_unicode.py` | mojibake, hidden Unicode, MT artifacts; `--fix` repairs in place |
| `check_translation_stats.py` | per-locale coverage, separating real translations from English fallbacks (also `composer locale:stats`) |
| `check_translation_integrity.py` | the damage classes - HARD ones exit 1, SOFT ones report only |

`composer locale:verify` in the parent repo runs the integrity and unicode checks plus msgfmt validation
and a .po/.mo drift check. **It cannot run in CI**: this repo is gitignored by the parent, so a CI checkout
has no `scripts/` directory and is limited to what gettext alone provides. Run it locally before pushing.

### Plural forms

`plural_forms.json` is the only table of gettext plural rules; `merge_messages.py` and
`translate_new_locale.py` read it and fail loudly on an unknown ISO code rather than defaulting to two
forms, which is wrong for every 3-, 4-, 5- and 6-form language.

Read a catalogue's rule with `poutil.header_plural_rule()`, never a regex over the raw file - 12 catalogues
wrap the header across several quoted lines. Compare two rules with `poutil.same_plural_rule()`, which
evaluates both over n=0..200; ru_RU and uk_UA ship different spellings of the identical Russian rule.

### cleanup_obsolete_translations.py

Removes entries no longer present in the `.pot`, matching on the full msgid so multi-line entries are handled
correctly. Flags: `--dry-run`, `--stats-only`, `--locale=`, `--module=`, `--force-check`, `--no-backup`.
The catalogue currently has zero obsolete entries.

## Other tooling

Release and maintenance helpers (`pre-release-check.sh`, `optimize-for-release.sh`, `format.sh`, `toggle_install.sh`,
`toggle_config.sh`, `e2e-sweep.sh`, `update_*.sh`, `update_copyright.py`, migration test scripts) and `proxy_test/`,
an end to end check for `NO_PROXY` handling. See each file's header for usage.

The two `test-migration-*.sh` scripts still cover `sql/` update scripts that ship today (a 4.0 install upgrading to
current runs them in sequence), but nothing invokes them automatically - run them by hand before a release.
