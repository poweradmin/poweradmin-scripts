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

The three stages, in order. `update_messages.sh` runs all three.

| Stage | Script | Writes |
|---|---|---|
| 1. Extract | `extract_strings.sh` | `locale/i18n-template-php.pot` |
| 2. Merge | `merge_messages.sh` | every `locale/*/LC_MESSAGES/messages.po` (+ timestamped backups) |
| 3. Compile | `compile_messages.sh` | every `locale/*/LC_MESSAGES/messages.mo` |

Extraction scans `lib/**/*.php` and `install/helpers/**/*.php` with `xgettext`, plus Twig templates for
`{% trans %}...{% endtrans %}` and `'string'|trans`. **The template scan is line based**, so a `{% trans %}` block
must sit on a single line to be picked up.

Merging fills any empty `msgstr` with the English source and flags it `#, auto-english-fallback`.

### Translating an existing locale

```
python3 scripts/extract_untranslated.py <locale>     # -> <locale>_untranslated.json
# fill in the translations
python3 scripts/import_translations.py <locale>_untranslated.json
./scripts/compile_messages.sh
```

`import_translations.py` also takes `<locale> --dict=<file.json>` for a flat `{msgid: translation}` map. Both forms
only fill entries whose `msgstr` is **empty**; an entry already holding an English fallback is left alone.

### Adding a new locale by machine translation

```
python3 scripts/translate_new_locale.py <locale> <iso639>   # Argos, offline, resumable
python3 scripts/fix_sentinel_leaks.py <locale>              # repair mangled placeholder sentinels
python3 scripts/apply_locale_corrections.py <locale>        # per-locale terminology fixes
python3 scripts/extract_failing_entries.py <locale>         # msgfmt failures -> JSON to hand-fix
python3 scripts/fallback_to_english.py <locale>             # last resort for unrecoverable entries
./scripts/compile_messages.sh
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
| `check_translation_stats.sh` | per-locale completion table (also `composer locale:stats`) |

The parent repo gates on these via `composer locale:check`.

### cleanup_obsolete_translations.sh

Removes entries no longer present in the `.pot`.

> **Known defect: do not run this yet.** It compares msgids using `sed 's/^msgid "//'`, so it only sees the first
> line of a multi-line msgid and can classify a live entry as obsolete and delete it. Always pass `--dry-run` first.

## Other tooling

Release and maintenance helpers (`pre-release-check.sh`, `optimize-for-release.sh`, `format.sh`, `toggle_install.sh`,
`toggle_config.sh`, `e2e-sweep.sh`, `update_*.sh`, migration test scripts) and `proxy_test/`, an end to end check for
`NO_PROXY` handling. See each file's header for usage.
