#!/usr/bin/env python3
"""Prepare paragraph-aware translation units from a born-digital academic PDF.

V2 deliberately uses the PDF content-stream order (sort=False), reconstructs prose
paragraphs across line / block / column / page fragments, and emits one model-facing
item per semantic unit instead of one item per visual line. Display equations and
bibliographic references are protected by default.

This script performs no network access and no translation.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import statistics
from pathlib import Path
from typing import Iterable

import fitz

MATH_FONT_RE = re.compile(r"(?:math|symbol|cmsy|cmex|cmmi|tex_cm_math|stix|cambria math)", re.I)
URL_RE = re.compile(r"(?:https?://|www\.|\bdoi\b|@)[^\s]+", re.I)
SECTION_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+|abstract\s*$|keywords?\s*:|nomenclature\s*:|"
    r"introduction\s*$|conclusions?\s*$|discussion\s*$|methodology\s*$|methods?\s*$|"
    r"results?(?:\s+and\s+discussion)?\s*$|references\s*$|bibliography\s*$)", re.I
)
CAPTION_RE = re.compile(r"^\s*(?:fig\.?|figure|table|图|表)\s*\d+", re.I)
BULLET_RE = re.compile(r"^\s*(?:[•●▪◦‣]|[-–—]\s+|\([a-z0-9]+\)\s+|[a-z]\)\s+)", re.I)
REF_HEADINGS = {"references", "bibliography", "参考文献"}
AFFIL_RE = re.compile(r"\b(?:university|univ\.?|school|institute|department|laboratory|college|academy)\b", re.I)


def norm_text(s: str) -> str:
    s = s.replace("\u00ad", "-").replace("\u200b", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"\s+", " ", s).strip()


def alpha_ratio(s: str) -> float:
    visible = [ch for ch in s if not ch.isspace()]
    return sum(ch.isalpha() for ch in visible) / max(1, len(visible))


def line_text(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def dehyphen_join(parts: Iterable[str]) -> str:
    out = ""
    for raw in parts:
        t = norm_text(raw)
        if not t:
            continue
        if not out:
            out = t
            continue
        # PDF line-break hyphenation: tem- + perature -> temperature.
        if out.endswith("-") and t[:1].islower():
            out = out[:-1] + t
        else:
            out += " " + t
    return norm_text(out)


def color_int_to_rgb(value: int) -> list[float]:
    return [round(((value >> shift) & 255) / 255, 4) for shift in (16, 8, 0)]


def looks_like_nontranslatable(text: str) -> bool:
    t = norm_text(text)
    if not t:
        return True
    if URL_RE.search(t):
        return True
    if re.fullmatch(r"[\d\s.,;:/%+\-−–—()\[\]{}]+", t):
        return True
    return False


def line_math_score(line: dict) -> float:
    spans = line.get("spans", [])
    if not spans:
        return 1.0
    total = 0
    weighted = 0.0
    for span in spans:
        t = norm_text(span.get("text", ""))
        n = max(1, len(t))
        total += n
        font = span.get("font", "")
        score = 0.0
        if MATH_FONT_RE.search(font):
            score += 0.8
        if alpha_ratio(t) < 0.25:
            score += 0.35
        if re.search(r"[∑∫√≈≠≤≥∞∂∇θλγΩσμδπ×÷]", t):
            score += 0.65
        weighted += min(1.0, score) * n
    return weighted / max(1, total)


def is_display_math(line: dict) -> bool:
    t = norm_text(line_text(line))
    if not t:
        return True
    score = line_math_score(line)
    words = re.findall(r"[A-Za-z]{3,}", t)
    equationish = bool(re.search(r"(?:=|∑|∫|√|\b(?:obj|err|MOP|MOA)\b)", t))
    if score >= 0.64 and len(words) <= 4:
        return True
    if equationish and alpha_ratio(t) < 0.45 and len(t) < 180:
        return True
    return False


def median_body_size(doc: fitz.Document) -> float:
    sizes: list[float] = []
    for page in doc:
        data = page.get_text("dict", sort=False)
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = norm_text(span.get("text", ""))
                    if len(t) >= 15 and alpha_ratio(t) > 0.45 and not MATH_FONT_RE.search(span.get("font", "")):
                        sizes.append(float(span.get("size", 8.0)))
    return statistics.median(sizes) if sizes else 8.0


def collect_repeated_margin_lines(doc: fitz.Document) -> set[str]:
    pages_seen: dict[str, set[int]] = collections.defaultdict(set)
    for pno, page in enumerate(doc):
        ph = page.rect.height
        data = page.get_text("dict", sort=False)
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                t = norm_text(line_text(line))
                if not t:
                    continue
                y0, y1 = line["bbox"][1], line["bbox"][3]
                if y1 < ph * 0.08 or y0 > ph * 0.92:
                    pages_seen[t.lower()].add(pno)
    threshold = max(3, math.ceil(len(doc) * 0.28))
    return {k for k, seen in pages_seen.items() if len(seen) >= threshold}


def line_font_size(line: dict, fallback: float) -> float:
    sizes = [float(s.get("size", fallback)) for s in line.get("spans", []) if norm_text(s.get("text", ""))]
    return statistics.median(sizes) if sizes else fallback


def line_color(line: dict) -> list[float]:
    spans = [s for s in line.get("spans", []) if norm_text(s.get("text", ""))]
    if not spans:
        return [0.0, 0.0, 0.0]
    # Prefer the longest span's color.
    s = max(spans, key=lambda x: len(norm_text(x.get("text", ""))))
    return color_int_to_rgb(int(s.get("color", 0)))


def guess_role(page_index: int, text: str, fs: float, body_size: float, y0: float, page_h: float) -> str:
    t = norm_text(text)
    low = t.lower().rstrip(":")
    if CAPTION_RE.match(t):
        return "caption"
    spaced = re.sub(r"[^A-Za-z]", "", t)
    if spaced.upper() in {"ABSTRACT", "ARTICLEINFO"} and len(spaced) >= 8:
        return "heading"
    if SECTION_RE.match(t) and len(t) < 130:
        if low.startswith("keywords"):
            return "keywords_heading"
        return "heading"
    if page_index == 0 and fs >= max(body_size * 1.45, 11.0) and y0 < page_h * 0.4:
        return "title"
    # Generic font-size-only heading detection is intentionally conservative: a
    # citation/symbol span can inflate the median size of an ordinary body line.
    if fs >= body_size * 1.42 and len(t) < 80 and len(t.split()) <= 10:
        return "heading"
    return "body"


def first_page_protected(page_index: int, text: str, y0: float, y1: float, page_h: float) -> bool:
    if page_index != 0:
        return False
    t = norm_text(text)
    if "corresponding author" in t.lower() or t.lower().startswith("e-mail address"):
        return True
    # Publisher masthead / journal navigation.
    if y1 < page_h * 0.18:
        return True
    # Author / affiliation rows are fragile and normally remain in the original language.
    if page_h * 0.25 <= y0 <= page_h * 0.33:
        if AFFIL_RE.search(t) or "*" in t or re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", t):
            return True
    # DOI and publication metadata footer.
    if y0 > page_h * 0.84 and (URL_RE.search(t) or t.lower().startswith(("received", "available online", "0957-"))):
        return True
    return False


def x_cluster_count(values: list[float], tol: float = 8.0) -> int:
    clusters: list[float] = []
    for x in sorted(values):
        if not clusters or abs(x - clusters[-1]) > tol:
            clusters.append(x)
        else:
            clusters[-1] = (clusters[-1] + x) / 2
    return len(clusters)


def is_table_like(lines: list[dict], page_w: float) -> bool:
    if len(lines) < 4:
        return False
    ys = [round(float(l["bbox"][1])) for l in lines]
    duplicate_y = len(lines) - len(set(ys))
    xs = [float(l["bbox"][0]) for l in lines]
    xclusters = x_cluster_count(xs)
    widths = [float(l["bbox"][2]) - float(l["bbox"][0]) for l in lines]
    median_chars = statistics.median(len(norm_text(line_text(l))) for l in lines)
    span_gap_rows = 0
    for line in lines:
        spans = [s for s in line.get("spans", []) if norm_text(s.get("text", ""))]
        for a, b in zip(spans, spans[1:]):
            if b["bbox"][0] - a["bbox"][2] > 12:
                span_gap_rows += 1
                break
    if duplicate_y >= max(2, int(0.14 * len(lines))) and xclusters >= 2:
        return True
    if xclusters >= 4 and median_chars < 28 and statistics.median(widths) < page_w * 0.38:
        return True
    if span_gap_rows >= max(2, int(0.25 * len(lines))):
        return True
    return False


def split_table_line(line: dict, body_size: float) -> list[dict]:
    spans = [s for s in line.get("spans", []) if norm_text(s.get("text", ""))]
    if not spans:
        return []
    groups: list[list[dict]] = [[spans[0]]]
    for span in spans[1:]:
        prev = groups[-1][-1]
        fs = statistics.median([float(prev.get("size", body_size)), float(span.get("size", body_size))])
        if float(span["bbox"][0]) - float(prev["bbox"][2]) > max(7.0, fs * 1.7):
            groups.append([span])
        else:
            groups[-1].append(span)
    out = []
    for group in groups:
        source = norm_text("".join(s.get("text", "") for s in group))
        if not source or looks_like_nontranslatable(source) or alpha_ratio(source) < 0.16:
            continue
        rect = fitz.Rect(group[0]["bbox"])
        for s in group[1:]:
            rect |= fitz.Rect(s["bbox"])
        out.append({
            "lines": [line],
            "source": source,
            "bbox": list(rect),
            "font_size": statistics.median(float(s.get("size", body_size)) for s in group),
            "color": color_int_to_rgb(int(max(group, key=lambda s: len(norm_text(s.get("text", "")))).get("color", 0))),
            "first_indent": False,
            "role": "table_cell",
            "starts_bullet": False,
        })
    return out


def split_prose_block(lines: list[dict], page_index: int, body_size: float, page_h: float) -> list[dict]:
    if not lines:
        return []
    base_x0 = min(float(l["bbox"][0]) for l in lines)
    ystarts = [float(l["bbox"][1]) for l in lines]
    gaps = [b - a for a, b in zip(ystarts, ystarts[1:]) if 3 < b - a < 40]
    pitch = statistics.median(gaps) if gaps else body_size * 1.30
    segments: list[dict] = []
    current: list[dict] = []
    current_role = "body"
    current_bullet = False

    def flush() -> None:
        nonlocal current, current_role, current_bullet
        if not current:
            return
        source = dehyphen_join(line_text(l) for l in current)
        if source and not looks_like_nontranslatable(source) and alpha_ratio(source) >= 0.18:
            rect = fitz.Rect(current[0]["bbox"])
            for l in current[1:]:
                rect |= fitz.Rect(l["bbox"])
            fs = statistics.median(line_font_size(l, body_size) for l in current)
            first_x = float(current[0]["bbox"][0])
            indent = max(0.0, first_x - min(float(l["bbox"][0]) for l in current))
            local_ys = [float(l["bbox"][1]) for l in current]
            local_gaps = [b - a for a, b in zip(local_ys, local_ys[1:]) if 3 < b - a < 40]
            local_pitch = statistics.median(local_gaps) if local_gaps else pitch
            segments.append({
                "lines": list(current),
                "source": source,
                "bbox": list(rect),
                "font_size": fs,
                "line_pitch": local_pitch,
                "color": line_color(max(current, key=lambda l: len(norm_text(line_text(l))))),
                "first_indent": indent > max(3.0, fs * 0.55),
                "indent_pt": round(indent, 2),
                "role": current_role,
                "starts_bullet": current_bullet,
            })
        current = []
        current_role = "body"
        current_bullet = False

    for idx, line in enumerate(lines):
        t = norm_text(line_text(line))
        if not t:
            continue
        fs = line_font_size(line, body_size)
        role = guess_role(page_index, t, fs, body_size, float(line["bbox"][1]), page_h)
        if is_display_math(line):
            flush()
            continue
        starts_bullet = bool(BULLET_RE.match(t))
        indented = float(line["bbox"][0]) > base_x0 + max(4.0, fs * 0.75)
        gap_break = False
        if current:
            gap = float(line["bbox"][1]) - float(current[-1]["bbox"][1])
            gap_break = gap > max(pitch * 1.65, fs * 1.9)
        special = role in {"title", "heading", "caption", "keywords_heading"}
        current_special = current_role in {"title", "heading", "caption", "keywords_heading"}

        should_break = False
        if current:
            if starts_bullet:
                should_break = True
            elif special != current_special or (special and role != current_role):
                should_break = True
            elif gap_break:
                should_break = True
            elif indented and not current_bullet and role == "body":
                should_break = True
        if should_break:
            flush()
        if not current:
            current_role = role
            current_bullet = starts_bullet
        current.append(line)
        # Headings/captions should not absorb the next body line, but allow a multi-line title/caption.
        if special and idx + 1 < len(lines):
            nxt = lines[idx + 1]
            nt = norm_text(line_text(nxt))
            nfs = line_font_size(nxt, body_size)
            nrole = guess_role(page_index, nt, nfs, body_size, float(nxt["bbox"][1]), page_h)
            if nrole != role and role != "title":
                flush()
    flush()
    return segments


def region_from_segment(seg: dict, page_no: int, page_rect: fitz.Rect) -> dict:
    lines = seg["lines"]
    bbox = fitz.Rect(seg["bbox"]) & page_rect
    reds = []
    for line in lines:
        r = fitz.Rect(line["bbox"])
        # Small horizontal/vertical padding removes antialiased source glyph fringes.
        r = fitz.Rect(r.x0 - 0.25, r.y0 - 0.10, r.x1 + 0.25, r.y1 + 0.10) & page_rect
        reds.append([round(v, 3) for v in r])
    return {
        "page": page_no,
        "bbox": [round(v, 3) for v in bbox],
        "redactions": reds,
        "line_count": max(1, len(lines)),
        "font_size": round(float(seg.get("font_size", 8.0)), 3),
        "line_pitch": round(float(seg.get("line_pitch", float(seg.get("font_size", 8.0)) * 1.3)), 3),
        "color": seg.get("color", [0, 0, 0]),
        "first_indent": bool(seg.get("first_indent", False)),
        "indent_pt": round(float(seg.get("indent_pt", 0.0)), 2),
    }


def can_flow_merge(prev: dict, cur: dict, page_rects: dict[int, list[float]]) -> bool:
    if prev.get("role") != "body" or cur.get("role") != "body":
        return False
    if prev.get("starts_bullet") or cur.get("starts_bullet") or cur.get("first_indent"):
        return False
    pr = prev["regions"][-1]
    cr = cur["regions"][0]
    pp, cp = pr["page"], cr["page"]
    pbox, cbox = pr["bbox"], cr["bbox"]
    if cp < pp or cp > pp + 1:
        return False
    if pp == cp:
        same_column = abs(float(pbox[0]) - float(cbox[0])) < 24
        if same_column:
            gap = float(cbox[1]) - float(pbox[3])
            return -2 <= gap <= max(20.0, float(pr["line_pitch"]) * 2.0)
        ph = page_rects[pp][3] - page_rects[pp][1]
        # Content-stream column continuation: prior fragment ends low on the page.
        return float(pbox[3]) > ph * 0.76
    # Page continuation: prior fragment ends low or current starts near the body top.
    ph = page_rects[pp][3] - page_rects[pp][1]
    ch = page_rects[cp][3] - page_rects[cp][1]
    return float(pbox[3]) > ph * 0.72 or float(cbox[1]) < ch * 0.34


def hard_tokens(text: str) -> list[str]:
    tokens = []
    patterns = [
        r"\b\d+(?:\.\d+)?\s*%",
        r"\b\d+(?:\.\d+)?\b",
        r"\b[A-Z][A-Z0-9]{1,8}\b",
        r"\b(?:CatBoost|XGBoost|LightGBM|ARIMA|SARIMA|SARFIMA|Prophet)\b",
        r"\([^()]{0,80}\b(?:19|20)\d{2}[a-z]?[^()]{0,20}\)",
    ]
    for pat in patterns:
        tokens.extend(re.findall(pat, text))
    seen = set()
    return [x for x in tokens if not (x in seen or seen.add(x))]


def extract_units(doc: fitz.Document, translate_references: bool) -> tuple[list[dict], list[str], float]:
    body_size = median_body_size(doc)
    repeated = collect_repeated_margin_lines(doc)
    page_rects = {i + 1: [float(v) for v in page.rect] for i, page in enumerate(doc)}
    candidates: list[dict] = []
    warnings: list[str] = []
    in_references = False
    scan_like_pages = 0

    for pno, page in enumerate(doc):
        data = page.get_text("dict", sort=False)
        chars = sum(len(span.get("text", "")) for b in data.get("blocks", []) if b.get("type") == 0 for l in b.get("lines", []) for span in l.get("spans", []))
        if chars < 40:
            scan_like_pages += 1
        for bidx, block in enumerate(data.get("blocks", [])):
            if block.get("type") != 0:
                continue
            raw_lines = [l for l in block.get("lines", []) if norm_text(line_text(l))]
            lines: list[dict] = []
            for line in raw_lines:
                t = norm_text(line_text(line))
                y0, y1 = float(line["bbox"][1]), float(line["bbox"][3])
                if t.lower() in repeated:
                    continue
                if re.fullmatch(r"\d{1,4}", t) and y0 > page.rect.height * 0.88:
                    continue
                if first_page_protected(pno, t, y0, y1, page.rect.height):
                    continue
                lines.append(line)
            if not lines:
                continue

            first_text = norm_text(line_text(lines[0]))
            if first_text.lower().rstrip(":") in REF_HEADINGS:
                # Keep the heading itself; preserve reference entries by default.
                pass
            elif in_references and not translate_references:
                continue

            if first_text.lower().startswith("keywords") and len(lines) > 1:
                # Keep the label in its original narrow box, but translate the keyword
                # list as one semantic list with explicit separators instead of a fake sentence.
                head = split_prose_block([lines[0]], pno, body_size, page.rect.height)
                rest = split_prose_block(lines[1:], pno, body_size, page.rect.height)
                if rest:
                    rest[0]["source"] = "; ".join(norm_text(line_text(l)) for l in lines[1:] if norm_text(line_text(l)))
                    rest[0]["role"] = "keywords"
                    rest = rest[:1]
                segs = head + rest
            elif is_table_like(lines, page.rect.width):
                segs = []
                for line in lines:
                    if is_display_math(line):
                        continue
                    segs.extend(split_table_line(line, body_size))
            else:
                segs = split_prose_block(lines, pno, body_size, page.rect.height)

            for sidx, seg in enumerate(segs):
                src = norm_text(seg.get("source", ""))
                if not src:
                    continue
                if src.lower().rstrip(":") in REF_HEADINGS:
                    seg["role"] = "heading"
                reg = region_from_segment(seg, pno + 1, page.rect)
                candidates.append({
                    "page": pno + 1,
                    "block": bidx,
                    "segment": sidx,
                    "role": seg.get("role", "body"),
                    "source": src,
                    "regions": [reg],
                    "starts_bullet": bool(seg.get("starts_bullet", False)),
                    "first_indent": bool(seg.get("first_indent", False)),
                })
            if any(norm_text(line_text(l)).lower().rstrip(":") in REF_HEADINGS for l in lines):
                in_references = True

    units: list[dict] = []
    for cand in candidates:
        if units and can_flow_merge(units[-1], cand, page_rects):
            units[-1]["source"] = dehyphen_join([units[-1]["source"], cand["source"]])
            units[-1]["regions"].extend(cand["regions"])
            units[-1]["last_page"] = cand["page"]
        else:
            units.append(cand)
            units[-1]["last_page"] = cand["page"]

    for idx, u in enumerate(units):
        u["id"] = f"u{idx:04d}"
        u["hard_tokens"] = hard_tokens(u["source"])
        u.pop("first_indent", None)
        # Context is intentionally short and model-facing, not used for rendering.
        if idx:
            u["prev_tail"] = units[idx - 1]["source"][-280:]
        else:
            u["prev_tail"] = ""
        if idx + 1 < len(units):
            u["next_head"] = units[idx + 1]["source"][:280]
        else:
            u["next_head"] = ""

    if scan_like_pages:
        warnings.append(f"{scan_like_pages} page(s) contain very little extractable text; OCR may be required.")
    return units, warnings, body_size


def write_batches(units: list[dict], workdir: Path, lang_in: str, lang_out: str, max_chars: int) -> list[str]:
    batchdir = workdir / "batches"
    batchdir.mkdir(parents=True, exist_ok=True)
    for old in batchdir.glob("batch_*.json"):
        old.unlink()
    batches: list[list[dict]] = []
    cur: list[dict] = []
    chars = 0
    for u in units:
        model_item = {
            "id": u["id"],
            "role": u["role"],
            "source": u["source"],
            "prev_tail": u.get("prev_tail", ""),
            "next_head": u.get("next_head", ""),
            "hard_tokens": u.get("hard_tokens", []),
        }
        n = len(u["source"])
        if cur and chars + n > max_chars:
            batches.append(cur)
            cur = []
            chars = 0
        cur.append(model_item)
        chars += n
    if cur:
        batches.append(cur)
    names = []
    for i, items in enumerate(batches):
        name = f"batch_{i:03d}.json"
        obj = {
            "source_language": lang_in,
            "target_language": lang_out,
            "instructions": "Translate every item as one coherent semantic unit. Do not split or redistribute by PDF line. Preserve hard_tokens exactly when they are lexical/numeric tokens from the paper.",
            "items": items,
        }
        (batchdir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        names.append(name)
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_pdf")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--lang-in", default="en")
    ap.add_argument("--lang-out", default="zh-CN")
    ap.add_argument("--max-batch-chars", type=int, default=6500)
    ap.add_argument("--translate-references", action="store_true")
    args = ap.parse_args()

    pdf = Path(args.input_pdf).resolve()
    wd = Path(args.workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "translated").mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    units, warnings, body_size = extract_units(doc, args.translate_references)
    with (wd / "units.jsonl").open("w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    batch_names = write_batches(units, wd, args.lang_in, args.lang_out, args.max_batch_chars)
    manifest = {
        "engine_version": 2,
        "input_pdf": str(pdf),
        "page_count": len(doc),
        "page_sizes": [[round(float(p.rect.width), 3), round(float(p.rect.height), 3)] for p in doc],
        "body_font_size": round(body_size, 3),
        "translation_units": len(units),
        "batches": batch_names,
        "source_language": args.lang_in,
        "target_language": args.lang_out,
        "translate_references": bool(args.translate_references),
        "warnings": warnings,
    }
    (wd / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    gloss = wd / "translation_glossary.json"
    if not gloss.exists():
        gloss.write_text(json.dumps({"terms": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
