# Version

- Build: `V3.1.0`
- Date: 2026-09-23
- Status: stable public release.
- Architecture change: layout is a pre-translation hard contract. `prepare.py` extracts semantics/geometry only; `layout_preflight.py` validates/finalizes writable regions, creates CJK capacity budgets and translation batches, and `apply.py` refuses to mutate the PDF until every completed translation passes a pre-render fit check.
- Retained V3 fixes: safe wrap-around line slots, CJK density-aware typography, retained glyph IDs, figure-internal label preservation, collision/overflow QA, translation run log.
