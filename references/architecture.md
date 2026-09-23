# Architecture and rationale - V3.1

## Why V3 still needed a workflow change

V3 fixed the main geometry mechanics: wrap-around paragraphs could use source-line slots, image zones were protected, CJK density was adapted, and font glyph IDs were retained. However, the user-facing workflow could still behave as if layout correctness were mainly established after translation and rendering: a translation was produced, inserted, and then QA confirmed whether it overlapped.

That order wastes work and makes collision handling feel reactive even when the renderer has safety guards.

## V3.1 principle: freeze layout before language generation

V3.1 separates the pipeline into three contracts:

1. **semantic contract** - what text belongs together and in what reading order;
2. **layout contract** - exactly where target text may be written and how much target-language capacity exists;
3. **linguistic contract** - accurate paragraph translation constrained by the already-approved layout budget.

Translation starts only after the layout contract passes.

## Stage A - semantic/source geometry extraction

`prepare.py` reconstructs paragraphs, captions, headings and table cells while recording source line geometry, image exclusions, font scale and semantic context. It deliberately emits no translation batches.

## Stage B - pre-translation layout preflight

`layout_preflight.py` is the new hard gate. It:

- validates all bboxes against page geometry;
- rejects rectangular flow boxes that cross protected images;
- validates slot geometry against exclusions;
- freezes the final plan into `units_planned.jsonl`;
- estimates CJK capacity at preferred/minimum font sizes;
- produces `layout_plan.json` and an annotated `layout_preflight.pdf`;
- creates translation batches only when the plan is `PASS`.

This turns figure avoidance from a post-render repair into a pre-translation invariant.

## Stage C - layout-aware translation

Each batch item contains a compact `layout_budget`: comfortable CJK character capacity, hard spatial warning, preferred/minimum target font sizes, and risk class. The active ChatGPT/Work model can therefore choose concise natural Chinese on the first pass without seeing or manipulating raw PDF coordinates.

The budget is advisory for wording, not a license to truncate scientific content.

## Stage D - pre-render fit gate

Before redacting the source PDF, `apply.py` flows every finished translation through the frozen plan using the real target font metrics. If any paragraph cannot fit or hits an exclusion, the script writes a repair batch and exits without mutating/rendering the PDF.

Only a fully fitting translation set reaches the redaction/render stage.

## Rendering and final QA

Rendering keeps the V3 behavior: text-only redaction, flow/slot insertion, bounded CJK typography, retained glyph IDs and invariant collision checks. `qa.py` and full-page previews remain mandatory because PDF rendering is complex, but they are now confirmation stages rather than the normal first detection of geometric conflicts.

## Figure-label policy

Raster figure-internal labels remain untouched by default. They are outside the body-text layout contract and require an explicit figure-label translation path when requested.

## Model boundary

No local script invokes an external translation API. Deterministic scripts establish and enforce geometry; the active ChatGPT/Work session performs linguistic translation after the layout contract is approved.

## Current limits

- Best on born-digital PDFs with extractable text; scans require OCR.
- Pure-vector diagrams without a raster bounding image can still require conservative slot segmentation and visual inspection.
- A capacity budget is an estimate; the exact pre-render fit gate is authoritative.
- Highly irregular editorial/magazine layouts may require page-specific repair.
- Exact proprietary source fonts are not guaranteed.

## Upstream design references

- Zotero integration: https://github.com/guaguastandup/zotero-pdf2zh
- PDFMathTranslate Next: https://github.com/PDFMathTranslate/PDFMathTranslate-next
- BabelDOC translator implementation notes: https://github.com/funstory-ai/BabelDOC/blob/main/docs/ImplementationDetails/ILTranslator/ILTranslator.md
