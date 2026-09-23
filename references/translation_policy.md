# Academic translation policy - paragraph first

## Goal

Translate for accurate academic reading while preserving the paper's claims, uncertainty, terminology, numerical values, units, citations, equations, model names, and logical relations. Never silently correct the paper.

## Semantic units

Each batch item is a reconstructed paragraph, heading, caption, keyword list, or table cell. Translate the complete `source` as one coherent unit and ignore the source PDF's visual line breaks. Use `prev_tail` / `next_head` only for context.

Keep Chinese complete but moderately concise. Concision is a layout aid, not permission to delete qualifications, methods, conditions, numerical results, or limitations.

## Protected content

- Preserve numbers, percentages, units, acronyms, model/dataset names, equation references, citations, URLs, DOIs, e-mail addresses, and formulas.
- Keep established identifiers such as `CatBoost`, `XGBoost`, `LightGBM`, `ARIMA`, `RMSE`, `MSE`, `LSTM`, `WiFi`, and `CSI` unchanged unless a conventional Chinese expansion helps on first mention.
- Preserve author-year citations such as `(Wang et al., 2020)`.
- Do not translate bibliographic reference entries by default.
- Display equations normally remain outside translation units.

## Figure-internal text

Text embedded inside raster figure regions is preserved by default and may therefore remain English in an otherwise Chinese paper. Do not treat this as a missing body translation. Translate it only when the user explicitly requests figure-label translation.

## Terminology

Use one stable Chinese term for recurring technical concepts and update `translation_glossary.json` when a term is settled.

## Output

Save exactly one translation per ID:

```json
{
  "items": [
    {"id": "u0005", "translation": "本文旨在……"}
  ]
}
```

Do not add Markdown, translator notes, explanations, or quotation marks inside `translation`.

## Overflow repair

If `apply.py` creates `repair_batch.json`, shorten only those translations. Preserve every technical claim, protected token, number, unit, citation, and qualifier. Later repair files override earlier translations. Do not solve overflow by fragmenting a semantic paragraph into independent translation calls.


## Layout budget - V3.1
Each model item may include `layout_budget`, generated before translation from the final safe target regions.

- Aim for `soft_cjk_chars` when natural academic Chinese can do so without loss.
- Treat `hard_cjk_chars` as a spatial warning only. Never delete claims, qualifiers, numbers, units, citations, model names, or uncertainty to hit a budget.
- If faithful wording cannot fit, preserve the meaning. The deterministic pre-render fit gate will request a compact repair before the PDF is modified.
- Do not manually split one semantic paragraph into source PDF lines to satisfy the budget.
