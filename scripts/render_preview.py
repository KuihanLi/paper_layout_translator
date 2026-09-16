#!/usr/bin/env python3
"""Render selected PDF pages to PNG and optionally create a contact sheet."""
from __future__ import annotations

import argparse
from pathlib import Path

import fitz
from PIL import Image, ImageOps, ImageDraw


def parse_pages(spec: str, total: int) -> list[int]:
    if spec == "all":
        return list(range(1, total + 1))
    if spec == "auto":
        candidates = [1, 2, max(1, total // 2), total]
        return sorted(set(x for x in candidates if 1 <= x <= total))
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(set(x for x in pages if 1 <= x <= total))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pages", default="auto")
    ap.add_argument("--dpi", type=int, default=160)
    ap.add_argument("--contact-sheet", action="store_true")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    pages = parse_pages(args.pages, len(doc))
    rendered = []
    scale = args.dpi / 72.0
    for pno in pages:
        page = doc[pno - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        path = outdir / f"page-{pno:03d}.png"
        pix.save(path)
        rendered.append((pno, path))
        print(path)
    if args.contact_sheet and rendered:
        imgs = []
        max_w = 0
        for pno, path in rendered:
            img = Image.open(path).convert("RGB")
            target_w = min(850, img.width)
            target_h = int(img.height * target_w / img.width)
            img = img.resize((target_w, target_h))
            canvas = Image.new("RGB", (target_w + 20, target_h + 50), "white")
            canvas.paste(img, (10, 35))
            ImageDraw.Draw(canvas).text((10, 10), f"Page {pno}", fill="black")
            imgs.append(canvas)
            max_w = max(max_w, canvas.width)
        total_h = sum(i.height for i in imgs)
        sheet = Image.new("RGB", (max_w, total_h), "white")
        y = 0
        for img in imgs:
            sheet.paste(img, (0, y))
            y += img.height
        sheet_path = outdir / "contact-sheet.jpg"
        sheet.save(sheet_path, quality=88)
        print(sheet_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
