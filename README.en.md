# Paper Layout Translator

> [中文](README.md) | English

Paper Layout Translator is an academic PDF translation Skill for ChatGPT / Work. Instead of extracting text and rebuilding the document from scratch, it preserves the original page count, columns, equations, figures, backgrounds, and page geometry as closely as practical. V3.1 first establishes a **target-language layout contract before translation**, then translates semantic paragraphs and writes them back only after a pre-render fit gate passes.

The current public engine is **Paper Layout Translator V3.1**.

## What changed in V3.1

```text
inspect source PDF
  -> reconstruct semantic units + source geometry
  -> layout preflight
       -> safe writable regions
       -> image/figure exclusions
       -> flow vs slots classification
       -> CJK font/capacity budget
       -> PASS before batches exist
  -> translate with the active ChatGPT session model
  -> validate completeness / protected tokens
  -> pre-render fit gate with real translated text
  -> text-only replacement only after PASS
  -> structural QA + full-page visual QA
```

This makes text/figure overlap, wrap-around prose, narrow continuation regions, and target-language density primarily **pre-constrained layout problems**, not issues discovered only after a PDF has already been rendered.

## Key capabilities

- paragraph-first translation instead of PDF-line fragments;
- pre-translation detection and freezing of safe target-language writable regions;
- `flow` regions for regular prose and source-line `slots` for wrap-around / irregular prose;
- hard protection for images, diagrams, matrices, vector graphics, equations, and backgrounds;
- raster figure-internal text is preserved by default and translated only when explicitly requested;
- per-unit `soft_cjk_chars` / `hard_cjk_chars` plus preferred/minimum font budgets;
- CJK density-aware font/leading adaptation to reduce unnecessary whitespace;
- pre-render fitting of actual translated text before the source PDF is mutated;
- text-only redaction rather than opaque white overlays;
- retained glyph IDs during CJK subsetting to avoid Identity-H rendering regressions;
- final QA for geometry, preserved images, out-of-page text, CJK rendering, overflow, and collisions;
- optional alternating or side-by-side bilingual PDFs;
- no third-party LLM API: the active ChatGPT / Work session performs the linguistic translation.

## Upstream inspiration and attribution

The project was motivated by studying layout-preserving academic PDF translation projects, especially:

- **Zotero PDF2zh** — `guaguastandup/zotero-pdf2zh`  
  https://github.com/guaguastandup/zotero-pdf2zh
- **PDFMathTranslate Next** — `PDFMathTranslate/PDFMathTranslate-next`  
  https://github.com/PDFMathTranslate/PDFMathTranslate-next
- **BabelDOC** — `funstory-ai/BabelDOC`  
  https://github.com/funstory-ai/BabelDOC

Paper Layout Translator is **not an official fork and does not bundle or copy their implementation code**. It is an independent ChatGPT / Work Skill and deterministic local PDF-processing pipeline that follows high-level lessons such as semantic reconstruction, math/graphics protection, and layout-preserving rendering. See [`NOTICE.md`](NOTICE.md) and [`references/architecture.md`](references/architecture.md).

## Repository layout

```text
paper_layout_translator/
├── SKILL.md
├── VERSION.md
├── README.md
├── README.en.md
├── NOTICE.md
├── LICENSE
├── requirements.txt
├── agents/
│   └── openai.yaml
├── assets/
│   └── icon.svg
├── references/
│   ├── architecture.md
│   ├── layout_policy.md
│   └── translation_policy.md
└── scripts/
    ├── prepare.py
    ├── layout_preflight.py
    ├── validate.py
    ├── apply.py
    ├── qa.py
    ├── render_preview.py
    ├── make_dual.py
    └── self_test.py
```

## Quick workflow

Preview the source:

```bash
python scripts/render_preview.py paper.pdf --outdir work/original_preview --pages auto --dpi 160 --contact-sheet
```

Reconstruct semantic units and raw geometry:

```bash
python scripts/prepare.py paper.pdf --workdir work --lang-out zh-CN
```

`prepare.py` intentionally creates **no translation batches**.

Run layout preflight:

```bash
python scripts/layout_preflight.py --workdir work
```

Only a `PASS` creates `units_planned.jsonl`, `layout_plan.json`, `layout_preflight.pdf`, and `batches/batch_XXX.json`.

Preview the layout plan:

```bash
python scripts/render_preview.py work/layout_preflight.pdf --outdir work/layout_preflight_preview --pages auto --dpi 130 --contact-sheet
```

Translate the generated batches with the active ChatGPT / Work session, using each item's layout budget as a concision target without dropping scientific meaning.

Validate:

```bash
python scripts/validate.py --workdir work --strict --write-merged
python scripts/validate.py --workdir work --strict --strict-tokens --write-merged
```

Apply translations:

```bash
python scripts/apply.py paper.pdf --workdir work --output work/paper_translated.pdf
```

Before modifying the source PDF, `apply.py` fits the real translation through the frozen layout. If it cannot fit safely, it writes a repair batch and exits without rendering a knowingly broken PDF.

Run structural QA:

```bash
python scripts/qa.py paper.pdf work/paper_translated.pdf --workdir work
```

Render every translated page:

```bash
python scripts/render_preview.py work/paper_translated.pdf --outdir work/final_preview --pages all --dpi 130 --contact-sheet
```

Run deterministic regression tests after Skill changes:

```bash
python scripts/self_test.py
```

Optional bilingual PDF:

```bash
python scripts/make_dual.py paper.pdf work/paper_translated.pdf \
  --output work/paper_dual.pdf --layout alternating
```

## Dependencies

```bash
pip install -r requirements.txt
```

The runtime also needs an installed CJK font such as Noto CJK or Source Han. Font files are not distributed in this repository.

## Current limitations

- Best on born-digital PDFs with extractable text; scans usually require OCR first.
- Rasterized text inside figures is preserved by default rather than automatically translated.
- Highly irregular magazine layouts, rotated/vertical text, or deeply nested vector tables can still require page-specific handling.
- Exact proprietary source fonts are not guaranteed; the workflow preserves geometry and typographic scale using an available CJK-compatible font.
- The local engine is intentionally lighter than BabelDOC; the active ChatGPT session remains the translator.

## License

The independently implemented code and Skill files in this repository are released under the MIT License. Upstream projects retain their own copyrights and licenses; in particular, `guaguastandup/zotero-pdf2zh` is AGPL-3.0. See [`NOTICE.md`](NOTICE.md).
