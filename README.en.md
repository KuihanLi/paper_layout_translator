# Paper Layout Translator

> [中文](README.md) | English

Paper Layout Translator is an academic PDF translation Skill designed for ChatGPT / Work. Instead of extracting text and rebuilding the document from scratch, it translates **semantic paragraphs** and flows the translation back through the PDF's original text regions while preserving page count, columns, equations, figures, backgrounds, and page geometry as closely as practical.

## What it does

```text
inspect source PDF
  -> reconstruct semantic paragraphs / table cells / captions
  -> translate with the active ChatGPT session model
  -> validate completeness and protected tokens
  -> remove source glyphs only
  -> flow translated paragraphs through original regions
  -> structural QA + full-page visual inspection
```

Key capabilities:

- paragraph-first translation instead of PDF-line fragments;
- preservation of page dimensions and multi-column structure;
- display equations, images, vector graphics, page backgrounds, and annotations remain untouched by default;
- source text is removed with text-only redaction rather than opaque white overlays;
- one semantic paragraph can flow across multiple original regions, columns, or pages;
- numbers, units, citations, model names, dataset names, and mathematical meaning are protected;
- bibliographic entries are preserved by default;
- optional alternating or side-by-side bilingual PDFs;
- no third-party LLM API is required: language translation is performed by the active ChatGPT / Work session.

## Upstream inspiration and attribution

The project was originally motivated by studying layout-preserving academic PDF translation projects, especially:

- **Zotero PDF2zh** — `guaguastandup/zotero-pdf2zh`  
  https://github.com/guaguastandup/zotero-pdf2zh
- **PDFMathTranslate Next** — `PDFMathTranslate/PDFMathTranslate-next`  
  https://github.com/PDFMathTranslate/PDFMathTranslate-next
- **BabelDOC** — `funstory-ai/BabelDOC`  
  https://github.com/funstory-ai/BabelDOC

`zotero-pdf2zh` is a Zotero PDF translation plugin that integrates PDF2zh / PDF2zh_next for layout- and formula-preserving PDF translation. At the time this repository was published, that upstream repository is distributed under **AGPL-3.0**.

Paper Layout Translator is **not an official fork of those projects and does not bundle or copy their implementation code**. It is an independent ChatGPT / Work Skill and deterministic local PDF-processing pipeline that follows several high-level design lessons: reconstruct semantic paragraphs before translation, protect math/graphics, preserve logical multi-column order, and render translation back into the original regions only after translation.

See [`NOTICE.md`](NOTICE.md) and [`references/architecture.md`](references/architecture.md) for details.

## Repository layout

```text
paper_layout_translator/
├── SKILL.md
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
│   └── translation_policy.md
└── scripts/
    ├── prepare.py
    ├── validate.py
    ├── apply.py
    ├── qa.py
    ├── render_preview.py
    └── make_dual.py
```

## Quick workflow

Preview the source:

```bash
python scripts/render_preview.py paper.pdf --outdir work/original_preview --pages auto --dpi 160 --contact-sheet
```

Prepare paragraph-aware units:

```bash
python scripts/prepare.py paper.pdf --workdir work --lang-out zh-CN
```

Translate the generated batches with the active ChatGPT / Work session and save translation files under `work/translated/`.

Validate:

```bash
python scripts/validate.py --workdir work --strict --strict-tokens --write-merged
```

Apply translations:

```bash
python scripts/apply.py paper.pdf --workdir work --output work/paper_translated.pdf
```

Run structural QA:

```bash
python scripts/qa.py paper.pdf work/paper_translated.pdf --workdir work
```

Render every translated page for visual inspection:

```bash
python scripts/render_preview.py work/paper_translated.pdf --outdir work/final_preview --pages all --dpi 130 --contact-sheet
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
- Rasterized text inside figures is left unchanged by default.
- Highly irregular magazine layouts, rotated/vertical text, or deeply nested vector tables can require page-specific repairs.
- Exact proprietary source fonts are not guaranteed; the workflow preserves geometry and typographic scale using an available CJK-compatible font.
- The local engine is intentionally lighter than BabelDOC; the active ChatGPT session remains the translator.

## License

The independently implemented code and Skill files in this repository are released under the MIT License. Upstream projects retain their own copyrights and licenses; in particular, `guaguastandup/zotero-pdf2zh` is AGPL-3.0. See [`NOTICE.md`](NOTICE.md).
