#!/usr/bin/env python3
"""Render paragraph translations into the original PDF without painting backgrounds.

V3.1 requires a PASSed pre-translation layout plan and runs an exact pre-render fit
gate before removing any source glyph. Only fully fitting translations are then
redacted/replaced inside the frozen safe regions. Images and vector graphics remain
untouched, and a dynamically subset CJK font is embedded for mixed Chinese-Latin text.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import hashlib
from datetime import datetime, timezone
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
        return {str(k): str(v).strip() for k, v in json.loads(merged.read_text(encoding="utf-8")).items() if str(v).strip()}
    out: dict[str, str] = {}
    for p in sorted((wd / "translated").glob("batch_*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        items = obj.get("items") if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id") is not None and str(item.get("translation", "")).strip():
                out[str(item["id"])] = str(item["translation"]).strip()
    return out


def locate_font(bold: bool = False) -> Path:
    names = [
        f"/usr/share/fonts/opentype/noto/NotoSerifCJK-{'Bold' if bold else 'Regular'}.ttc",
        f"/usr/share/fonts/opentype/noto/NotoSansCJK-{'Bold' if bold else 'Regular'}.ttc",
        f"/usr/share/fonts/opentype/noto/NotoSerifCJK-{'Bold' if bold else 'Regular'}.otf",
        f"/usr/share/fonts/opentype/noto/NotoSansCJK-{'Bold' if bold else 'Regular'}.otf",
    ]
    for name in names:
        p = Path(name)
        if p.exists():
            return p
    # Last-resort local font discovery. No network access is performed.
    for root in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if not root.exists():
            continue
        needles = ["*Serif*CJK*Bold*" if bold else "*Serif*CJK*Regular*", "*CJK*Bold*" if bold else "*CJK*Regular*"]
        for needle in needles:
            for p in root.rglob(needle):
                if p.suffix.lower() in {".ttc", ".ttf", ".otf"}:
                    return p
    raise RuntimeError("No local CJK font was found. Install a Noto/Source Han CJK font in the runtime before rendering Chinese text.")


def ttc_sc_index(path: Path) -> int:
    if path.suffix.lower() != ".ttc":
        return 0
    try:
        from fontTools.ttLib import TTCollection
        coll = TTCollection(str(path), lazy=True)
        fallback = 0
        for i, font in enumerate(coll.fonts):
            names = []
            for rec in font["name"].names:
                if rec.nameID not in {1, 2, 4, 6}:
                    continue
                try:
                    names.append(rec.toUnicode())
                except Exception:
                    pass
            joined = " ".join(names).lower()
            if " cjk sc" in joined or joined.endswith(" sc") or "simplified chinese" in joined:
                return i
            if "noto serif cjk sc" in joined or "noto sans cjk sc" in joined:
                return i
            if "jp" not in joined and "kr" not in joined and "tc" not in joined and "hk" not in joined:
                fallback = i
        return fallback
    except Exception:
        return 2  # Noto CJK collections conventionally store Simplified Chinese at index 2.


def subset_font(src: Path, out: Path, text: str) -> tuple[Path, bool]:
    """Create a tiny local font subset for embedding; fall back to full font if needed."""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
        out.parent.mkdir(parents=True, exist_ok=True)
        kwargs = {"fontNumber": ttc_sc_index(src)} if src.suffix.lower() == ".ttc" else {}
        font = TTFont(str(src), **kwargs)
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = [0, 1, 2, 3, 4, 5, 6]
        opts.name_legacy = True
        opts.name_languages = [0x409, 0x804]
        opts.notdef_glyph = True
        opts.notdef_outline = True
        opts.recommended_glyphs = True
        # PyMuPDF inserts Type0/CID text with Identity-H.  Renumbering glyph IDs in
        # a subset can therefore leave extraction intact while rendering blank CJK.
        opts.retain_gids = True
        sub = subset.Subsetter(options=opts)
        # Keep a small ASCII safety set for mixed terminology and punctuation.
        safety = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,:;!?%+-–—()[]/°²³×·•_="
        sub.populate(text=text + safety)
        sub.subset(font)
        font.save(str(out))
        return out, True
    except Exception as e:
        print(f"WARN: font subsetting failed ({e}); embedding the local font directly.")
        return src, False


def tokenise(text: str) -> list[str]:
    # Preserve Latin/model-name runs but allow CJK to wrap character by character.
    pat = re.compile(r"\s+|[A-Za-z0-9]+(?:[._/:+%\-–—^][A-Za-z0-9]+)*|.", re.S)
    return pat.findall(text.replace("\n", " "))


CLOSE_PUNCT = set("，。！？；：、）】》〉」』〕］｝,.!?;:%)]}")
OPEN_PUNCT = set("（【《〈「『〔［｛([{\"")


def text_width(font: fitz.Font, s: str, fs: float) -> float:
    try:
        return float(font.text_length(s, fontsize=fs))
    except Exception:
        return len(s) * fs


def consume_line(tokens: list[str], width: float, font: fitz.Font, fs: float) -> tuple[str, list[str]]:
    if width <= fs * 0.7:
        return "", tokens
    cur = ""
    cur_width = 0.0
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.isspace():
            if cur and not cur.endswith(" "):
                w = text_width(font, " ", fs)
                if cur_width + w <= width:
                    cur += " "
                    cur_width += w
            idx += 1
            continue
        tok_width = text_width(font, tok, fs)
        if not cur or cur_width + tok_width <= width:
            cur += tok
            cur_width += tok_width
            idx += 1
            continue
        # Closing punctuation may hang slightly into the margin rather than start a line.
        if tok in CLOSE_PUNCT and cur_width + tok_width <= width + fs * 0.55:
            cur += tok
            cur_width += tok_width
            idx += 1
        break
    if idx == 0 and tokens:
        # A single long Latin token: split at character granularity as a last resort.
        tok = tokens[0]
        take = ""
        take_width = 0.0
        for ch in tok:
            w = text_width(font, ch, fs)
            if take and take_width + w > width:
                break
            take += ch
            take_width += w
        cur = take or tok[:1]
        rest = ([tok[len(cur):]] if len(cur) < len(tok) else []) + tokens[1:]
        return cur.rstrip(), rest
    # Avoid leaving an opening punctuation at the end when possible.
    if cur and cur[-1] in OPEN_PUNCT and idx > 0:
        ch = cur[-1]
        cur = cur[:-1].rstrip()
        idx -= 1
        tokens = tokens[:idx] + [ch] + tokens[idx:]
        return cur, tokens[idx:]
    return cur.rstrip(), tokens[idx:]


def region_capacity(region: dict) -> int:
    return max(1, int(region.get("line_count", 1)))


def _rect_overlap_area(a: fitz.Rect, b: fitz.Rect) -> float:
    r = a & b
    return 0.0 if r.is_empty else max(0.0, r.width) * max(0.0, r.height)


def _line_box(x0: float, baseline: float, text: str, font: fitz.Font, fs: float) -> fitz.Rect:
    width = max(0.1, text_width(font, text, fs))
    asc = float(font.ascender if font.ascender else 1.05)
    desc = abs(float(font.descender if font.descender else -0.25))
    return fitz.Rect(x0, baseline - fs * max(0.75, asc), x0 + width, baseline + fs * max(0.15, desc))


def _collides(box: fitz.Rect, exclusions: list[list[float]]) -> bool:
    return any(_rect_overlap_area(box, fitz.Rect(raw)) > 0.8 for raw in exclusions)


def plan_flow(text: str, regions: list[dict], font: fitz.Font, fs: float) -> tuple[list[dict], str]:
    """Flow one semantic paragraph through safe visual slots.

    Regular prose uses a rectangular flow region.  Irregular / wrap-around prose uses
    the original source line slots so translated text cannot expand through a figure.
    """
    tokens = tokenise(text)
    placements: list[dict] = []
    first_overall_line = True
    for region in regions:
        box = fitz.Rect(region["bbox"])
        mode = region.get("layout_mode", "flow")
        lines = []
        if mode == "slots" and region.get("line_slots"):
            asc = float(font.ascender if font.ascender else 1.05)
            asc_factor = min(1.25, max(0.85, asc))
            for raw_slot in region["line_slots"]:
                if not tokens:
                    break
                slot = fitz.Rect(raw_slot)
                baseline = slot.y0 + fs * asc_factor
                if baseline > slot.y1 + fs * 0.25:
                    # Do not skip an earlier visual slot and continue later at an
                    # oversized font. Force the font search to try a smaller size.
                    placements.append({"region": region, "lines": lines})
                    return placements, "".join(tokens).strip()
                indent = 0.0
                # The slot x-position already contains the source indentation.
                width = max(fs, slot.width)
                line, tokens = consume_line(tokens, width, font, fs)
                if not line:
                    break
                lines.append({"text": line, "indent": indent, "slot_bbox": list(slot), "pitch": 0.0})
                first_overall_line = False
        else:
            cap = region_capacity(region)
            base_pitch = max(float(region.get("line_pitch", fs * 1.3)), fs * 1.06)
            asc = float(font.ascender if font.ascender else 1.05)
            asc_factor = min(1.25, max(0.85, asc))
            for li in range(cap):
                if not tokens:
                    break
                # Font search must obey the same vertical baseline constraint as the
                # renderer. Otherwise a large CJK size can appear to fit horizontally
                # and then be skipped at render time in a one-line continuation box.
                baseline = box.y0 + fs * asc_factor + li * base_pitch
                if baseline > box.y1 + fs * 0.25:
                    if li == 0 and tokens:
                        placements.append({"region": region, "lines": lines})
                        return placements, "".join(tokens).strip()
                    break
                indent = 0.0
                if first_overall_line and region.get("first_indent"):
                    indent = min(float(region.get("indent_pt", 0.0)), max(0.0, box.width * 0.18))
                width = max(fs, box.width - indent)
                line, tokens = consume_line(tokens, width, font, fs)
                if not line:
                    break
                lines.append({"text": line, "indent": indent, "pitch": base_pitch})
                first_overall_line = False
            # Chinese often needs fewer glyphs than English.  Use a bounded amount of
            # extra leading so the translated paragraph occupies the original vertical
            # rhythm instead of leaving a conspicuous blank tail.
            if len(lines) >= 2:
                asc = float(font.ascender if font.ascender else 1.05)
                room_pitch = max(fs * 1.06, (box.height - fs * max(0.90, asc)) / max(1, len(lines) - 1))
                pitch = min(room_pitch, base_pitch * 1.22, fs * 1.55)
                for line in lines:
                    line["pitch"] = pitch
        placements.append({"region": region, "lines": lines})
    leftover = "".join(tokens).strip()
    return placements, leftover


def choose_font_size(text: str, unit: dict, font: fitz.Font, min_scale: float) -> tuple[float, list[dict], str]:
    regions = unit["regions"]
    base = sum(float(r.get("font_size", 8.0)) * max(1, int(r.get("line_count", 1))) for r in regions) / max(1, sum(max(1, int(r.get("line_count", 1))) for r in regions))
    role = unit.get("role", "body")
    if role == "body":
        upper_factor = 1.12
    elif role in {"caption", "keywords"}:
        upper_factor = 1.09
    elif role == "table_cell":
        upper_factor = 1.05
    elif role in {"heading", "keywords_heading"}:
        upper_factor = 1.04
    else:
        upper_factor = 1.02
    upper = max(4.0, base * upper_factor)
    lower = max(3.8, base * min_scale)

    # First verify the minimum is feasible.  If it is not, no font search can solve
    # the region without a compact translation / structural repair.
    low_plan, low_left = plan_flow(text, regions, font, lower)
    if low_left:
        return lower, low_plan, low_left

    best_fs, best_plan = lower, low_plan
    lo, hi = lower, upper
    # Three bounded probes are enough for visual typography; high-precision binary
    # searches were expensive on dense papers without a visible benefit.
    for _ in range(3):
        mid = hi if _ == 0 else (lo + hi) / 2.0
        p, left = plan_flow(text, regions, font, mid)
        if not left:
            best_fs, best_plan = mid, p
            lo = mid
        else:
            hi = mid
    return best_fs, best_plan, ""


def add_redactions(doc: fitz.Document, units: list[dict], translations: dict[str, str]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for u in units:
        if not translations.get(u["id"]):
            continue
        for region in u.get("regions", []):
            pno = int(region["page"]) - 1
            page = doc[pno]
            for bbox in region.get("redactions", []):
                r = fitz.Rect(bbox) & page.rect
                if r.is_empty:
                    continue
                page.add_redact_annot(r, fill=None, cross_out=False)
                counts[pno] = counts.get(pno, 0) + 1
    for pno in sorted(counts):
        # Critical: remove text only. Images and vector graphics/backgrounds remain untouched.
        doc[pno].apply_redactions(images=0, graphics=0, text=0)
    return counts


def render_unit(doc: fitz.Document, unit: dict, translation: str, reg_font: Path, bold_font: Path, reg_metrics: fitz.Font, bold_metrics: fitz.Font, min_scale: float) -> tuple[bool, dict]:
    bold = unit.get("role") in {"title", "heading", "keywords_heading"}
    fontfile = bold_font if bold else reg_font
    metrics = bold_metrics if bold else reg_metrics
    fs, placements, leftover = choose_font_size(translation, unit, metrics, min_scale)
    alias = "PLTB" if bold else "PLTR"
    inserted_lines = 0
    inserted_boxes = []
    collisions = []
    for placement in placements:
        region = placement["region"]
        page = doc[int(region["page"]) - 1]
        try:
            page.insert_font(fontname=alias, fontfile=str(fontfile))
        except Exception:
            pass
        box = fitz.Rect(region["bbox"])
        color = tuple(float(x) for x in region.get("color", [0, 0, 0]))
        exclusions = region.get("exclusions", [])
        for li, line in enumerate(placement["lines"]):
            asc = float(metrics.ascender if metrics.ascender else 1.05)
            if line.get("slot_bbox"):
                slot = fitz.Rect(line["slot_bbox"])
                x0 = slot.x0
                baseline = slot.y0 + fs * min(1.25, max(0.85, asc))
            else:
                pitch = float(line["pitch"])
                x0 = box.x0 + float(line["indent"])
                baseline = box.y0 + fs * min(1.25, max(0.85, asc)) + li * pitch
                if baseline > box.y1 + fs * 0.25:
                    leftover = (line["text"] + " " + leftover).strip()
                    continue
            tbox = _line_box(x0, baseline, line["text"], metrics, fs)
            if _collides(tbox, exclusions):
                collisions.append({"page": int(region["page"]), "bbox": [round(v, 3) for v in tbox], "text": line["text"][:100]})
                continue
            page.insert_text(fitz.Point(x0, baseline), line["text"], fontname=alias, fontsize=fs, color=color, overlay=True)
            inserted_lines += 1
            inserted_boxes.append({"page": int(region["page"]), "bbox": [round(v, 3) for v in tbox]})
    ok = not bool(leftover) and not collisions
    return ok, {
        "id": unit["id"],
        "role": unit.get("role"),
        "pages": sorted({r["page"] for r in unit.get("regions", [])}),
        "layout_modes": sorted({r.get("layout_mode", "flow") for r in unit.get("regions", [])}),
        "font_size": round(fs, 3),
        "base_font_size": round(sum(float(r.get("font_size", 8.0)) for r in unit["regions"]) / max(1, len(unit["regions"])), 3),
        "inserted_lines": inserted_lines,
        "inserted_boxes": inserted_boxes,
        "collisions": collisions,
        "leftover": leftover,
    }



def pre_render_fit_check(units: list[dict], translations: dict[str, str], reg_metrics: fitz.Font, bold_metrics: fitz.Font, min_scale: float) -> tuple[list[dict], list[dict], list[dict]]:
    """Verify every translation fits the approved layout before mutating the PDF.

    This is a hard gate: failures create a repair batch and no redaction/rendering is
    attempted. Collision checks here are assertions against the precomputed layout
    contract, not a post-hoc repair mechanism.
    """
    overflow = []
    collision_items = []
    details = []
    for u in units:
        tr = translations.get(u.get("id", ""))
        if not tr:
            continue
        metrics = bold_metrics if u.get("role") in {"title", "heading", "keywords_heading"} else reg_metrics
        fs, placements, leftover = choose_font_size(tr, u, metrics, min_scale)
        collisions = []
        for placement in placements:
            region = placement["region"]
            box = fitz.Rect(region["bbox"])
            exclusions = region.get("exclusions", [])
            for li, line in enumerate(placement.get("lines", [])):
                asc = float(metrics.ascender if metrics.ascender else 1.05)
                if line.get("slot_bbox"):
                    slot = fitz.Rect(line["slot_bbox"])
                    x0 = slot.x0
                    baseline = slot.y0 + fs * min(1.25, max(0.85, asc))
                else:
                    pitch = float(line["pitch"])
                    x0 = box.x0 + float(line["indent"])
                    baseline = box.y0 + fs * min(1.25, max(0.85, asc)) + li * pitch
                tbox = _line_box(x0, baseline, line["text"], metrics, fs)
                if _collides(tbox, exclusions):
                    collisions.append({"page": int(region["page"]), "bbox": [round(v, 3) for v in tbox], "text": line["text"][:100]})
        budget = u.get("layout_budget", {})
        info = {
            "id": u.get("id"),
            "font_size": round(fs, 3),
            "leftover": leftover,
            "collisions": collisions,
            "soft_cjk_chars": budget.get("soft_cjk_chars"),
            "hard_cjk_chars": budget.get("hard_cjk_chars"),
            "translation_chars": len(tr.replace(" ", "")),
        }
        details.append(info)
        if leftover:
            overflow.append({
                "id": u.get("id"), "role": u.get("role"), "source": u.get("source", ""),
                "translation": tr, "leftover": leftover,
                "pages": sorted({r.get("page") for r in u.get("regions", [])}),
                "min_font_size": round(fs, 3), "layout_budget": budget,
            })
        if collisions:
            collision_items.append({"id": u.get("id"), "collisions": collisions, "layout_budget": budget})
    return overflow, collision_items, details

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pdf")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-scale", type=float, default=0.72)
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--allow-unplanned", action="store_true", help="Development only: bypass V3.1 layout_preflight contract.")
    args = ap.parse_args()

    input_pdf = Path(args.input_pdf).resolve()
    wd = Path(args.workdir).resolve()
    out = Path(args.output).resolve()
    plan_path = wd / "layout_plan.json"
    planned_units_path = wd / "units_planned.jsonl"
    if not args.allow_unplanned:
        if not plan_path.exists() or not planned_units_path.exists():
            raise SystemExit("Missing V3.1 layout preflight. Run layout_preflight.py before translation/apply.")
        plan_obj = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan_obj.get("status") != "PASS":
            raise SystemExit("Layout preflight is not PASS; fix geometry before translating or rendering.")
        units = load_units(planned_units_path)
    else:
        units = load_units(wd / "units.jsonl")
    translations = load_translations(wd)
    missing = [u["id"] for u in units if not translations.get(u["id"])]
    if missing and not args.allow_partial:
        raise SystemExit(f"Missing {len(missing)} translations. Run validate.py --strict first or use --allow-partial only for smoke tests.")

    # Only translated units contribute characters to the embedded subsets.
    all_text = "\n".join(translations.get(u["id"], "") for u in units if translations.get(u["id"]))
    font_dir = wd / "_font_cache"
    reg_src = locate_font(False)
    bold_src = locate_font(True)
    reg_font, reg_subset = subset_font(reg_src, font_dir / "paper-cjk-regular.otf", all_text)
    bold_font, bold_subset = subset_font(bold_src, font_dir / "paper-cjk-bold.otf", all_text)
    reg_metrics = fitz.Font(fontfile=str(reg_font))
    bold_metrics = fitz.Font(fontfile=str(bold_font))

    # V3.1 hard gate: prove that the translated paragraphs fit the already-approved
    # regions before removing a single source glyph. If this fails, repair the text
    # and rerun; do not render a known-bad PDF and discover overlap afterwards.
    fit_overflow, fit_collisions, fit_details = pre_render_fit_check(units, translations, reg_metrics, bold_metrics, args.min_scale)
    fit_report = {
        "engine_version": 3.1,
        "status": "PASS" if not fit_overflow and not fit_collisions else "FAIL",
        "overflow": len(fit_overflow),
        "collisions": len(fit_collisions),
        "details": fit_details,
    }
    (wd / "translation_fit_report.json").write_text(json.dumps(fit_report, ensure_ascii=False, indent=2), encoding="utf-8")
    if fit_overflow or fit_collisions:
        repair = {
            "instructions": "These translations failed the pre-render layout fit gate. Rewrite only the listed translations more compactly. Preserve every scientific claim, number, unit, citation, acronym/model name, and uncertainty. Do not split by PDF line and do not omit meaning to satisfy a character budget.",
            "items": [{"id": x["id"], "source": x["source"], "translation": x["translation"], "layout_budget": x.get("layout_budget", {})} for x in fit_overflow],
        }
        (wd / "repair_batch.json").write_text(json.dumps(repair, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"pre_render_fit": "FAIL", "overflow": len(fit_overflow), "collisions": len(fit_collisions), "repair_batch": str(wd / "repair_batch.json")}, ensure_ascii=False, indent=2))
        return 4 if fit_collisions else 3

    doc = fitz.open(input_pdf)
    redaction_counts = add_redactions(doc, units, translations)
    overflow = []
    collision_items = []
    details = []
    applied = 0
    for u in units:
        tr = translations.get(u["id"])
        if not tr:
            continue
        ok, info = render_unit(doc, u, tr, reg_font, bold_font, reg_metrics, bold_metrics, args.min_scale)
        details.append(info)
        if info.get("collisions"):
            collision_items.append({"id": u["id"], "pages": info["pages"], "collisions": info["collisions"]})
        if ok:
            applied += 1
        elif info.get("leftover"):
            overflow.append({
                "id": u["id"],
                "role": u.get("role"),
                "source": u["source"],
                "translation": tr,
                "leftover": info["leftover"],
                "pages": info["pages"],
                "min_font_size": info["font_size"],
            })

    out.parent.mkdir(parents=True, exist_ok=True)
    # subset fonts + deflation keep the file close to the source size instead of exploding via per-box fallback fonts.
    # Do not use clean=True here. On complex source PDFs it can rewrite Type0/CID
    # resources in a way that preserves ToUnicode extraction yet corrupts the visual
    # CID-to-glyph mapping of dynamically subset CJK fonts. Garbage collection +
    # deflation is safe and still keeps the file compact.
    doc.save(out, garbage=4, deflate=True)
    report = {
        "engine_version": 3.1,
        "output": str(out),
        "units": len(units),
        "translated": len(units) - len(missing),
        "applied": applied,
        "missing": len(missing),
        "overflow": len(overflow),
        "collision_guard_failures": len(collision_items),
        "redaction_pages": len(redaction_counts),
        "font_subsetting": bool(reg_subset and bold_subset),
        "font_subset_retain_gids": True,
        "layout_preflight_status": "PASS" if not args.allow_unplanned else "BYPASSED",
        "pre_render_fit_status": "PASS",
        "layout_modes": {
            "slots": sum(1 for u in units for r in u.get("regions", []) if r.get("layout_mode") == "slots"),
            "flow": sum(1 for u in units for r in u.get("regions", []) if r.get("layout_mode") != "slots"),
        },
        "output_bytes": out.stat().st_size,
        "source_bytes": input_pdf.stat().st_size,
        "size_ratio": round(out.stat().st_size / max(1, input_pdf.stat().st_size), 3),
        "overflow_items": overflow,
        "collision_items": collision_items,
        "details": details,
    }
    (wd / "apply_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = wd / "manifest.json"
    run_log = {
        "engine_version": 3.1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_pdf": str(input_pdf),
        "input_sha256": sha256_file(input_pdf),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
        "layout_plan_sha256": sha256_file(plan_path) if plan_path.exists() else None,
        "pre_render_fit_status": "PASS",
        "translations_sha256": sha256_file(wd / "translations_merged.json") if (wd / "translations_merged.json").exists() else None,
        "output_pdf": str(out),
        "output_sha256": sha256_file(out),
        "layout_modes": report["layout_modes"],
        "font_subset_retain_gids": True,
        "overflow": len(overflow),
        "collision_guard_failures": len(collision_items),
        "qa": None,
    }
    (wd / "translation_run_log.json").write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8")
    if overflow:
        repair = {
            "instructions": "Rewrite only these paragraph translations more compactly. Preserve every technical claim, number, unit, acronym/model name, and citation. Do not split a paragraph into line fragments.",
            "items": [{"id": x["id"], "source": x["source"], "translation": x["translation"]} for x in overflow],
        }
        (wd / "repair_batch.json").write_text(json.dumps(repair, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"details", "overflow_items", "collision_items"}}, ensure_ascii=False, indent=2))
    if collision_items:
        return 4
    return 0 if not overflow else 3


if __name__ == "__main__":
    raise SystemExit(main())
