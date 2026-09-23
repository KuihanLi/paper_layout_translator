# Paper Layout Translator

> 中文 | [English](README.en.md)

Paper Layout Translator 是一个面向 ChatGPT / Work 场景的学术论文 PDF 翻译 Skill。它不是简单抽取文字后重新排版，而是尽量保持**原始页数、分栏、公式、图表、背景、页几何和视觉层级**，并在翻译前先建立目标语言的安全排版合同，再将段落级译文写回原始区域。

当前公开版本对应 **Paper Layout Translator V3.1**。

## V3.1 的核心变化

V3.1 将“布局是否安全”从渲染后的检查项，前移成翻译前的硬门槛：

```text
检查原始 PDF
  ↓
重建语义段落 + 原始几何
  ↓
Layout Preflight
  ├─ 识别可写区域与图像禁入区
  ├─ 将区域分类为 flow / slots
  ├─ 冻结最终排版几何
  ├─ 估计中文目标字号与容量预算
  └─ PASS 后才生成翻译 batch
  ↓
当前 ChatGPT 会话模型按版面预算翻译
  ↓
完整性 / protected-token 校验
  ↓
Pre-render Fit Gate：真实译文先试排
  ↓
PASS 后才移除原文字形并写入中文
  ↓
结构 QA + 全页视觉 QA
```

因此，图像遮挡、绕图正文、窄栏溢出等问题不再主要依赖“先渲染再返工”发现。

## 主要能力

- 按语义段落而不是 PDF 行碎片翻译；
- 翻译前识别并冻结目标语言安全排版区域；
- 对普通段落使用 `flow` 区域，对绕图/异形正文使用真实源行 `slots`；
- 图像、流程图、矩阵、矢量图形、公式和页面背景作为硬保护对象；
- 默认保留图内栅格文字，只有显式请求时才翻译图内标签；
- 为每个翻译单元生成 `soft_cjk_chars` / `hard_cjk_chars` 和推荐/最小字号预算；
- 中文较短时允许在安全范围内适当增加字号/行距，减少无意义留白；
- `apply.py` 在真正修改 PDF 前先进行真实译文 Fit Gate；
- 使用 text-only redaction 移除原文字形，不使用白色矩形覆盖背景；
- CJK 字体子集化保留 glyph ID，降低 Identity-H 下的缺字风险；
- 最终 QA 检查页几何、图片保留、文字越界、CJK 渲染、overflow 与 collision；
- 支持可选双语 alternating / side-by-side PDF；
- 不需要第三方 LLM API：语言翻译由当前 ChatGPT / Work 会话模型完成。

## 与原参考项目的关系

本项目的设计目标受到以下项目启发：

- **Zotero PDF2zh** — `guaguastandup/zotero-pdf2zh`  
  https://github.com/guaguastandup/zotero-pdf2zh
- **PDFMathTranslate Next** — `PDFMathTranslate/PDFMathTranslate-next`  
  https://github.com/PDFMathTranslate/PDFMathTranslate-next
- **BabelDOC** — `funstory-ai/BabelDOC`  
  https://github.com/funstory-ai/BabelDOC

其中 `zotero-pdf2zh` 通过 PDF2zh / PDF2zh_next 提供保留公式与排版的 PDF 翻译能力，并采用 **AGPL-3.0**。

Paper Layout Translator **不是上述项目的官方分支，也不打包或复制其实现代码**。本仓库是面向 ChatGPT / Work 的独立 Skill 与本地确定性 PDF 处理流水线，借鉴的是语义重建、图形/公式保护和布局保持等高层设计原则。详细说明见 [`NOTICE.md`](NOTICE.md) 和 [`references/architecture.md`](references/architecture.md)。

## 目录结构

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

## 工作流

### 1. 预览原始 PDF

```bash
python scripts/render_preview.py paper.pdf --outdir work/original_preview --pages auto --dpi 160 --contact-sheet
```

### 2. 重建语义单元与原始几何

```bash
python scripts/prepare.py paper.pdf --workdir work --lang-out zh-CN
```

这一阶段**不会生成翻译 batch**。主要生成：

- `units.jsonl`：语义单元、原始区域、行槽与 exclusions；
- `manifest.json`：页面几何和提取状态；
- `translation_glossary.json`：术语表。

### 3. 翻译前布局预检

```bash
python scripts/layout_preflight.py --workdir work
```

必须得到 `status: PASS` 才能开始翻译。它会生成：

- `units_planned.jsonl`：冻结后的最终安全排版区域；
- `layout_plan.json`：容量、字号与风险报告；
- `layout_preflight.pdf`：安全区域 / 禁入区可视化；
- `batches/batch_XXX.json`：只有预检通过后才生成的翻译批次。

建议先查看预检 PDF：

```bash
python scripts/render_preview.py work/layout_preflight.pdf --outdir work/layout_preflight_preview --pages auto --dpi 130 --contact-sheet
```

### 4. 使用当前 ChatGPT 会话翻译

每个 batch 中的 `source` 作为完整语义单元翻译，并参考 `layout_budget`：

- `soft_cjk_chars`：舒适字号下的建议中文容量；
- `hard_cjk_chars`：最低可接受字号下的空间警戒值。

容量预算只用于帮助译文紧凑自然，**不能作为删除科学信息、数字、条件、引用或不确定性的理由**。

### 5. 完整性校验

```bash
python scripts/validate.py --workdir work --strict --write-merged
python scripts/validate.py --workdir work --strict --strict-tokens --write-merged
```

### 6. Pre-render Fit Gate + 应用译文

```bash
python scripts/apply.py paper.pdf --workdir work --output work/paper_translated.pdf
```

`apply.py` 会先在内存中用真实中文译文模拟排版。若存在 overflow 或 exclusion/collision 风险，会生成 `translation_fit_report.json` / `repair_batch.json` 并退出，**不会先删除英文再生成一个已知有问题的 PDF**。

只有 Fit Gate 通过后，才进行 text-only redaction 和最终中文写入。

### 7. 结构 QA

```bash
python scripts/qa.py paper.pdf work/paper_translated.pdf --workdir work
```

### 8. 全页视觉检查

```bash
python scripts/render_preview.py work/paper_translated.pdf --outdir work/final_preview --pages all --dpi 130 --contact-sheet
```

最终交付前确认：

- 页数与页面尺寸一致；
- `overflow: 0`；
- `collision_guard_failures: 0`；
- 无文字裁切、跨图、越界、黑框或缺字；
- 图表、公式、矩阵、流程图、背景与矢量元素保持；
- 中文密度自然，不因机械沿用英文尺度留下大面积空白；
- 复杂页建议额外用第二渲染器 spot check。

## 回归自测

修改 Skill 后运行：

```bash
python scripts/self_test.py
```

当前测试覆盖 CJK 子集渲染、绕图行槽、垂直 fit、翻译前 layout contract 与 pre-render fit gate。

## 双语 PDF

单语译文通过 QA 后：

```bash
python scripts/make_dual.py paper.pdf work/paper_translated.pdf \
  --output work/paper_dual.pdf --layout alternating
```

`alternating` 保持原始页尺寸；`side-by-side` 会改变页面宽度。

## 依赖

```bash
pip install -r requirements.txt
```

主要依赖：PyMuPDF、Pillow、fontTools。渲染中文还需要运行环境已有 Noto CJK、Source Han 等 CJK 字体；仓库本身不分发字体文件。

## 当前限制

- 最适合有可提取文本层的 born-digital PDF；扫描件通常需先 OCR；
- 图片内部的栅格文字默认保留，不自动翻译；
- 极复杂杂志式排版、旋转/竖排文字、深度嵌套矢量表格仍可能需要页面级处理；
- 不保证完全复刻原始专有字体，只保持几何、字号尺度、行距和视觉层级；
- 本地布局引擎比 BabelDOC 更轻量，目标是在无需外部翻译 API 的前提下利用当前 ChatGPT 会话完成可靠的学术 PDF 翻译。

## License

本仓库中独立实现的代码与 Skill 文件采用 MIT License，见 [`LICENSE`](LICENSE)。上游项目保留各自版权与许可证；尤其 `guaguastandup/zotero-pdf2zh` 当前采用 AGPL-3.0。详见 [`NOTICE.md`](NOTICE.md)。
