#!/usr/bin/env python3
"""Translation sync checker for the i18n system.

Usage:
    python platform/scripts/sync_translations.py          # check for missing/extra keys
    python platform/scripts/sync_translations.py --fix    # add placeholders for missing keys

Uses en.json as the source of truth. Reports missing and extra keys in all
other language files (fr.json, ar.json, etc.).

With --fix, missing keys are added with the value "[NEEDS TRANSLATION] <english value>"
so they're easy to find and translate.
"""

import json
import sys
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"
SOURCE_LANG = "en"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    fix_mode = "--fix" in sys.argv

    source_path = I18N_DIR / f"{SOURCE_LANG}.json"
    if not source_path.exists():
        print(f"ERROR: Source file {source_path} not found.")
        sys.exit(1)

    source = load_json(source_path)
    source_keys = set(source.keys())
    print(f"Source ({SOURCE_LANG}.json): {len(source_keys)} keys\n")

    lang_files = sorted(I18N_DIR.glob("*.json"))
    has_issues = False

    for lang_file in lang_files:
        lang = lang_file.stem
        if lang == SOURCE_LANG:
            continue

        target = load_json(lang_file)
        target_keys = set(target.keys())

        missing = sorted(source_keys - target_keys)
        extra = sorted(target_keys - source_keys)

        if not missing and not extra:
            print(f"  {lang}.json: OK ({len(target_keys)} keys)")
            continue

        has_issues = True
        print(f"  {lang}.json: {len(target_keys)} keys")

        if missing:
            print(f"    MISSING ({len(missing)}):")
            for key in missing:
                print(f"      - {key}")
            if fix_mode:
                for key in missing:
                    target[key] = f"[NEEDS TRANSLATION] {source[key]}"
                # Reorder to match source key order
                ordered = {}
                for key in source:
                    if key in target:
                        ordered[key] = target[key]
                # Keep any extra keys at the end
                for key in target:
                    if key not in ordered:
                        ordered[key] = target[key]
                save_json(lang_file, ordered)
                print(f"    -> Added {len(missing)} placeholder(s) to {lang}.json")

        if extra:
            print(f"    EXTRA ({len(extra)}):")
            for key in extra:
                print(f"      + {key}")
            if fix_mode:
                for key in extra:
                    del target[key]
                save_json(lang_file, target)
                print(f"    -> Removed {len(extra)} extra key(s) from {lang}.json")

        print()

    if has_issues and not fix_mode:
        print("Run with --fix to add placeholders for missing keys and remove extras.")
        sys.exit(1)
    elif not has_issues:
        print("\nAll translations are in sync!")


if __name__ == "__main__":
    main()
