# Changelog

## [1.0.0-rc.1]

First release candidate. Final **1.0.0** follows once the manual checklist (PDF engines, GUI, exe) has
been run on a real workspace.

### Architecture
- The single 3,000-line file is now the `pageout/` package: `core/` (config, naming, pipeline, IR,
  resolver, cache, assets, secrets, database exports), `sources/` (Notion API, Notion-JSON -> IR, export zip),
  `renderers/` (html, pdf, markdown, txt, docx, latex), `ocr/gemini.py`, `plugins/hooks.py`, `gui/`, `cli.py`.
- All renderers read a typed **IR** (`core/ir.py`); only `sources/` knows Notion's JSON. The JSON export is the
  one deliberate exception (a lossless dump of the source data).
- `core.pipeline.export(config) -> Result` is the single entry point for GUI and CLI.
- `notion_exporter.py` stays as a launcher, so shortcuts and build scripts keep working.

### New
- **Links:** links and mentions between exported pages become relative links (HTML, Markdown; Obsidian
  `[[wikilinks]]`); `link_to_page` blocks render as links.
- **Images:** SHA-256 de-duplication; expired Notion image URLs are re-fetched automatically; LaTeX export now
  includes real images (webp/gif converted to PNG), with a "comments only" option.
- **Incremental sync:** unchanged pages (same `last_edited_time` and settings) are skipped; `--force` / "Force
  full re-export" overrides. Automatically off for combined files, inline sub-pages and raw image export.
- **CLI:** `pageout export <url> --format pdf,md`, settings files (`pageout.yaml` / `.json` / `.toml`), `--set KEY=VALUE`,
  `init-config`, exit codes 0 / 1 (problems) / 2 (usage) / 130 (cancelled).
- **Hooks:** `filter_page`, `transform_node`, `transform_frontmatter` (see `examples/hooks_example.py`).
- **Markdown presets:** GFM, Vanilla, Obsidian.
- **Database extras:** index page, table of properties, CSV.
- **Offline math:** KaTeX is bundled (no internet needed); CDN / none still selectable.
- **Notion export zip** as an offline source (experimental, Markdown only).
- **Secrets:** tokens and the Gemini key are stored in the OS keyring; plain text only if explicitly allowed.
  Old plain-text configs are migrated automatically. Tokens are redacted from logs and error messages.
- **Quality:** 80+ pytest tests (golden files, fixtures, no network), ruff, mypy on `core/`, GitHub Actions CI
  (Windows + Linux) and a tag-triggered release workflow with SHA-256 checksums.

### Fixed
- LaTeX: callouts with an emoji produced an empty `\textbf{}`; toggles lost their title; database blocks vanished.
- Importing the module no longer crashes when Tkinter is missing (the GUI is imported only when it is started).

### Behaviour changes to be aware of
- Word export: links to Notion-internal pages are no longer written as broken hyperlinks (plain text instead).
- Unknown block types that carry rich text are rendered as paragraphs.
- Config `_ver` is now 3 (plain-text secrets are moved into the keyring on first start).

## [1.0.0-beta.1]
Initial public beta.
