#!/usr/bin/env python3
"""Build a new locale .po by machine-translating en_EN.po with Argos.

Usage: python3 translate_new_locale.py <target_locale> <iso639_code>
Example: python3 translate_new_locale.py da_DK da

Run apply_locale_corrections.py afterwards for per-locale terminology fixes.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poutil  # noqa: E402

# Offline translation via Argos (no rate limits, no network calls during translation).
# Models must be pre-installed via argostranslate.package.
import argostranslate.translate

# Patterns that MT engines routinely garble. We mask them with ASCII sentinels (XPHXn)
# that the MT models cannot translate but reliably preserve through their byte tokenizers.
# Unicode bullets work for most languages but break on Irish/Malay Argos models.
_TAG_RE = re.compile(r'<[^<>]+>')
_PLACEHOLDER_RE = re.compile(r'%(?:\d+\$)?[sdfucxXob%]|\$\w+|\{[^{}]+\}')


def _mask(text: str):
    """Replace HTML tags + printf placeholders with ASCII sentinels; return (masked, table)."""
    table = []

    def _repl(match):
        idx = len(table)
        table.append(match.group(0))
        return f"ZZ{idx}ZZ"

    masked = _TAG_RE.sub(_repl, text)
    masked = _PLACEHOLDER_RE.sub(_repl, masked)
    return masked, table


def _unmask(text: str, table):
    """Restore sentinels back to original tokens."""
    for i, original in enumerate(table):
        text = text.replace(f"ZZ{i}ZZ", original)
        # MT models sometimes pad with spaces or lowercase the sentinel; try variants.
        text = re.sub(rf"ZZ\s*{i}\s*ZZ", original, text)
        text = re.sub(rf"zz\s*{i}\s*zz", original, text, flags=re.IGNORECASE)
    return text

ROOT = poutil.ROOT
EN_PO = poutil.po_path("en_EN")

# Plural forms per locale (ISO formula)
PLURAL_FORMS = {
    "ar": "nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);",
    "bg": "nplurals=2; plural=(n != 1);",
    "da": "nplurals=2; plural=(n != 1);",
    "el": "nplurals=2; plural=(n != 1);",
    "fa": "nplurals=2; plural=(n > 1);",
    "ga": "nplurals=5; plural=(n==1 ? 0 : n==2 ? 1 : n<7 ? 2 : n<11 ? 3 : 4);",
    "he": "nplurals=2; plural=(n != 1);",
    "hi": "nplurals=2; plural=(n != 1);",
    "ms": "nplurals=1; plural=0;",
    "mt": "nplurals=4; plural=(n==1 ? 0 : (n==0 || (n%100>1 && n%100<11)) ? 1 : (n%100>10 && n%100<20) ? 2 : 3);",
    "sl": "nplurals=4; plural=(n%100==1 ? 0 : n%100==2 ? 1 : n%100==3 || n%100==4 ? 2 : 3);",
    "sq": "nplurals=2; plural=(n != 1);",
    "th": "nplurals=1; plural=0;",
}


def batch_translate(texts, target_iso, batch_size=100, checkpoint=None, **_):
    """Translate a list of texts via Argos (offline, no rate limits).

    checkpoint: optional callable(translations_so_far_dict) invoked after every batch.
    Returns a list of translated strings in the same order. On a per-string error,
    the English source is kept as fallback.
    """
    out = [None] * len(texts)
    for i, text in enumerate(texts):
        masked, table = _mask(text)
        try:
            translated = argostranslate.translate.translate(masked, "en", target_iso) or masked
            out[i] = _unmask(translated, table)
        except Exception as e:
            print(f"  string {i} failed: {type(e).__name__}: {str(e)[:80]}", flush=True)
            out[i] = text
        if (i + 1) % batch_size == 0 or (i + 1) == len(texts):
            print(f"  ... translated {i + 1}/{len(texts)}", flush=True)
            if checkpoint:
                checkpoint(dict(zip(texts[:i + 1], out[:i + 1])))
    return out


def build_locale(target_locale: str, iso_code: str):
    entries = poutil.parse(EN_PO)

    # Collect all unique strings needing translation
    msgids_to_translate = []
    plurals_to_translate = []
    for e in entries:
        if e.is_header or e.obsolete or not e.msgid:
            continue
        msgids_to_translate.append(e.msgid)
        if e.msgid_plural:
            plurals_to_translate.append(e.msgid_plural)

    # Resume from cache if present (so a killed run doesn't lose all progress)
    cache_path = f"/tmp/{target_locale}_translations.json"
    cached = {"msgids": {}, "plurals": {}}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        print(f"Resuming from cache: {len(cached.get('msgids', {}))} msgids, {len(cached.get('plurals', {}))} plurals already done", flush=True)

    remaining_msgids = [m for m in msgids_to_translate if m not in cached["msgids"]]
    remaining_plurals = [p for p in plurals_to_translate if p not in cached["plurals"]]
    print(f"Translating {len(remaining_msgids)} msgids and {len(remaining_plurals)} plurals to {iso_code}...", flush=True)

    msgid_translations = dict(cached["msgids"])
    plural_translations = dict(cached["plurals"])

    def save_msgid_checkpoint(partial):
        merged = dict(msgid_translations)
        merged.update(partial)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"msgids": merged, "plurals": plural_translations}, f, ensure_ascii=False, indent=2)

    def save_plural_checkpoint(partial):
        merged = dict(plural_translations)
        merged.update(partial)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"msgids": msgid_translations, "plurals": merged}, f, ensure_ascii=False, indent=2)

    if remaining_msgids:
        new_translations = batch_translate(remaining_msgids, iso_code, checkpoint=save_msgid_checkpoint)
        msgid_translations.update(dict(zip(remaining_msgids, new_translations)))

    if remaining_plurals:
        new_plurals = batch_translate(remaining_plurals, iso_code, checkpoint=save_plural_checkpoint)
        plural_translations.update(dict(zip(remaining_plurals, new_plurals)))

    # Save dict for audit/reuse
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"msgids": msgid_translations, "plurals": plural_translations}, f, ensure_ascii=False, indent=2)
    print(f"Cached translations to {cache_path}")

    # Rebuild .po
    nplurals = nplurals_for(iso_code)
    for e in entries:
        if e.is_header:
            e.raw = rewrite_header(e.raw, target_locale, iso_code)
        elif e.obsolete or not e.msgid:
            continue
        elif e.msgid_plural:
            singular = msgid_translations.get(e.msgid, e.msgid)
            plural = plural_translations.get(e.msgid_plural, e.msgid_plural)
            for n in range(nplurals):
                e.set_plural(n, singular if n == 0 or nplurals == 1 else plural)
        else:
            e.msgstr = msgid_translations.get(e.msgid, e.msgid)

    out_path = poutil.po_path(target_locale)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    poutil.write(out_path, entries)
    print(f"Wrote {out_path}")


def rewrite_header(block: str, target_locale: str, iso_code: str) -> str:
    block = re.sub(r'"Language: [^"]*\\n"', f'"Language: {target_locale}\\\\n"', block)
    block = re.sub(r'"Last-Translator: [^"]*"', '"Last-Translator: Automatically generated\\\\n"', block)
    plural = PLURAL_FORMS.get(iso_code)
    if plural:
        if 'Plural-Forms:' in block:
            block = re.sub(r'"Plural-Forms: [^"]*\\n"', f'"Plural-Forms: {plural}\\\\n"', block)
        else:
            block = block.rstrip() + f'\n"Plural-Forms: {plural}\\n"'
    return block


def nplurals_for(iso_code: str) -> int:
    formula = PLURAL_FORMS.get(iso_code, "nplurals=2;")
    m = re.match(r"nplurals=(\d+)", formula)
    return int(m.group(1)) if m else 2


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <target_locale> <iso_code>")
        sys.exit(1)
    build_locale(sys.argv[1], sys.argv[2])
