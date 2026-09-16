#!/usr/bin/env python3
"""Create an optional bilingual PDF from original and translated PDFs."""
from __future__ import annotations

import argparse
from pathlib import Path
import fitz


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("original_pdf")
    ap.add_argument("translated_pdf")
    ap.add_argument("--output", required=True)
    ap.add_argument("--layout", choices=["alternating", "side-by-side"], default="alternating")
    ap.add_argument("--gap", type=float, default=12.0)
    args = ap.parse_args()

    orig = fitz.open(args.original_pdf)
    trans = fitz.open(args.translated_pdf)
    if len(orig) != len(trans):
        raise SystemExit("Original and translated PDFs must have the same page count.")
    out = fitz.open()
    if args.layout == "alternating":
        for i in range(len(orig)):
            out.insert_pdf(orig, from_page=i, to_page=i)
            out.insert_pdf(trans, from_page=i, to_page=i)
    else:
        for i in range(len(orig)):
            ro = orig[i].rect
            rt = trans[i].rect
            h = max(ro.height, rt.height)
            page = out.new_page(width=ro.width + args.gap + rt.width, height=h)
            page.show_pdf_page(fitz.Rect(0, 0, ro.width, ro.height), orig, i)
            page.show_pdf_page(fitz.Rect(ro.width + args.gap, 0, ro.width + args.gap + rt.width, rt.height), trans, i)
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, garbage=4, deflate=True)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
