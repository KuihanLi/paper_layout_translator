---
name: paper-layout-translator
description: Translate born-digital academic PDF papers while preserving the original page count, columns, figures, equations, tables, backgrounds, captions, and overall geometry, without asking the user to configure an external LLM API. Use when a user uploads or links a scientific paper/PDF and asks for Chinese or another-language full-text translation, especially when they want a PDF2zh/BabelDOC-like layout-preserving result, coherent paragraph translation, or an optional bilingual PDF. The scripts perform deterministic local parsing/rendering while the active ChatGPT conversation or Work task itself performs translation, so no third-party translation API key, provider URL, or local LLM setup is required.
---

# Paper Layout Translator

Use the V2 pipeline: **inspect -> reconstruct semantic paragraphs -> translate with the active ChatGPT model -> validate -> remove source glyphs only -> flow translated paragraphs through original regions -> render/QA**.

Never call an external LLM or machine-translation API from the bundled scripts.

## Non-negotiable quality rules

- Translate paragraphs / semantic units, never individual PDF lines for ordinary prose.
- Use the PDF's content-stream order (`sort=False`) so multi-column reading order is not reconstructed only from vertical coordinates.
- Preserve display equations, figures, charts, vector graphics, page backgrounds, annotations, and page geometry.
- Do not paint white rectangles over source text. V2 uses text-only redaction so original backgrounds and graphics survive.
- Keep citations, numbers, units, model names, dataset names, and mathematical meaning intact.
- Preserve bibliographic entries by default; translate the `References` heading but not each reference unless the user asks.
- Complete the workflow autonomously in Work mode. Do not ask the user to configure API keys or manually translate JSON batches.
- Read `references/translation_policy.md` before translating. Read `references/architecture.md` when explaining the design or limitations.

## 1. Resolve and inspect the input PDF

Obtain the real local path. Never invent a sandbox path from a display filename.

Create a dedicated work directory:

```bash
WORKDIR=/mnt/data/<paper-stem>_layout_translation
mkdir -p "$WORKDIR"
```

Render representative source pages first:

```bash
python scripts/render_preview.py "$INPUT_PDF" --outdir "$WORKDIR/original_preview" --pages auto --dpi 160 --contact-sheet
```

Inspect multi-column flow, figures, equations, tables, shaded/colored backgrounds, rotated text, and whether the file has an extractable text layer.

## 2. Prepare paragraph-aware batches

For Chinese:

```bash
python scripts/prepare.py "$INPUT_PDF" --workdir "$WORKDIR" --lang-out zh-CN
```

Add `--translate-references` only when requested.

V2 creates:

- `units.jsonl` - semantic units plus one or more original rendering regions;
- `batches/batch_XXX.json` - compact paragraph-level translation batches;
- `manifest.json` - page geometry and preparation report;
- `translation_glossary.json` - reusable terminology decisions;
- `translated/` - destination for session-generated translations.

If `manifest.json` reports pages with little/no text, use a local OCR workflow first when practical. Do not claim layout-preserving translation of an image-only scan without OCR.

## 3. Translate batches with the active session model

Read `references/translation_policy.md` once. Process batches in numeric order.

For each batch:

1. Read every item's `source`, `role`, `prev_tail`, `next_head`, and `hard_tokens`.
2. Translate the entire `source` as one coherent semantic unit. **Ignore the original PDF's visual line breaks.**
3. Use context only to resolve discourse and references; never repeat it.
4. Keep the translation accurate, natural, and moderately concise so it can fit the original region without dropping meaning.
5. Save exactly:

```json
{
  "items": [
    {"id": "u0005", "translation": "本文旨在……"}
  ]
}
```

6. Update `translation_glossary.json` for stable recurring terminology.

Do not expose batch JSON in user-facing chat unless requested. In Work mode, continue through all batches automatically.

## 4. Validate translation completeness

```bash
python scripts/validate.py --workdir "$WORKDIR" --strict --write-merged
```

For stricter numeric/model/citation preservation checks:

```bash
python scripts/validate.py --workdir "$WORKDIR" --strict --strict-tokens --write-merged
```

Resolve missing IDs or token warnings before final rendering.

## 5. Apply translations without altering backgrounds

```bash
python scripts/apply.py "$INPUT_PDF" --workdir "$WORKDIR" --output "$WORKDIR/<paper-stem>_translated.pdf"
```

Important V2 behavior:

- source glyphs are removed via **text-only redaction**;
- images and vector graphics are preserved;
- one translated paragraph can flow through several original regions/columns/pages;
- line pitch, approximate font scale, text color, and paragraph indentation are retained;
- a dynamically subset local CJK font is embedded, avoiding broken mixed Latin/CJK spacing and excessive file growth.

If `repair_batch.json` is generated, shorten only those translations without removing technical meaning. Save repairs to `translated/batch_repair.json`, rerun validation, then rerun `apply.py`. Do not deliver with overflow remaining.

`--allow-partial` is for smoke tests only, never for a final translation.

## 6. Structural QA

Run:

```bash
python scripts/qa.py "$INPUT_PDF" "$WORKDIR/<paper-stem>_translated.pdf" --workdir "$WORKDIR"
```

For final delivery, failures must be zero. Investigate size-ratio warnings rather than accepting a many-times-larger PDF blindly.

## 7. Render every translated page and inspect visually

```bash
python scripts/render_preview.py "$WORKDIR/<paper-stem>_translated.pdf" --outdir "$WORKDIR/final_preview" --pages all --dpi 130 --contact-sheet
```

Check all of the following:

- paragraph translation reads continuously instead of line fragments;
- translated text stays inside its original column/cell/caption region;
- no clipped/overlapping text, black boxes, broken glyphs, or artificial spaces inside names such as `CatBoost`;
- figures, equations, rules, colored cells, and page backgrounds are unchanged;
- title/abstract/headings/captions/tables retain their visual hierarchy;
- page count and page dimensions match the source exactly;
- `apply_report.json` shows `overflow: 0`;
- output file size remains reasonably close to the source unless the source itself required OCR/raster work.

If a small number of complex pages fail visual QA, repair those pages/units and re-render. Do not describe a visibly damaged result as layout-preserving.

## 8. Optional bilingual PDF

After the monolingual translated PDF passes QA:

```bash
python scripts/make_dual.py "$INPUT_PDF" "$WORKDIR/<paper-stem>_translated.pdf" --output "$WORKDIR/<paper-stem>_dual.pdf" --layout alternating
```

Use `--layout side-by-side` only when requested; it changes page dimensions. Alternating mode preserves each original page size.

## 9. Deliver

Return the translated PDF (and bilingual PDF if requested) as sandbox links. Mention only material limitations actually found during QA.

## Script map

- `scripts/prepare.py` - reconstruct paragraph/table/caption units and cross-region flow.
- `scripts/validate.py` - verify IDs, completeness, and protected tokens.
- `scripts/apply.py` - text-only redaction plus paragraph-flow rendering with dynamic CJK font subsetting.
- `scripts/qa.py` - structural checks for geometry, overflow, source-text residue, and abnormal file growth.
- `scripts/render_preview.py` - render pages/contact sheets for visual QA.
- `scripts/make_dual.py` - optional alternating or side-by-side bilingual PDF.

## Intentional model boundary

The scripts cannot synchronously invoke the active ChatGPT conversation model without an API, and they must not try. The skill itself orchestrates the translation between deterministic script stages so the user's current ChatGPT/Work allowance performs the language work with zero external LLM API configuration.
