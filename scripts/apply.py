#!/usr/bin/env python3
"""Render paragraph translations into the original PDF without painting backgrounds.

V2 removes only source text glyphs through transparent PDF redaction while preserving
images and vector graphics. Translated paragraphs are then flowed through their
original multi-line / multi-column regions. A small dynamically subset CJK font is
embedded for natural mixed Chinese-Latin typography.
"""
from __future__ import annotations

import argparse
import json
import math
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
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.isspace():
            if cur and not cur.endswith(" "):
                proposal = cur + " "
                if text_width(font, proposal, fs) <= width:
                    cur = proposal
            idx += 1
            continue
        proposal = cur + tok
        if not cur or text_width(font, proposal, fs) <= width:
            cur = proposal
            idx += 1
            continue
        # Closing punctuation may hang slightly into the margin rather than start a line.
        if tok in CLOSE_PUNCT and text_width(font, proposal, fs) <= width + fs * 0.55:
            cur = proposal
            idx += 1
        break
    if idx == 0 and tokens:
        # A single long Latin token: split at character granularity as a last resort.
        tok = tokens[0]
        take = ""
        k = 0
        for k, ch in enumerate(tok, start=1):
            if take and text_width(font, take + ch, fs) > width:
                k -= 1
                break
            take += ch
        else:
            k = len(tok)
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


def plan_flow(text: str, regions: list[dict], font: fitz.Font, fs: float) -> tuple[list[dict], str]:
    tokens = tokenise(text)
    placements: list[dict] = []
    first_overall_line = True
    for ridx, region in enumerate(regions):
        box = fitz.Rect(region["bbox"])
        cap = region_capacity(region)
        pitch = max(float(region.get("line_pitch", fs * 1.3)), fs * 1.04)
        lines = []
        for li in range(cap):
            if not tokens:
                break
            indent = 0.0
            if first_overall_line and region.get("first_indent"):
                indent = min(float(region.get("indent_pt", 0.0)), max(0.0, box.width * 0.18))
            width = max(fs, box.width - indent)
            line, tokens = consume_line(tokens, width, font, fs)
            if not line:
                break
            lines.append({"text": line, "indent": indent, "pitch": pitch})
            first_overall_line = False
        placements.append({"region": region, "lines": lines})
    leftover = "".join(tokens).strip()
    return placements, leftover


def choose_font_size(text: str, unit: dict, font: fitz.Font, min_scale: float) -> tuple[float, list[dict], str]:
    regions = unit["regions"]
    base = sum(float(r.get("font_size", 8.0)) * max(1, int(r.get("line_count", 1))) for r in regions) / max(1, sum(max(1, int(r.get("line_count", 1))) for r in regions))
    role = unit.get("role", "body")
    upper_factor = 1.02 if role in {"body", "caption"} else 1.00
    upper = max(4.0, base * upper_factor)
    lower = max(3.8, base * min_scale)
    best = None
    best_left = text
    # Try source-size first; if it fits, keep it rather than inflating translated text.
    p, left = plan_flow(text, regions, font, min(base, upper),)
    if not left:
        return min(base, upper), p, ""
    lo, hi = lower, min(base, upper)
    for _ in range(16):
        mid = (lo + hi) / 2
        p, left = plan_flow(text, regions, font, mid)
        if not left:
            best = (mid, p)
            lo = mid
        else:
            best_left = left
            hi = mid
    if best:
        return best[0], best[1], ""
    p, left = plan_flow(text, regions, font, lower)
    return lower, p, left or best_left


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
    for placement in placements:
        region = placement["region"]
        page = doc[int(region["page"]) - 1]
        try:
            page.insert_font(fontname=alias, fontfile=str(fontfile))
        except Exception:
            pass
        box = fitz.Rect(region["bbox"])
        color = tuple(float(x) for x in region.get("color", [0, 0, 0]))
        for li, line in enumerate(placement["lines"]):
            pitch = float(line["pitch"])
            # Baseline from the original line top using the actual CJK font ascender.
            asc = float(metrics.ascender if metrics.ascender else 1.05)
            baseline = box.y0 + fs * min(1.25, max(0.85, asc)) + li * pitch
            # Keep the baseline safely inside the region's final line band.
            if baseline > box.y1 + fs * 0.25:
                continue
            point = fitz.Point(box.x0 + float(line["indent"]), baseline)
            page.insert_text(point, line["text"], fontname=alias, fontsize=fs, color=color, overlay=True)
            inserted_lines += 1
    ok = not bool(leftover)
    return ok, {
        "id": unit["id"],
        "role": unit.get("role"),
        "pages": sorted({r["page"] for r in unit.get("regions", [])}),
        "font_size": round(fs, 3),
        "base_font_size": round(sum(float(r.get("font_size", 8.0)) for r in unit["regions"]) / max(1, len(unit["regions"])), 3),
        "inserted_lines": inserted_lines,
        "leftover": leftover,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pdf")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-scale", type=float, default=0.72)
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    input_pdf = Path(args.input_pdf).resolve()
    wd = Path(args.workdir).resolve()
    out = Path(args.output).resolve()
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

    doc = fitz.open(input_pdf)
    redaction_counts = add_redactions(doc, units, translations)
    overflow = []
    details = []
    applied = 0
    for u in units:
        tr = translations.get(u["id"])
        if not tr:
            continue
        ok, info = render_unit(doc, u, tr, reg_font, bold_font, reg_metrics, bold_metrics, args.min_scale)
        details.append(info)
        if ok:
            applied += 1
        else:
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
        "engine_version": 2,
        "output": str(out),
        "units": len(units),
        "translated": len(units) - len(missing),
        "applied": applied,
        "missing": len(missing),
        "overflow": len(overflow),
        "redaction_pages": len(redaction_counts),
        "font_subsetting": bool(reg_subset and bold_subset),
        "output_bytes": out.stat().st_size,
        "source_bytes": input_pdf.stat().st_size,
        "size_ratio": round(out.stat().st_size / max(1, input_pdf.stat().st_size), 3),
        "overflow_items": overflow,
        "details": details,
    }
    (wd / "apply_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if overflow:
        repair = {
            "instructions": "Rewrite only these paragraph translations more compactly. Preserve every technical claim, number, unit, acronym/model name, and citation. Do not split a paragraph into line fragments.",
            "items": [{"id": x["id"], "source": x["source"], "translation": x["translation"]} for x in overflow],
        }
        (wd / "repair_batch.json").write_text(json.dumps(repair, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"details", "overflow_items"}}, ensure_ascii=False, indent=2))
    return 0 if not overflow else 3


if __name__ == "__main__":
    raise SystemExit(main())
