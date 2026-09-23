#!/usr/bin/env python3
"""Build a translation-before-render layout contract.

This stage runs before linguistic translation. It validates that every semantic unit has
safe geometry, estimates CJK capacity at preferred/minimum font sizes, writes model
batches carrying a layout budget, and produces an annotated layout preview PDF.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("plt_apply", HERE / "apply.py")
apply_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(apply_mod)


def load_units(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def overlap_area(a: fitz.Rect, b: fitz.Rect) -> float:
    r = a & b
    return 0.0 if r.is_empty else max(0.0, r.width) * max(0.0, r.height)


def font_bounds(unit: dict, min_scale: float) -> tuple[float, float, float]:
    regions = unit.get("regions", [])
    weighted = sum(float(r.get("font_size", 8.0)) * max(1, int(r.get("line_count", 1))) for r in regions)
    denom = max(1, sum(max(1, int(r.get("line_count", 1))) for r in regions))
    base = weighted / denom
    role = unit.get("role", "body")
    upper_factor = 1.12 if role == "body" else 1.09 if role in {"caption", "keywords"} else 1.05 if role == "table_cell" else 1.04 if role in {"heading", "keywords_heading"} else 1.02
    preferred_factor = 1.08 if role == "body" else 1.05 if role in {"caption", "keywords"} else 1.02
    upper = max(4.0, base * upper_factor)
    preferred = min(upper, max(4.0, base * preferred_factor))
    lower = max(3.8, base * min_scale)
    return lower, preferred, upper


def cjk_capacity(unit: dict, font: fitz.Font, fs: float) -> int:
    glyph_w = max(0.1, apply_mod.text_width(font, "汉", fs))
    asc = float(font.ascender if font.ascender else 1.05)
    asc_factor = min(1.25, max(0.85, asc))
    total = 0
    first_line = True
    for region in unit.get("regions", []):
        box = fitz.Rect(region["bbox"])
        if region.get("layout_mode") == "slots" and region.get("line_slots"):
            for raw in region["line_slots"]:
                slot = fitz.Rect(raw)
                baseline = slot.y0 + fs * asc_factor
                if baseline > slot.y1 + fs * 0.25:
                    break
                total += max(0, int(slot.width // glyph_w))
                first_line = False
        else:
            cap = apply_mod.region_capacity(region)
            pitch = max(float(region.get("line_pitch", fs * 1.3)), fs * 1.06)
            for li in range(cap):
                baseline = box.y0 + fs * asc_factor + li * pitch
                if baseline > box.y1 + fs * 0.25:
                    break
                indent = 0.0
                if first_line and region.get("first_indent"):
                    indent = min(float(region.get("indent_pt", 0.0)), max(0.0, box.width * 0.18))
                total += max(0, int(max(0.0, box.width - indent) // glyph_w))
                first_line = False
    return total


def geometry_failures(unit: dict, page_sizes: list[list[float]]) -> list[str]:
    failures = []
    for ri, region in enumerate(unit.get("regions", [])):
        pno = int(region.get("page", 0))
        if pno < 1 or pno > len(page_sizes):
            failures.append(f"region {ri}: invalid page {pno}")
            continue
        pw, ph = page_sizes[pno - 1]
        page = fitz.Rect(0, 0, float(pw), float(ph))
        box = fitz.Rect(region.get("bbox", [0, 0, 0, 0]))
        if box.is_empty or overlap_area(box, page) + 0.5 < max(0.0, box.width * box.height):
            failures.append(f"region {ri}: bbox outside page")
        exclusions = [fitz.Rect(x) for x in region.get("exclusions", [])]
        if region.get("layout_mode") == "slots":
            slots = [fitz.Rect(x) for x in region.get("line_slots", [])]
            if not slots:
                failures.append(f"region {ri}: slots mode without line slots")
            for si, slot in enumerate(slots):
                if any(overlap_area(slot, ex) > 0.8 for ex in exclusions):
                    failures.append(f"region {ri}: slot {si} intersects exclusion")
        else:
            if any(overlap_area(box, ex) > 0.8 for ex in exclusions):
                failures.append(f"region {ri}: flow bbox intersects exclusion; use slots")
    return failures


def build_unit_plan(unit: dict, page_sizes: list[list[float]], regular: fitz.Font, bold: fitz.Font, min_scale: float = 0.72) -> tuple[dict, list[str]]:
    metrics = bold if unit.get("role") in {"title", "heading", "keywords_heading"} else regular
    lower, preferred, upper = font_bounds(unit, min_scale)
    pref_cap = cjk_capacity(unit, metrics, preferred)
    hard_cap = cjk_capacity(unit, metrics, lower)
    # Reserve headroom for Latin tokens, punctuation and mixed-width scientific text.
    soft = max(1, int(math.floor(pref_cap * 0.84)))
    hard = max(1, int(math.floor(hard_cap * 0.86)))
    words = len(re.findall(r"[A-Za-z0-9]+(?:[-_/+.][A-Za-z0-9]+)*", unit.get("source", "")))
    expected = max(1, int(math.ceil(words * 1.55)))
    modes = sorted({r.get("layout_mode", "flow") for r in unit.get("regions", [])})
    pages = sorted({int(r.get("page", 0)) for r in unit.get("regions", [])})
    complex_layout = "slots" in modes or len(unit.get("regions", [])) > 1 or any(r.get("exclusions") for r in unit.get("regions", []))
    risk = "tight" if soft < expected else "complex" if complex_layout else "normal"
    plan = {
        "preferred_font_pt": round(preferred, 3),
        "min_font_pt": round(lower, 3),
        "max_font_pt": round(upper, 3),
        "soft_cjk_chars": soft,
        "hard_cjk_chars": hard,
        "source_word_count": words,
        "estimated_zh_chars": expected,
        "risk": risk,
        "layout_modes": modes,
        "pages": pages,
    }
    fails = geometry_failures(unit, page_sizes)
    if hard_cap <= 0:
        fails.append("no target-language capacity at minimum font size")
    return plan, fails


def write_batches(units: list[dict], workdir: Path, manifest: dict, max_chars: int) -> list[str]:
    batchdir = workdir / "batches"
    batchdir.mkdir(parents=True, exist_ok=True)
    for old in batchdir.glob("batch_*.json"):
        old.unlink()
    batches, cur, chars = [], [], 0
    for u in units:
        budget = u.get("layout_budget", {})
        item = {
            "id": u["id"],
            "role": u.get("role", "body"),
            "source": u.get("source", ""),
            "prev_tail": u.get("prev_tail", ""),
            "next_head": u.get("next_head", ""),
            "hard_tokens": u.get("hard_tokens", []),
            "layout_budget": {
                "soft_cjk_chars": budget.get("soft_cjk_chars"),
                "hard_cjk_chars": budget.get("hard_cjk_chars"),
                "preferred_font_pt": budget.get("preferred_font_pt"),
                "min_font_pt": budget.get("min_font_pt"),
                "risk": budget.get("risk"),
            },
        }
        n = len(item["source"])
        if cur and chars + n > max_chars:
            batches.append(cur); cur = []; chars = 0
        cur.append(item); chars += n
    if cur:
        batches.append(cur)
    names = []
    instructions = (
        "Translate each source as one coherent semantic unit. Preserve all technical meaning and hard_tokens. "
        "The layout_budget was computed before translation from safe target regions. Aim to stay within soft_cjk_chars "
        "using concise natural academic Chinese. hard_cjk_chars is a hard spatial warning, not permission to omit meaning: "
        "if faithful translation cannot fit, keep the meaning and let the pre-render fit gate request a compact repair."
    )
    for i, items in enumerate(batches):
        name = f"batch_{i:03d}.json"
        obj = {
            "source_language": manifest.get("source_language", "en"),
            "target_language": manifest.get("target_language", "zh-CN"),
            "layout_preflight": "PASS",
            "instructions": instructions,
            "items": items,
        }
        (batchdir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        names.append(name)
    return names


def make_preview(input_pdf: Path, units: list[dict], output: Path) -> None:
    doc = fitz.open(input_pdf)
    seen_ex = set()
    for u in units:
        uid = u.get("id", "")
        for r in u.get("regions", []):
            pno = int(r["page"]) - 1
            page = doc[pno]
            mode = r.get("layout_mode", "flow")
            if mode == "slots":
                for raw in r.get("line_slots", []):
                    page.draw_rect(fitz.Rect(raw), color=(0.1, 0.55, 0.2), width=0.45, stroke_opacity=0.72)
            else:
                page.draw_rect(fitz.Rect(r["bbox"]), color=(0.1, 0.35, 0.85), width=0.45, stroke_opacity=0.70)
            for ex in r.get("exclusions", []):
                key = (pno, tuple(round(float(v), 2) for v in ex))
                if key in seen_ex:
                    continue
                seen_ex.add(key)
                page.draw_rect(fitz.Rect(ex), color=(0.88, 0.15, 0.15), fill=(1.0, 0.88, 0.88), width=0.55, stroke_opacity=0.75, fill_opacity=0.08)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output, garbage=3, deflate=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--min-scale", type=float, default=0.72)
    ap.add_argument("--max-batch-chars", type=int, default=6500)
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).resolve()
    manifest_path = wd / "manifest.json"
    units_path = wd / "units.jsonl"
    if not manifest_path.exists() or not units_path.exists():
        raise SystemExit("Run prepare.py first; manifest.json and units.jsonl are required.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_pdf = Path(manifest["input_pdf"]).resolve()
    units = load_units(units_path)
    regular = fitz.Font(fontfile=str(apply_mod.locate_font(False)))
    bold = fitz.Font(fontfile=str(apply_mod.locate_font(True)))
    page_sizes = manifest.get("page_sizes", [])

    failures = []
    planned = []
    risk_pages = set()
    risks = {"normal": 0, "complex": 0, "tight": 0}
    for u in units:
        budget, fails = build_unit_plan(u, page_sizes, regular, bold, args.min_scale)
        nu = dict(u)
        nu["layout_budget"] = budget
        planned.append(nu)
        risks[budget["risk"]] = risks.get(budget["risk"], 0) + 1
        if budget["risk"] != "normal":
            risk_pages.update(budget["pages"])
        failures.extend([{"id": u.get("id"), "message": x} for x in fails])

    status = "PASS" if not failures else "FAIL"
    plan = {
        "engine_version": 3.1,
        "status": status,
        "input_pdf": str(input_pdf),
        "units": len(planned),
        "risk_counts": risks,
        "risk_pages": sorted(risk_pages),
        "failures": failures,
        "contract": "Translation batches may be created only after this preflight passes. Apply must use units_planned.jsonl and may not expand planned regions.",
    }
    (wd / "layout_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    with (wd / "units_planned.jsonl").open("w", encoding="utf-8") as f:
        for u in planned:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")

    if not args.no_preview:
        make_preview(input_pdf, planned, wd / "layout_preflight.pdf")

    batch_names = []
    if status == "PASS":
        batch_names = write_batches(planned, wd, manifest, args.max_batch_chars)
    else:
        batchdir = wd / "batches"
        if batchdir.exists():
            for old in batchdir.glob("batch_*.json"):
                old.unlink()

    manifest["engine_version"] = 3.1
    manifest["layout_preflight_required"] = True
    manifest["layout_preflight_status"] = status
    manifest["layout_risk_pages"] = sorted(risk_pages)
    manifest["batches"] = batch_names
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": status, "units": len(planned), "risk_counts": risks, "risk_pages": sorted(risk_pages), "failures": failures[:20], "batches": batch_names}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
