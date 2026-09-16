#!/usr/bin/env python3
"""Structural QA for a layout-preserving translated PDF.

This complements visual render inspection. It checks page geometry, file-size blow-up,
render-time overflow reports, and residual source prose inside translated regions.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz


def load_units(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def load_translations(wd: Path) -> dict[str, str]:
    merged = wd / "translations_merged.json"
    if merged.exists():
        return {str(k): str(v) for k, v in json.loads(merged.read_text(encoding="utf-8")).items()}
    out = {}
    for p in sorted((wd / "translated").glob("batch_*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        items = obj.get("items", []) if isinstance(obj, dict) else obj
        for item in items:
            if isinstance(item, dict) and item.get("id") is not None:
                out[str(item["id"])] = str(item.get("translation", ""))
    return out


def compact_words(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def source_probe(source: str) -> str:
    words = re.findall(r"[A-Za-z]{4,}", source)
    # Skip common technical names that may intentionally survive translation.
    skip = {"catboost", "xgboost", "lightgbm", "arima", "sarima", "mape", "rmse", "stlf", "lstm"}
    words = [w for w in words if w.lower() not in skip]
    return " ".join(words[:5]).lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("original_pdf")
    ap.add_argument("translated_pdf")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    orig_path = Path(args.original_pdf).resolve()
    trans_path = Path(args.translated_pdf).resolve()
    wd = Path(args.workdir).resolve()
    orig = fitz.open(orig_path)
    trans = fitz.open(trans_path)
    failures = []
    warnings = []

    if len(orig) != len(trans):
        failures.append(f"page count differs: {len(orig)} vs {len(trans)}")
    size_mismatches = []
    for i in range(min(len(orig), len(trans))):
        a, b = orig[i].rect, trans[i].rect
        if abs(a.width - b.width) > 0.05 or abs(a.height - b.height) > 0.05:
            size_mismatches.append(i + 1)
    if size_mismatches:
        failures.append(f"page geometry differs on pages {size_mismatches[:20]}")

    ratio = trans_path.stat().st_size / max(1, orig_path.stat().st_size)
    if ratio > 3.5:
        warnings.append(f"output file is {ratio:.2f}x the source size; inspect font/image duplication")

    apply_report = {}
    ar = wd / "apply_report.json"
    if ar.exists():
        apply_report = json.loads(ar.read_text(encoding="utf-8"))
        if int(apply_report.get("overflow", 0)):
            failures.append(f"apply_report has {apply_report['overflow']} overflow unit(s)")

    units_path = wd / "units.jsonl"
    residual = []
    translated = load_translations(wd)
    if units_path.exists():
        units = load_units(units_path)
        page_text_cache = {i + 1: compact_words(trans[i].get_text("text")) for i in range(len(trans))}
        for u in units:
            if not translated.get(u["id"]):
                continue
            probe = source_probe(u.get("source", ""))
            if len(probe) < 12:
                continue
            # A probe is only meaningful when its words were contiguous enough in source.
            for pno in {int(r["page"]) for r in u.get("regions", [])}:
                if probe in page_text_cache.get(pno, ""):
                    residual.append({"id": u["id"], "page": pno, "probe": probe})
                    break
    if residual:
        warnings.append(f"possible visible/searchable source prose remains in {len(residual)} translated unit(s)")

    report = {
        "original": str(orig_path),
        "translated": str(trans_path),
        "page_count_original": len(orig),
        "page_count_translated": len(trans),
        "size_ratio": round(ratio, 3),
        "failures": failures,
        "warnings": warnings,
        "residual_source_probes": residual[:50],
        "apply_overflow": int(apply_report.get("overflow", 0)) if apply_report else None,
    }
    (wd / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures or (args.strict and warnings):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
