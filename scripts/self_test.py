#!/usr/bin/env python3
"""Deterministic regression smoke tests for the layout renderer.

No network or translation API is used.  Tests cover CJK subset rendering, safe line-slot
flow around an exclusion, and Chinese density expansion.
"""
from __future__ import annotations
import importlib.util
import tempfile
from pathlib import Path
import fitz

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plt_apply", HERE / "apply.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

pre_spec = importlib.util.spec_from_file_location("plt_layout_preflight", HERE / "layout_preflight.py")
pre = importlib.util.module_from_spec(pre_spec)
assert pre_spec.loader
pre_spec.loader.exec_module(pre)


def ink_count(pix: fitz.Pixmap) -> int:
    n = pix.n
    data = pix.samples
    count = 0
    for i in range(0, len(data), n):
        if min(data[i:i+min(3,n)]) < 235:
            count += 1
    return count


def test_cjk_subset() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = mod.locate_font(False)
        subset, ok = mod.subset_font(src, td / "subset.otf", "中文测试 WiFi CSI")
        assert subset.exists()
        doc = fitz.open()
        page = doc.new_page(width=300, height=120)
        page.insert_font(fontname="T", fontfile=str(subset))
        page.insert_text((20, 60), "中文测试 WiFi CSI", fontname="T", fontsize=18)
        out = td / "cjk.pdf"
        doc.save(out)
        reopened = fitz.open(out)
        assert "中文测试" in reopened[0].get_text("text")
        pix = reopened[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        assert ink_count(pix) > 150, "CJK subset rendered blank"


def test_slot_flow_and_density() -> None:
    font_path = mod.locate_font(False)
    metrics = fitz.Font(fontfile=str(font_path))
    exclusion = [120, 10, 205, 75]
    unit = {
        "id": "u",
        "role": "body",
        "regions": [{
            "page": 1,
            "bbox": [10, 10, 205, 110],
            "line_count": 5,
            "font_size": 10.0,
            "line_pitch": 13.0,
            "first_indent": False,
            "indent_pt": 0,
            "layout_mode": "slots",
            "line_slots": [[10,10,115,22],[10,28,115,40],[10,46,115,58],[10,82,205,94],[10,98,205,110]],
            "exclusions": [exclusion],
            "color": [0,0,0],
            "redactions": [],
        }],
    }
    text = "这是用于验证中文排版安全槽位的测试段落，文字应该沿原有槽位流动，并且不能进入右侧图像区域。WiFi CSI 模型保持英文名称。"
    fs, placements, left = mod.choose_font_size(text, unit, metrics, 0.72)
    assert not left
    assert fs >= 10.0, f"expected CJK density expansion, got {fs}"
    for placement in placements:
        for line in placement["lines"]:
            slot = fitz.Rect(line["slot_bbox"])
            baseline = slot.y0 + fs * min(1.25, max(0.85, float(metrics.ascender or 1.05)))
            box = mod._line_box(slot.x0, baseline, line["text"], metrics, fs)
            assert not mod._collides(box, [exclusion]), (line["text"], box)



def test_vertical_fit_guard() -> None:
    font_path = mod.locate_font(False)
    metrics = fitz.Font(fontfile=str(font_path))
    unit = {
        "id": "v", "role": "body",
        "regions": [
            {"page": 1, "bbox": [10,10,210,20], "line_count": 1, "font_size": 10.0, "line_pitch": 13.0, "layout_mode": "flow", "line_slots": [[10,10,210,20]], "exclusions": [], "first_indent": False, "indent_pt": 0},
            {"page": 1, "bbox": [10,30,210,78], "line_count": 4, "font_size": 10.0, "line_pitch": 12.0, "layout_mode": "flow", "line_slots": [], "exclusions": [], "first_indent": False, "indent_pt": 0},
        ],
    }
    text = "用于检查一行高续接区域的垂直基线约束，字号搜索不能因为横向能放下就选择过大的字号。"
    fs, placements, left = mod.choose_font_size(text, unit, metrics, 0.72)
    assert not left
    first = placements[0]["lines"]
    assert first, "first continuation region should receive text"
    box = fitz.Rect(unit["regions"][0]["bbox"])
    asc = float(metrics.ascender if metrics.ascender else 1.05)
    baseline = box.y0 + fs * min(1.25, max(0.85, asc))
    assert baseline <= box.y1 + fs * 0.25 + 1e-6, (fs, baseline, box)



def test_layout_preflight_contract() -> None:
    regular = fitz.Font(fontfile=str(mod.locate_font(False)))
    bold = fitz.Font(fontfile=str(mod.locate_font(True)))
    safe = {
        "id": "p", "role": "body", "source": "A compact paragraph about WiFi CSI sensing and model evaluation.",
        "regions": [{
            "page": 1, "bbox": [10,10,210,100], "line_count": 5, "font_size": 10.0, "line_pitch": 13.0,
            "layout_mode": "slots", "line_slots": [[10,10,115,22],[10,28,115,40],[10,46,115,58],[10,70,210,82],[10,86,210,98]],
            "exclusions": [[120,10,205,65]], "first_indent": False, "indent_pt": 0,
        }],
    }
    plan, failures = pre.build_unit_plan(safe, [[220,120]], regular, bold, 0.72)
    assert not failures, failures
    assert plan["soft_cjk_chars"] > 0 and plan["hard_cjk_chars"] >= plan["soft_cjk_chars"]
    assert plan["risk"] in {"complex", "tight"}

    unsafe = {
        "id": "bad", "role": "body", "source": "unsafe",
        "regions": [{
            "page": 1, "bbox": [10,10,210,100], "line_count": 5, "font_size": 10.0, "line_pitch": 13.0,
            "layout_mode": "flow", "line_slots": [], "exclusions": [[120,10,205,65]],
            "first_indent": False, "indent_pt": 0,
        }],
    }
    _, failures = pre.build_unit_plan(unsafe, [[220,120]], regular, bold, 0.72)
    assert any("flow bbox intersects exclusion" in x for x in failures), failures


def test_pre_render_fit_gate() -> None:
    metrics = fitz.Font(fontfile=str(mod.locate_font(False)))
    unit = {
        "id": "fit", "role": "body",
        "regions": [{
            "page": 1, "bbox": [10,10,210,80], "line_count": 5, "font_size": 10.0, "line_pitch": 13.0,
            "layout_mode": "flow", "line_slots": [], "exclusions": [], "first_indent": False, "indent_pt": 0,
        }],
        "layout_budget": {"soft_cjk_chars": 60, "hard_cjk_chars": 90},
        "source": "source",
    }
    overflow, collisions, _ = mod.pre_render_fit_check([unit], {"fit": "这是一段用于验证翻译前布局预算和渲染前适配检查的中文文本。"}, metrics, metrics, 0.72)
    assert not overflow and not collisions

    very_long = "中文" * 400
    overflow, _, _ = mod.pre_render_fit_check([unit], {"fit": very_long}, metrics, metrics, 0.72)
    assert overflow, "expected pre-render fit failure for oversized translation"

def main() -> int:
    test_cjk_subset()
    test_slot_flow_and_density()
    test_vertical_fit_guard()
    test_layout_preflight_contract()
    test_pre_render_fit_gate()
    print("paper-layout-translator self-test: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
