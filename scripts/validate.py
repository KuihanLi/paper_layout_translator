#!/usr/bin/env python3
"""Validate session-generated paragraph translation files for the V2 layout engine."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_units(path: Path) -> dict[str, dict]:
    out = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                out[str(obj["id"])] = obj
    return out


def load_translations(translated_dir: Path) -> tuple[dict[str, str], list[str]]:
    translations: dict[str, str] = {}
    errors = []
    for p in sorted(translated_dir.glob("batch_*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{p.name}: invalid JSON: {e}")
            continue
        items = obj.get("items") if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            errors.append(f"{p.name}: expected a list or an object with an 'items' list")
            continue
        for item in items:
            if not isinstance(item, dict) or "id" not in item or "translation" not in item:
                errors.append(f"{p.name}: each item must contain id and translation")
                continue
            uid = str(item["id"])
            tr = str(item["translation"]).strip()
            if not tr:
                errors.append(f"{p.name}: empty translation for {uid}")
                continue
            # Later files override earlier ones; batch_repair.json intentionally wins.
            translations[uid] = tr
    return translations, errors


def token_present(token: str, translation: str) -> bool:
    # Numeric/model/acronym tokens should normally survive verbatim. Citations may
    # acquire Chinese punctuation but the core author-year text should still exist.
    if token in translation:
        return True
    core = re.sub(r"[()\[\],;:]", "", token).strip()
    return bool(core and core in re.sub(r"[()\[\],;:]", "", translation))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--write-merged", action="store_true")
    ap.add_argument("--strict-tokens", action="store_true", help="Treat missing hard tokens as validation errors instead of warnings.")
    args = ap.parse_args()
    wd = Path(args.workdir)
    units = load_units(wd / "units.jsonl")
    translations, errors = load_translations(wd / "translated")
    unknown = sorted(set(translations) - set(units))
    missing = sorted(set(units) - set(translations))
    if unknown:
        errors.append(f"unknown ids: {len(unknown)} (e.g. {unknown[:5]})")

    token_warnings = []
    for uid, tr in translations.items():
        if uid not in units:
            continue
        absent = [tok for tok in units[uid].get("hard_tokens", []) if not token_present(str(tok), tr)]
        if absent:
            token_warnings.append({"id": uid, "missing_tokens": absent[:20]})
    if args.strict_tokens and token_warnings:
        errors.append(f"{len(token_warnings)} translated unit(s) lost protected numeric/model/citation tokens")

    if args.write_merged:
        (wd / "translations_merged.json").write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "engine_version": 2,
        "expected": len(units),
        "translated": len(set(translations) & set(units)),
        "missing": len(missing),
        "unknown": len(unknown),
        "token_warnings": token_warnings[:100],
        "errors": errors,
        "missing_ids": missing[:100],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors or (args.strict and missing):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
