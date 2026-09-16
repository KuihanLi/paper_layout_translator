# Architecture and rationale - V2

## Why V1 did not match PDF2zh/BabelDOC quality
The first implementation treated visual PDF lines / span groups as translation units and then painted white rectangles over those boxes. That architecture has three predictable failure modes:

1. **Line-fragment translation** - a semantic paragraph becomes many unrelated model calls, so citations, hyphenated words, discourse order, and cross-column continuation break.
2. **Box-by-box typesetting** - Chinese is forced into the dimensions of individual English lines, producing tiny type, uneven whitespace, and unnatural wrapping.
3. **Background destruction** - opaque white cover rectangles assume a white page and can visibly damage colored cells, shaded areas, rules, or other page artwork. Repeated multilingual HTML fallback can also inflate the PDF substantially.

V2 replaces that architecture rather than merely tuning font sizes.

## Upstream design lesson
`zotero-pdf2zh` delegates the difficult layout work to `pdf2zh_next` / BabelDOC. PDFMathTranslate-next identifies itself as BabelDOC-based and emphasizes preserving formulas, charts, tables of contents, and annotations. BabelDOC's translator documentation describes paragraph processing and formula/rich-text placeholders before translation. The upstream PDFMathTranslate documentation also highlights cross-column/cross-page semantic consistency and dynamic scaling in the newer engine.

V2 follows those **design principles** without bundling or copying the upstream AGPL implementation:

- semantic paragraphs before translation;
- protected display math;
- logical content-stream order for multi-column papers;
- cross-block / cross-column / cross-page paragraph flow when geometry indicates continuation;
- layout-specific handling for table cells and captions;
- rendering back into the original regions only after translation.

## Session-native model boundary
A local Python script cannot consume the current ChatGPT subscription/session model without an API call. Therefore the skill intentionally separates deterministic PDF work from linguistic work:

1. `prepare.py`: local parsing only; output paragraph-level JSON batches.
2. Active ChatGPT / Work model: translate batches directly using the current session allowance.
3. `validate.py`: check IDs, completeness, and protected tokens.
4. `apply.py`: text-only PDF redaction + translated paragraph flow.
5. `qa.py` + rendered previews: structural and visual verification.

No bundled script sends text to OpenAI, DeepSeek, Google, Microsoft, SiliconFlow, or another translation endpoint.

## Background-preserving replacement
V2 no longer paints a guessed background color. It adds redaction annotations over source glyph boxes and applies redactions with **text removal only** (`images=0`, `graphics=0`, `text=0` in PyMuPDF). Images, vector lines, fills, charts, and page backgrounds therefore remain in the original PDF content.

This is materially closer to "do not change the paper layout" than painting white rectangles over text.

## Paragraph-flow rendering
A unit can have multiple `regions`. For example, a paragraph may start at the bottom of the left column and continue near the top of the right column. The model produces one coherent Chinese translation; the renderer then wraps that single translation sequentially through the original regions while retaining each region's width, line count, approximate font size, line pitch, color, and first-line indentation.

Tables are intentionally different: cells/labels remain separate units because collapsing a table into prose would destroy its structure.

## Font strategy
V2 does not bundle font files. At render time it locates a CJK font already installed in the runtime, dynamically subsets it to the characters actually needed, and embeds only that small subset into the output PDF. This gives natural mixed Chinese/Latin text such as `CatBoost 与 XGBoost` while avoiding the tens-of-megabytes blow-up caused by repeatedly embedding fallback fonts.

## Current limits
- Best on born-digital PDFs with extractable text. Image-only scans still require OCR first.
- Rasterized text inside figures is intentionally left unchanged unless the user requests image translation.
- Very complex magazines, arbitrary rotated text, unusual vertical writing, and deeply nested vector tables can still require page-specific repair.
- Exact proprietary source font identity is not guaranteed; V2 preserves geometry and typographic scale while using an installed CJK-compatible serif/sans font.
- The local fallback engine is independent and lighter than BabelDOC. If the runtime already provides an upstream layout engine, it may be used only when doing so does not require a third-party translation API; the active ChatGPT session remains the translator.

## Upstream references
- Zotero integration: https://github.com/guaguastandup/zotero-pdf2zh
- PDFMathTranslate Next: https://github.com/PDFMathTranslate/PDFMathTranslate-next
- BabelDOC translator implementation notes: https://github.com/funstory-ai/BabelDOC/blob/main/docs/ImplementationDetails/ILTranslator/ILTranslator.md
