<p align="center">
  <img src="assets/banner.jpg" alt="PageOut for Notion" width="100%">
</p>

# PageOut for Notion

Export Notion pages to **PDF, HTML, Markdown, Text, Word, JSON and LaTeX**, and save
their **images with custom names**. Desktop app (Tkinter) · **v1.0.0-beta.1 (Beta)**

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
| **Other** | Merged PDF with bookmarks, combined HTML/Markdown, resume, retries |

---

## Install (run as Python script)

```bash
pip install -r requirements.txt
playwright install chromium
python notion_exporter.py
```

> **Pillow** (`pillow`) is needed only for the custom-icon feature; everything
> else works without it.

---

## Notion setup

1. Create an integration at <https://www.notion.so/my-integrations> and copy the **Internal Integration Token**.
2. In Notion open your page or database → **…** → **Connections** → add your integration.
3. Paste the token and the page/database URL into the app.

---

> ### ⚠️ Beta software
> PageOut for Notion is in **Beta**: every main feature works, but the app is new and still being tested,
> so you may run into bugs. Your Notion data is never modified (the app only reads it), but please keep
> backups of anything important. If something goes wrong, copy the text from the log box at the bottom of
> the window and report it.
>
> **Alpha vs Beta:** *Alpha* = early version, features missing or unstable, tested by the developer only.
> *Beta* = feature-complete enough for real use, tested by real users, bugs are fixed before the final
> **1.0.0** release.

## What's new in the Beta

- Tick-box lists for pages and properties, working mouse-wheel scrolling on every tab, bigger log window.
- Font chooser that shows every font in its own typeface.
- Output styled like Notion itself (typography, callouts, quotes, code, tables, lists, property rows).
- Empty PDF pages are removed automatically (PDF tab). Default margin is now 20 mm.

## Highlights

- **8 guided tabs** (Source → Pages → Formats → Design → Images → PDF → LaTeX & AI → Output) with hints under every option.
- **Style presets** and **45+ fonts** (any font installed on your PC, plus optional Google Fonts such as Inter, Lora, Cairo, Amiri). Arabic text flows right-to-left automatically.
- **Prettier PDF/HTML**: accent color, nicer tables, callouts, code blocks, quotes, KaTeX math rendering.
- **Faster export**: pages/images are fetched in parallel while the previous page renders; big photos are shrunk inside PDF/Word files.
- LaTeX: images are written as `% [Image ...]` comments for now.

## Changing the app icon

1. Replace `icon.ico` (and `icon.png`) in the project folder.
2. Delete the old `build`, `dist` folders and `PageOut-for-Notion.spec`.
3. Run `.\build_exe.ps1` again.
4. If Explorer still shows the old icon, it is Windows' icon cache: copy the exe to another folder or run `ie4uinit.exe -show`.

---

## LaTeX & Gemini Math OCR

Tick **LaTeX (.tex)** on the Formats tab. Output compiles with `pdflatex`
(for Arabic/CJK text use `xelatex`). Emoji are removed automatically; images
other than PNG/JPG/PDF are skipped with a comment.

For whiteboard photos, open the **LaTeX & OCR** tab, paste your own Gemini key
(<https://aistudio.google.com/>) and tick *Scan images with Gemini Math OCR*.
The model name box is editable, so you can type any current Gemini model.
The key is stored in plain text in `~/.notion_pdf_exporter/config.json`.

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
.\build_exe.ps1
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
  --add-data "icon.ico;." --add-data "icon.png;." `
  --collect-all playwright --collect-all google.genai --collect-data docx `
  --hidden-import notion_client --hidden-import pypdf --hidden-import PIL.ImageTk `
  notion_exporter.py
```

---

## Notes

- The token is **never saved** unless you tick "Remember token" (stored plain-text in `~/.notion_pdf_exporter/config.json`).
- Notion image URLs expire after ~1 hour — use **Embed** or **Save locally** for reliable exports.
- When using `--onefile`, PyInstaller extracts resources to a temp `_MEIPASS` folder at runtime; `resource_path()` in the script handles this automatically.

---

## License

MIT
