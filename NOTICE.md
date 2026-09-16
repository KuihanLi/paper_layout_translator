# Notice and upstream acknowledgements

Paper Layout Translator is an independent ChatGPT / Work Skill and local PDF-processing workflow.

## Primary inspiration

### Zotero PDF2zh

- Repository: https://github.com/guaguastandup/zotero-pdf2zh
- Project: Zotero PDF2zh
- Upstream description: Zotero PDF translation plugin integrating PDF2zh / PDF2zh_next while preserving formulas and layout.
- Upstream license at the time of publication: GNU Affero General Public License v3.0 (AGPL-3.0).

This repository was initially motivated by studying the user experience and layout-preserving translation goals of Zotero PDF2zh.

Paper Layout Translator is **not an official fork of Zotero PDF2zh** and does not bundle or copy its implementation code. The local scripts in this repository are independently implemented for a different execution model: deterministic PDF preparation/rendering scripts are combined with the active ChatGPT / Work session as the translator, avoiding any requirement to configure an external LLM API inside the scripts.

## Additional upstream design references

### PDFMathTranslate Next

- Repository: https://github.com/PDFMathTranslate/PDFMathTranslate-next

The architecture review drew on its public layout-preserving translation goals, including protection of mathematical content and document structure.

### BabelDOC

- Repository: https://github.com/funstory-ai/BabelDOC
- Translator implementation notes referenced during design:
  https://github.com/funstory-ai/BabelDOC/blob/main/docs/ImplementationDetails/ILTranslator/ILTranslator.md

The architecture review drew on public documentation describing paragraph-oriented translation and preservation of formulas/rich-text placeholders.

## Relationship to this repository's license

The MIT License in this repository applies only to the independently implemented files contained here. It does not relicense, replace, or override the copyright or license of Zotero PDF2zh, PDFMathTranslate Next, BabelDOC, or any other upstream project.

If you reuse code directly from an upstream repository, you must follow that upstream project's license independently of this repository's MIT License.
