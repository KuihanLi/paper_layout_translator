# Changelog

## v1.1.0 - 2026-09-23

Paper Layout Translator V3.1 workflow and renderer update.

### Added
- Pre-translation `layout_preflight.py` hard gate.
- Frozen `units_planned.jsonl` layout contract and `layout_plan.json` risk/capacity report.
- Layout-preview PDF showing writable regions and figure/image exclusions before translation begins.
- Per-unit CJK capacity budgets (`soft_cjk_chars`, `hard_cjk_chars`) and preferred/minimum font targets.
- Pre-render fit gate using the real translated text before source glyphs are removed.
- `flow` / source-line `slots` region classes for regular versus wrap-around/irregular text.
- `layout_policy.md` and deterministic `self_test.py` regression tests.
- `VERSION.md` build identity.

### Fixed
- Text crossing figures/diagrams because a paragraph union bbox ignored wrap-around geometry.
- Excess whitespace caused by mechanically preserving English typographic density for shorter Chinese text.
- CJK subset rendering regressions by retaining glyph IDs for Identity-H use.
- False overflow caused by font-size search not matching final vertical-baseline constraints.
- Figure-internal raster labels being treated as ordinary body prose by default.
- Late discovery of geometry errors after a PDF had already been rendered.

### Changed
- `prepare.py` now extracts semantics and raw geometry only; it no longer emits translation batches.
- Translation batches are generated only after layout preflight passes.
- `apply.py` refuses to mutate the PDF when the translated text does not safely fit the approved layout.
- Final QA remains mandatory but now verifies a pre-constrained layout rather than serving as the primary collision-repair stage.

## v1.0.0 - 2026-09-16

Initial public release of Paper Layout Translator V2.

### Highlights
- paragraph-first academic PDF translation workflow;
- content-stream-order reconstruction for multi-column papers;
- text-only redaction that preserves images, vector graphics, fills, and backgrounds;
- cross-region / cross-column / cross-page paragraph flow;
- protected token validation for numbers, model names, citations, and technical identifiers;
- dynamic local CJK font subsetting;
- structural QA and full-page visual preview tooling;
- optional bilingual PDF generation;
- session-native translation architecture with no third-party LLM API requirement in bundled scripts.
