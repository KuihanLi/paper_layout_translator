#!/usr/bin/env python3
"""Structural QA for a layout-preserving translated PDF.

This complements visual render inspection. It checks page geometry, file-size blow-up,
render-time overflow reports, and residual source prose inside translated regions.
"""
from __future__ import annotations

import argparse
import json
import re
import hashlib
from collections import Counter
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




def image_hashes_by_page(doc: fitz.Document) -> dict[int, Counter]:
    out: dict[int, Counter] = {}
    for pno, page in enumerate(doc, start=1):
        hashes = Counter()
        for info in page.get_images(full=True):
            xref = int(info[0])
            try:
                data = doc.extract_image(xref).get("image", b"")
            except Exception:
                data = b""
            if data:
                hashes[hashlib.sha256(data).hexdigest()] += 1
        out[pno] = hashes
    return out


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))

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
        if int(apply_report.get("collision_guard_failures", 0)):
            failures.append(f"apply_report has {apply_report['collision_guard_failures']} text/exclusion collision(s)")
        if apply_report.get("layout_preflight_status") != "PASS":
            failures.append("output was not produced from a PASSed layout preflight contract")
        if apply_report.get("pre_render_fit_status") != "PASS":
            failures.append("output was not produced after a PASSed pre-render fit gate")

    # Source images must survive text-only redaction.  Compare extracted image bytes
    # page by page; mismatch is a warning because some PDFs can legally re-encode an
    # image object without changing its appearance.
    orig_images = image_hashes_by_page(orig)
    trans_images = image_hashes_by_page(trans)
    image_mismatch_pages = [p for p in orig_images if orig_images[p] != trans_images.get(p, Counter())]
    if image_mismatch_pages:
        warnings.append(f"image object hashes/counts differ on pages {image_mismatch_pages[:20]}; inspect those pages visually")

    translated_text = "\n".join(p.get_text("text") for p in trans)
    expected_cjk = any(contains_cjk(v) for v in load_translations(wd).values())
    if expected_cjk and not contains_cjk(translated_text):
        failures.append("translations contain CJK but rendered PDF text layer contains no CJK; possible subset/CID glyph failure")

    out_of_page = []
    for item in apply_report.get("details", []) if apply_report else []:
        for ib in item.get("inserted_boxes", []):
            pno = int(ib["page"])
            if pno < 1 or pno > len(trans):
                out_of_page.append({"id": item.get("id"), "page": pno, "bbox": ib.get("bbox")})
                continue
            box = fitz.Rect(ib["bbox"])
            page_box = trans[pno - 1].rect
            if box.x0 < page_box.x0 - 0.5 or box.y0 < page_box.y0 - 0.5 or box.x1 > page_box.x1 + 0.5 or box.y1 > page_box.y1 + 0.5:
                out_of_page.append({"id": item.get("id"), "page": pno, "bbox": ib.get("bbox")})
    if out_of_page:
        failures.append(f"{len(out_of_page)} inserted text line(s) extend outside page geometry")

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
        "collision_guard_failures": int(apply_report.get("collision_guard_failures", 0)) if apply_report else None,
        "out_of_page_insertions": out_of_page[:50],
        "image_mismatch_pages": image_mismatch_pages,
        "cjk_render_text_present": contains_cjk(translated_text) if expected_cjk else None,
    }
    (wd / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    run_log_path = wd / "translation_run_log.json"
    if run_log_path.exists():
        try:
            run_log = json.loads(run_log_path.read_text(encoding="utf-8"))
            run_log["qa"] = {
                "failures": failures,
                "warnings": warnings,
                "page_geometry_match": not size_mismatches and len(orig) == len(trans),
                "image_mismatch_pages": image_mismatch_pages,
                "out_of_page_insertions": len(out_of_page),
            }
            run_log_path.write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures or (args.strict and warnings):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
