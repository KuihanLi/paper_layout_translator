# Paper Layout Translator

> 中文 | [English](README.en.md)

Paper Layout Translator 是一个面向 ChatGPT / Work 场景的学术论文 PDF 翻译 Skill。它的目标不是简单抽取文字再重新排版，而是在尽量保持**原始页数、分栏、公式、图表、背景、页几何和视觉层级**的前提下，将 born-digital 学术 PDF 按**语义段落**翻译并重新流入原始文字区域。

## 它能做什么

核心流程：

```text
检查原始 PDF
  ↓
重建语义段落 / 表格单元 / 标题 / 图注
  ↓
由当前 ChatGPT 会话模型完成翻译
  ↓
完整性与术语检查
  ↓
仅移除原文字形，不覆盖背景
  ↓
译文按原始区域重新排版
  ↓
结构 QA + 全页渲染检查
```

主要能力：

- 按段落而不是 PDF 行碎片翻译，降低断句、跨栏和上下文割裂问题；
- 保留页面数量、页面尺寸、双栏/多栏结构；
- 默认保留公式、图像、矢量图形、页面背景和注释；
- 通过 text-only redaction 移除原文字形，而不是使用白色矩形遮盖；
- 支持一个语义段落跨多个原始区域、跨栏甚至跨页重新流排；
- 保留数字、单位、模型名、数据集名、引用和数学含义；
- 默认保留参考文献条目，仅翻译 `References` 标题；
- 支持输出单语译文 PDF，以及可选的双语 alternating / side-by-side PDF；
- 不要求配置第三方 LLM API：语言翻译工作由当前 ChatGPT / Work 会话模型完成。

## 为什么采用“段落优先”

普通 PDF 文本层经常按视觉行或 span 保存。如果直接逐行翻译，会出现：

- 一个完整段落被拆成多个无关翻译请求；
- 连字符断词、引用、跨栏续接被破坏；
- 中文被强制塞进英文单行框，字体异常缩小；
- 使用白色遮罩替换原文会破坏彩色表格、底纹和页面图形。

因此 V2 工作流先在 PDF 内容流顺序中重建语义单元，再翻译整段，最后将同一段译文按原始几何区域依次流排。

## 与原参考项目的关系

本项目最初的设计目标受到以下项目启发：

- **Zotero PDF2zh** — `guaguastandup/zotero-pdf2zh`  
  https://github.com/guaguastandup/zotero-pdf2zh
- **PDFMathTranslate Next** — `PDFMathTranslate/PDFMathTranslate-next`  
  https://github.com/PDFMathTranslate/PDFMathTranslate-next
- **BabelDOC** — `funstory-ai/BabelDOC`  
  https://github.com/funstory-ai/BabelDOC

其中，`zotero-pdf2zh` 是一个 Zotero PDF 翻译插件，并通过 PDF2zh / PDF2zh_next 提供保留公式与排版的 PDF 翻译能力。该项目当前以 **AGPL-3.0** 发布。

Paper Layout Translator **不是上述项目的官方分支，也不打包或复制其实现代码**。本仓库是面向 ChatGPT / Work 的独立 Skill 与本地确定性 PDF 处理流水线：借鉴的是“先识别语义结构、保护公式/图形、再进行布局保持翻译”的设计原则。详细说明见 [`NOTICE.md`](NOTICE.md) 和 [`references/architecture.md`](references/architecture.md)。

## 目录结构

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

## 工作流

### 1. 预览与检查原始 PDF

```bash
python scripts/render_preview.py paper.pdf --outdir work/original_preview --pages auto --dpi 160 --contact-sheet
```

### 2. 重建段落级翻译单元

```bash
python scripts/prepare.py paper.pdf --workdir work --lang-out zh-CN
```

生成：

- `units.jsonl`：语义单元与原始渲染区域；
- `batches/batch_XXX.json`：供当前会话模型翻译的段落批次；
- `manifest.json`：页几何与准备报告；
- `translation_glossary.json`：术语表；
- `translated/`：保存会话生成的译文。

### 3. 使用当前 ChatGPT 会话完成翻译

每个 batch 中的 `source` 应作为一个完整语义单元翻译，不按原始 PDF 换行重新切分。

翻译结果保存为：

```json
{
  "items": [
    {"id": "u0005", "translation": "本文旨在……"}
  ]
}
```

### 4. 校验完整性

```bash
python scripts/validate.py --workdir work --strict --strict-tokens --write-merged
```

### 5. 应用译文

```bash
python scripts/apply.py paper.pdf --workdir work --output work/paper_translated.pdf
```

如果生成 `repair_batch.json`，只需压缩其中发生溢出的译文，再重新验证和渲染。

### 6. 结构 QA

```bash
python scripts/qa.py paper.pdf work/paper_translated.pdf --workdir work
```

### 7. 全页视觉检查

```bash
python scripts/render_preview.py work/paper_translated.pdf --outdir work/final_preview --pages all --dpi 130 --contact-sheet
```

最终交付前应确认：

- 页数与页尺寸一致；
- `apply_report.json` 中 `overflow: 0`；
- 无文字裁切、重叠、黑框或异常空格；
- 图表、公式、背景与矢量元素未被破坏；
- 段落连贯，不出现逐行碎片式翻译。

## 双语 PDF

单语译文通过 QA 后，可生成双语版本：

```bash
python scripts/make_dual.py paper.pdf work/paper_translated.pdf \
  --output work/paper_dual.pdf --layout alternating
```

`alternating` 保持每一页的原始尺寸；`side-by-side` 会改变页面宽度。

## 依赖

```bash
pip install -r requirements.txt
```

主要依赖：

- PyMuPDF
- Pillow
- fontTools

渲染中文时还需要运行环境中已经安装 Noto CJK 或 Source Han 一类 CJK 字体。仓库本身**不分发字体文件**。

## 当前限制

- 最适合有可提取文本层的 born-digital PDF；扫描件通常需先 OCR；
- 图片内部的栅格文字默认不会翻译；
- 极复杂杂志式排版、旋转文字、竖排文字或复杂矢量表格可能需要页面级修复；
- 不保证完全复刻原始专有字体，只保持几何、字号尺度、行距和视觉层级；
- 本地布局引擎比 BabelDOC 更轻量，重点是让 ChatGPT 会话能够在不配置外部翻译 API 的情况下完成完整流程。

## Skill 使用方式

在支持自定义 Skill 的 ChatGPT / Work 环境中，保留本仓库目录结构，并以 `SKILL.md` 作为入口。Skill 会在需要时调用本地脚本完成 PDF 解析、验证、排版和 QA，而真正的语言翻译由当前会话模型承担。

## License

本仓库中独立实现的代码与 Skill 文件采用 MIT License，见 [`LICENSE`](LICENSE)。

本项目所参考的上游项目拥有各自独立的版权与许可证；尤其 `guaguastandup/zotero-pdf2zh` 当前采用 AGPL-3.0。请勿将本仓库的 MIT License 理解为对任何上游项目代码重新授权。详见 [`NOTICE.md`](NOTICE.md)。
