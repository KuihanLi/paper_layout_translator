---
name: paper-layout-translator
description: Translate born-digital academic PDF papers while preserving page count, columns, figures, equations, tables, backgrounds, captions, and overall geometry. Use when a user wants a PDF2zh/BabelDOC-like full-text translation without configuring an external LLM API. The active ChatGPT/Work session performs paragraph translation; deterministic local scripts first build and validate safe target-language layout regions and capacity budgets, then render only after a pre-render fit gate passes.
---

# Paper Layout Translator

**Build identity:** `V3.1.0`

Use the V3.1 pipeline: **inspect -> reconstruct semantic units -> preflight final writable regions + CJK capacity -> translate against the approved layout budget -> validate -> pre-render fit gate -> text-only replacement -> structural QA -> full-page visual QA**.

Never call an external LLM or machine-translation API from the bundled scripts.

## Core rules

- Translate coherent paragraphs / semantic units, never ordinary PDF lines one by one.
- Treat semantic reconstruction and layout reconstruction as separate models.
- **Finish layout planning before linguistic translation starts.** Post-render collision detection is only a final assertion, not the primary repair strategy.
- Use PDF content-stream order (`sort=False`) for semantic order.
- Preserve display equations, figures, charts, vector graphics, backgrounds, annotations, page count, and page geometry.
- Preserve raster figure-internal text by default; translate it only when explicitly requested.
- Remove source glyphs with text-only redaction; never paint white cover rectangles.
- Preserve numbers, units, citations, models/datasets, formulas, and uncertainty.
- Treat unsafe geometry, unresolved overflow, image/text collision, clipped text, and broken CJK glyphs as hard failures.
- Keep `translation_run_log.json`, `layout_plan.json`, and QA reports when the result is being used to improve this Skill.
- Read `references/translation_policy.md` before translation and `references/layout_policy.md` before layout preflight/rendering.

## 1. Inspect the source

Resolve the real PDF path and create a work directory:

```bash
WORKDIR=/mnt/data/<paper-stem>_layout_translation
mkdir -p "$WORKDIR"
python scripts/render_preview.py "$INPUT_PDF" --outdir "$WORKDIR/original_preview" --pages auto --dpi 160 --contact-sheet
```

Inspect columns, wrap-around figures, equations, tables, figure-internal text, shaded regions, rotated text, and scan-like pages.

## 2. Reconstruct semantics and source geometry

```bash
python scripts/prepare.py "$INPUT_PDF" --workdir "$WORKDIR" --lang-out zh-CN
```

Add `--translate-references` only when requested. Add `--translate-figure-text` only when figure-internal labels must be translated.

`prepare.py` now **does not emit translation batches**. It creates semantic units and raw geometry only. Starting translation before the next step is a workflow error.

Outputs include:

- `units.jsonl` - semantic units plus source regions/line slots/exclusions;
- `manifest.json` - page geometry and extraction status;
- `translation_glossary.json`.

## 3. Hard-gate the final writable layout before translation

```bash
python scripts/layout_preflight.py --workdir "$WORKDIR"
```

This stage must finish with `status: PASS` before any batch is translated. It:

- validates every translatable region against page bounds and figure exclusion zones;
- rejects a rectangular `flow` region that crosses an image instead of discovering the collision after rendering;
- freezes `flow` versus `slots` geometry into `units_planned.jsonl`;
- estimates preferred/minimum CJK font sizes and safe target-language capacities;
- adds a soft/hard layout budget to each model item;
- writes `layout_plan.json` and only then creates `batches/batch_XXX.json`;
- writes `layout_preflight.pdf` showing safe regions and exclusion zones.

Render the preflight plan before translating:

```bash
python scripts/render_preview.py "$WORKDIR/layout_preflight.pdf" --outdir "$WORKDIR/layout_preflight_preview" --pages auto --dpi 130 --contact-sheet
```

Inspect the risk pages listed in `layout_plan.json`. If safe regions are wrong, fix/re-run preparation now; do not translate first and hope QA catches it later.

## 4. Translate against the approved layout budget

Process the generated batches in numeric order. Every item includes `layout_budget`.

For each item:

1. Translate the entire `source` as one coherent semantic unit.
2. Ignore original visual line breaks.
3. Preserve `hard_tokens` and scientific meaning.
4. Aim for concise natural academic Chinese within `soft_cjk_chars` when possible.
5. Treat `hard_cjk_chars` as a spatial warning, **not permission to omit meaning**. If a faithful translation needs more space, keep the meaning; the pre-render fit gate will request a compact repair before touching the PDF.
6. Keep terminology stable in `translation_glossary.json`.

Do not expose batch JSON to the user unless requested.

## 5. Validate translation completeness

```bash
python scripts/validate.py --workdir "$WORKDIR" --strict --write-merged
python scripts/validate.py --workdir "$WORKDIR" --strict --strict-tokens --write-merged
```

Resolve missing IDs and material token warnings.

## 6. Apply only after the pre-render fit gate passes

```bash
python scripts/apply.py "$INPUT_PDF" --workdir "$WORKDIR" --output "$WORKDIR/<paper-stem>_translated.pdf"
```

Before opening the source PDF for mutation, `apply.py` reflows every completed translation through the already-approved regions. If any item overflows or violates an exclusion, it writes `translation_fit_report.json` / `repair_batch.json` and exits **without redacting or rendering a PDF**.

Only when this gate passes does it:

- remove source text with text-only redaction;
- render regular prose inside approved `flow` regions;
- render irregular/wrap-around prose through approved source-line `slots`;
- adapt CJK font size/leading within bounded limits;
- retain CJK glyph IDs during font subsetting;
- keep collision detection as a final invariant check.

Do not deliver when `overflow > 0` or `collision_guard_failures > 0`.

## 7. Structural QA

```bash
python scripts/qa.py "$INPUT_PDF" "$WORKDIR/<paper-stem>_translated.pdf" --workdir "$WORKDIR"
```

Require zero structural failures. Check page geometry, image preservation, CJK rendering, out-of-page text, source residue, and apply reports.

## 8. Full-page visual QA

```bash
python scripts/render_preview.py "$WORKDIR/<paper-stem>_translated.pdf" --outdir "$WORKDIR/final_preview" --pages all --dpi 130 --contact-sheet
```

Inspect every page for text/figure overlap, clipping, broken glyphs, column violations, preserved diagrams/equations/backgrounds, hierarchy, and visually appropriate Chinese density. Use a second renderer for complex pages when available.

Visual QA remains mandatory, but it verifies an already-constrained layout rather than serving as the first place overlap is discovered.

## 9. Optional bilingual PDF

After the monolingual PDF passes QA:

```bash
python scripts/make_dual.py "$INPUT_PDF" "$WORKDIR/<paper-stem>_translated.pdf" --output "$WORKDIR/<paper-stem>_dual.pdf" --layout alternating
```

Use side-by-side only when requested because it changes page dimensions.

## 10. Regression check after Skill changes

```bash
python scripts/self_test.py
```

Tests cover CJK subset rendering, line-slot safety, vertical fit, pre-translation layout-contract validation, and the pre-render fit gate.

## Script map

- `scripts/prepare.py` - reconstruct semantics and raw source geometry; does not emit translation batches.
- `scripts/layout_preflight.py` - freeze safe writable regions, estimate CJK budgets, generate layout preview, then emit translation batches.
- `scripts/validate.py` - verify translation completeness/protected tokens.
- `scripts/apply.py` - pre-render fit gate followed by text-only replacement using the approved plan.
- `scripts/qa.py` - final structural verification.
- `scripts/render_preview.py` - source/layout/final preview rendering.
- `scripts/make_dual.py` - optional bilingual PDF.
- `scripts/self_test.py` - deterministic local regression tests.

## Model boundary

Local scripts do not call external translation services. The active ChatGPT/Work session performs linguistic translation only after deterministic layout preflight has defined the writable geometry and target-language capacity.
