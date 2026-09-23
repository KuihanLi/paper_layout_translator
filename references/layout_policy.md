# Layout and visual-QA policy - V3.1

## 1. Layout is a pre-translation contract

Do not use rendered output as the first place to discover text/image overlap. Before any translation batch is created:

1. reconstruct semantic units;
2. classify every writable region as `flow` or `slots`;
3. freeze figure/image exclusion zones;
4. verify region/page geometry;
5. estimate target-language CJK capacity at comfortable and minimum font sizes;
6. generate translation batches only after the layout preflight passes.

Post-render collision detection is an invariant check, not the primary layout algorithm.

## 2. Keep semantics separate from geometry

Translate a paragraph as one semantic unit. Do not split translation calls because the source wraps around a figure or crosses columns/pages. Geometry belongs to the layout plan; meaning belongs to the translation unit.

## 3. Layout classes

### Regular flow region
Use a rectangular region only when its full writable bbox does not intersect a protected image/figure exclusion. Chinese may rewrap naturally inside this approved rectangle.

### Safe line-slot region
Use original source-line slots when the paragraph is non-rectangular, wraps a figure, or has materially shifting middle-line edges. Each translated line must remain inside a planned slot.

### Figure-internal text
Text substantially embedded inside a raster figure is protected by default and must not be treated as prose. Translate it only through an explicit figure-label workflow.

## 4. Translation capacity budget

`layout_preflight.py` estimates two capacities for every semantic unit:

- `soft_cjk_chars`: the approximate amount of Chinese that fits at a comfortable target font size with safety headroom;
- `hard_cjk_chars`: a warning threshold based on the minimum acceptable font size.

The translator should aim for the soft budget through concise academic Chinese, but may exceed it when fidelity requires. Budgets never authorize deleting claims, conditions, numbers, units, citations, or uncertainty.

After translation, the renderer performs an exact pre-render fit test with the actual translated text. If it cannot fit, request a compact rewrite before any source glyph is removed.

## 5. Chinese density adaptation

English and Chinese have different visual densities. Use this order:

1. preserve meaning;
2. fit at a comfortable CJK font size within the approved geometry;
3. modestly increase font size and/or line pitch when Chinese is substantially shorter;
4. shrink only as needed;
5. request a compact rewrite only after geometric adaptation is exhausted.

Recommended upper bounds remain conservative: about +12% body, +9% caption/keywords, +5% table cells.

## 6. Collision safety

- Image/figure zones are hard exclusions.
- A `flow` region intersecting an exclusion is a **preflight failure** and must be converted to slots or resegmented before translation.
- A slot intersecting an exclusion is a **preflight failure**.
- `apply.py` must use `units_planned.jsonl`; it may not enlarge or invent regions at render time.
- Any collision detected during the pre-render fit gate or final insertion is a hard failure.

## 7. CJK font safety

When subsetting Type0/CID `Identity-H` fonts, retain glyph IDs. Any font-embedding change must pass the deterministic self-test and a rendered visual check.

## 8. QA expectations

Final output still requires:

- identical page count and dimensions;
- zero pre-render fit failures;
- zero unresolved overflow;
- zero collision-guard failures;
- zero out-of-page insertions;
- visible CJK glyphs;
- preserved images/figures;
- full-page visual inspection;
- second-renderer spot checks on complex pages when available.

The final visual QA verifies the frozen layout contract; it should not be the normal mechanism for discovering geometry that could have been rejected before translation.
