# Academic translation policy - paragraph-first

## Goal
Translate for accurate academic reading while keeping the PDF's original visual structure. Preserve the paper's claims, uncertainty, terminology, numerical values, units, citations, equations, model names, and logical relations. Never silently correct the paper.

## Translate semantic units, not PDF lines
Each batch item is a reconstructed semantic unit such as a paragraph, heading, caption, keyword list, or table cell. The `source` field is already de-hyphenated and may combine fragments from multiple visual regions or even adjacent columns/pages.

For every item:
1. Translate `source` as one coherent unit. **Do not split the translation according to the original PDF's line breaks.**
2. Use `prev_tail` and `next_head` only for discourse context; do not repeat them in the translation.
3. Return exactly one translation for each `id`.
4. Keep the translation complete but reasonably concise. Prefer normal academic Chinese rather than word-for-word line fragments.
5. Preserve numbers, percentages, units, acronyms, model/dataset names, equation references, and citations. `hard_tokens` lists tokens that deserve special attention.
6. Preserve author-year citations such as `(Wang et al., 2020)` rather than translating author names.
7. Do not add translator notes, Markdown, explanations, quotation marks, or commentary inside `translation`.

## Terminology
- Keep established names such as `CatBoost`, `XGBoost`, `LightGBM`, `ARIMA`, `RMSE`, `MSE`, `STLF`, `LSTM`, and dataset/code identifiers unchanged unless a conventional Chinese expansion is useful on first mention.
- Keep one stable Chinese term for each technical concept across the paper. Update `translation_glossary.json` when a recurring term is settled.
- Keep DOIs, URLs, e-mail addresses, formulas, symbols, and bibliographic reference entries unchanged by default.
- Translate title, abstract, section headings, keywords, prose, captions, footnotes, and text-based table labels/cells.

## Formula behavior
Display equations are normally excluded from translation units and remain untouched in the original PDF. When an inline symbol or equation reference appears inside prose, preserve it faithfully in the translated paragraph. Never paraphrase a mathematical expression into a different claim.

## Output schema
Save each translated batch as UTF-8 JSON only:

```json
{
  "items": [
    {"id": "u0005", "translation": "本文旨在……"}
  ]
}
```

Do not copy `source`, `prev_tail`, `next_head`, or `hard_tokens` into the translated file unless needed for debugging.

## Overflow repair
If `apply.py` creates `repair_batch.json`, shorten only the listed paragraph translations. Preserve all technical meaning and protected tokens. Save fixes to `translated/batch_repair.json`. Later translation files override earlier entries.
