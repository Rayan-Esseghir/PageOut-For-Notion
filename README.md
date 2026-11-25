<p align="center">
  <img src="assets/banner.jpg" alt="PageOut for Notion" width="100%">
</p>

# PageOut for Notion

Export Notion pages to **PDF, HTML, Markdown, Text, Word, JSON and LaTeX**, and save
their **images with custom names**. Desktop app (Tkinter) **and command line** · **v1.0.0-rc.1 (Release Candidate)**

---

## Features

| Category | Details |
|---|---|
| **Sources** | Database, single page, or multiple URLs at once |
| **Formats** | PDF, HTML, Markdown, Text, Word (.docx), JSON, LaTeX (.tex), raw Images |
| **Math OCR** | Optional Gemini Vision: whiteboard photos → LaTeX (your own API key) |
| **PDF engines** | **API** (fast, no login) · **Browser** (pixel-perfect Notion look) |
| **Properties** | Choose which properties to show; four layout styles |
| **Naming** | File & image naming templates: `{date:%Y-%m-%d} {title:40}`, `{page}_{n}`, any property |
| **Sub-pages** | Skip · inline in parent · separate files (recursive, configurable depth) |
| **Links** | Keep all · remove all · remove only Notion-internal |
| **Images** | Embed, save locally, or keep Notion link; maximize, one-per-page, custom captions |
| **Styling** | Font family/size, line spacing, text/heading alignment, title separator |
| **Cover page** | Dedicated header page (title + icon + properties) followed by a page break |
| **Page icon** | Show Notion emoji/icon · hide · use custom local image file |
| **Page numbers** | Bottom Center / Bottom Right / Top Right; `Page X of Y` or `X` |
| **Date formats** | YYYY-MM-DD, DD/MM/YYYY, MMM DD YYYY, Relative, ISO 8601, or any `strftime` |
| **Links** | Links/mentions between exported pages become relative links that work offline (HTML, Markdown, Obsidian `[[wikilinks]]`) |
| **Sync** | Incremental: unchanged pages are skipped on the next run (`--force` to redo) |
| **Markdown** | GFM · Vanilla · Obsidian presets |
| **Databases** | Index page, table of properties, or CSV of all properties |
| **Offline** | Bundled KaTeX (math without internet); Notion export `.zip` as an offline source (experimental) |
| **Automation** | `pageout` CLI, `pageout.yaml`, Python hooks |
| **Other** | Merged PDF with bookmarks, combined HTML/Markdown, resume, retries |

---

## Install (run as Python script)

```bash
pip install -r requirements.txt
playwright install chromium        # only for the PDF engines
python notion_exporter.py          # GUI
python notion_exporter.py export <url> --format pdf,md --out ./export     # CLI
```

> **Pillow** (`pillow`) is needed only for the custom-icon feature; everything
> else works without it.

---

## Notion setup

1. Create an integration at <https://www.notion.so/my-integrations> and copy the **Internal Integration Token**.
2. In Notion open your page or database → **…** → **Connections** → add your integration.
3. Paste the token and the page/database URL into the app.

---

> ### Release candidate
> Every feature is implemented and covered by automated tests (80+, no network needed). The PDF engines,
> the GUI on your machine and the built `.exe` still need the manual checklist below before the final
> **1.0.0**. Your Notion data is never modified (the app only reads it). If something goes wrong, copy the text
> from the log box (or the CLI output) and report it. Secrets are redacted from logs.

## What's new in 1.0.0-rc.1

See [CHANGELOG.md](CHANGELOG.md). Short version: new `pageout/` package with a typed IR, offline link
rewriting, incremental sync, CLI + hooks, Markdown presets, database exports, bundled KaTeX, real images in LaTeX,
keyring-based secrets.

## Command line

```bash
pageout export https://www.notion.so/<db-or-page> -f pdf,md,html -o ./export      # python -m pageout ... also works
pageout export -c pageout.yaml                       # settings file (pageout init-config writes an example)
pageout export <url> -f md --md-preset obsidian --db-export index --sub-pages inline
pageout export --zip notion-export.zip -f html,md    # offline, no token
pageout export <url> -f md --force                   # ignore the incremental cache
pageout export <url> -f md --set margin_mm=10 --set math_engine=None
```

Settings are layered (later wins): defaults < `~/.notion_pdf_exporter/config.json` < `pageout.yaml` < flags.
The token comes from `--token`, `NOTION_TOKEN`, or the OS keyring (never from the yaml file).
Exit codes: `0` ok · `1` some pages failed · `2` usage/config error · `130` cancelled.
The windowed `.exe` is the GUI; for the CLI use `python -m pageout` or build with `.\build_exe.ps1 -Console`.

## Incremental sync

After an export the app writes `.pageout_cache.json` into the output folder. On the next run a page is skipped
when its `last_edited_time`, your settings and its output files are unchanged. It is switched off automatically
for combined files, inline sub-pages (a sub-page edit does not change the parent's timestamp) and raw image
export. Tick **Force full re-export** (or `--force`) to redo everything.

## Hooks

```python
def filter_page(page):                 # False -> skip the page
def transform_node(block, doc):        # return the block, a new one, or None to drop it
def transform_frontmatter(fm, doc):    # Markdown front matter dict
```
Use `--hooks my_hooks.py` or `hooks:` in `pageout.yaml`. See `examples/hooks_example.py`.
Hook files are ordinary Python: only load files you trust.

## Project layout

```
pageout/core/        config, naming, pipeline, ir, resolver, cache, assets, secrets, database
pageout/sources/     notion_api (client, rate limit), notion_ir (JSON -> IR), notion_zip (offline)
pageout/renderers/   html, pdf, markdown, txt, docx, latex
pageout/ocr/         gemini (Math OCR)      pageout/plugins/  hooks      pageout/gui/  Tkinter app
tests/               pytest: fixtures (recorded-shape JSON), golden files, unit + feature tests
```
Only `sources/` knows Notion's JSON; renderers read the IR in `core/ir.py`. The GUI and the CLI both call
`core.pipeline.export()`.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # no network, no browser, no Notion token needed
ruff check pageout tests && ruff format --check pageout tests && mypy
```
Golden files: `tests/golden/`. After an *intended* output change: `UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`
(PowerShell: `$env:UPDATE_GOLDEN=1`) and review `git diff tests/golden`.

### Manual checklist before 1.0.0
1. GUI: export a real page to PDF (API engine), HTML, Markdown, Word, LaTeX; open each.
2. PDF **Browser** engine with a private page (`playwright install chromium`, log in once).
3. A database with 20+ pages: run twice, the second run must say "unchanged, skipped".
4. A page with an image older than an hour: images must still export (expired links are re-fetched).
5. `.\build_exe.ps1`, start `dist\PageOut-for-Notion.exe`, export once, check the icon.

## Highlights

- **8 guided tabs** (Source → Pages → Formats → Design → Images → PDF → LaTeX & AI → Output) with hints under every option.
- **Style presets** and **45+ fonts** (any font installed on your PC, plus optional Google Fonts such as Inter, Lora, Cairo, Amiri). Arabic text flows right-to-left automatically.
- **Prettier PDF/HTML**: accent color, nicer tables, callouts, code blocks, quotes, KaTeX math rendering.
- **Faster export**: pages/images are fetched in parallel while the previous page renders; big photos are shrunk inside PDF/Word files.
- LaTeX: images are saved next to the `.tex` and included (webp/gif are converted to PNG); "Comments only" is available.

## Changing the app icon

1. Replace `icon.ico` (and `icon.png`) in the project folder.
2. Delete the old `build`, `dist` folders and `PageOut-for-Notion.spec`.
3. Run `.\build_exe.ps1` again.
4. If Explorer still shows the old icon, it is Windows' icon cache: copy the exe to another folder or run `ie4uinit.exe -show`.

---

## LaTeX & Gemini Math OCR

Tick **LaTeX (.tex)** on the Formats tab. Output compiles with `pdflatex`
(for Arabic/CJK text use `xelatex`). Emoji are removed automatically; images
other than PNG/JPG/PDF are converted to PNG.

For whiteboard photos, open the **LaTeX & OCR** tab, paste your own Gemini key
(<https://aistudio.google.com/>) and tick *Scan images with Gemini Math OCR*.
The model name box is editable, so you can type any current Gemini model.
The key is stored in the OS keyring (plain text in `config.json` only if you allow it).

---

## New in v4 — Quick Guide

### Custom App Icon
Place `icon.ico` (Windows, recommended), `icon.png`, or `icon.jpg` next to
`notion_exporter.py` (or inside the `.exe`'s folder). The app picks the first
one it finds and falls back to a programmatically drawn "N" icon via Pillow.

### Styling Tab
- **Font family** – Sans-serif / Serif / Monospace applied to all HTML & API-PDF exports.
- **Base font size** – pixels; default 16.
- **Line spacing** – unitless multiplier; default 1.6.
- **Heading alignment** – Left or Center.
- **Title separator** – thin rule under the page title.

### Page Icon / Emoji
*Styling → Page Icon / Emoji*  
Choose **Show page icon** (default), **Hide icon**, or **Custom icon file**.  
When *Custom icon file* is selected, pick any local PNG/JPEG/SVG and it
replaces the Notion icon in every export.

### Cover / Header Page
*Styling → Cover / Header Page*  
Tick **"Create dedicated cover/header page"** to put only the title, icon and
properties on page 1, then break to page 2 for the actual content.

### Properties Tab — Layout Styles
| Style | Looks like |
|---|---|
| **Notion Table** | Clean two-column grid under the title (default) |
| **Inline Pills** | Compact horizontal `Key: Value` badges |
| **Minimalist List** | Subtle `Key    Value` lines |
| **Hidden** | Properties excluded from the exported body |

### Date Formatting
*Properties Tab → Property date format*  
Presets: `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `MMM DD, YYYY`,
`MMMM D, YYYY`, `D MMM YYYY`, `ISO 8601`, `Relative` (e.g. "3 days ago").  
Or type any `strftime` pattern directly (e.g. `%d.%m.%Y`).

### Image Layout (Images Tab)
| Option | Effect |
|---|---|
| **Maximize images** | `width: 100%` on every image |
| **One image per page** | Page break inserted after each image |
| **Show image filenames** | Caption shown even when Notion has no caption |
| **Caption format** | Template: `{name}`, `{name}.{ext}`, `Figure {n}: {name}`, `{original}`, `{caption}` |

### Page Numbers (PDF Tab)
- **Position**: Bottom Center · Bottom Right · Top Right
- **Format**: `Page X of Y` · `X`

---

## Build a standalone `.exe` (Windows)

### Prerequisites
```powershell
pip install -r requirements.txt pyinstaller
```

### Build with PowerShell (recommended)
```powershell
cd C:\Projects\Notion-Exporter
.\build_exe.ps1            # tests are not run here; CI runs them before every release
```

### Build with Command Prompt
```cmd
cd C:\Projects\Notion-Exporter
build_exe.bat
```

The output is `dist\PageOut-for-Notion.exe`.  
`icon.ico` is embedded as the exe icon and bundled for the window/taskbar icon.
Use `.\build_exe.ps1 -Console` (or `build_exe.bat console`) for a debug build that shows errors.
All settings and config are stored in `%USERPROFILE%\.notion_pdf_exporter\`.

### Playwright / Chromium and the .exe

The **API engine** (default) uses no browser — the `.exe` works standalone.

The **Browser engine** (exact Notion look) requires Chromium:

| Option | How |
|---|---|
| **Install on target PC** | `playwright install chromium` |
| **Portable Chromium** | Copy `~\AppData\Local\ms-playwright` next to the `.exe` and rename it `browsers` (auto-detected), or set `PLAYWRIGHT_BROWSERS_PATH` |

> Bundling Chromium *inside* the `.exe` with `--add-binary` adds ~300 MB.
> The build scripts intentionally skip this; use the portable-folder approach instead.

### Manual PyInstaller command

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name PageOut-for-Notion --icon icon.ico `
  --add-data "icon.ico;." --add-data "icon.png;." --add-data "pageout/assets;pageout/assets" `
  --collect-submodules pageout --collect-all keyring --hidden-import yaml `
  --collect-all playwright --collect-all google.genai --collect-data docx `
  --hidden-import notion_client --hidden-import pypdf --hidden-import PIL.ImageTk `
  notion_exporter.py
```

---

## Notes

- The token is **never saved** unless you tick "Remember on this PC": it then goes to the OS keyring (Windows Credential Manager). Plain text in `~/.notion_pdf_exporter/config.json` only if no keyring exists *and* you tick "Allow plain-text storage". Old plain-text configs are migrated on first start.
- Notion image URLs expire after ~1 hour; the exporter re-fetches a fresh link automatically when a download is refused. **Embed** or **Save locally** are still the most reliable.
- When using `--onefile`, PyInstaller extracts resources to a temp `_MEIPASS` folder at runtime; `resource_path()` in the script handles this automatically.

---

## License

MIT
