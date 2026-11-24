# PageOut for Notion

Export Notion pages to **PDF, HTML, Markdown, Text, Word and JSON**, and save
their **images with custom names**. Desktop app (Tkinter) · v4.

---

## Features

| Category | Details |
|---|---|
| **Sources** | Database, single page, or multiple URLs at once |
| **Formats** | PDF, HTML, Markdown, Text, Word (.docx), JSON, raw Images |
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
pip install notion-client playwright pypdf python-docx pillow
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
pip install pyinstaller pillow
# (notion-client, playwright, pypdf, python-docx already installed)
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
Resource files (`icon.ico`, `icon.png`, `icon.jpg`) are automatically bundled.
All settings and config are stored in `%USERPROFILE%\.notion_pdf_exporter\`.

### Playwright / Chromium and the .exe

The **API engine** (default) uses no browser — the `.exe` works standalone.

The **Browser engine** (exact Notion look) requires Chromium:

| Option | How |
|---|---|
| **Install on target PC** | `playwright install chromium` |
| **Portable Chromium** | Copy the `~\.cache\ms-playwright` folder; before launch set `PLAYWRIGHT_BROWSERS_PATH=<parent folder>` |

> Bundling Chromium *inside* the `.exe` with `--add-binary` adds ~300 MB.
> The build scripts intentionally skip this; use the portable-folder approach instead.

### Manual PyInstaller command

```powershell
pyinstaller `
  --onefile `
  --windowed `
  --name "PageOut-for-Notion" `
  --icon icon.ico `
  --add-data "icon.ico;." `
  --add-data "icon.png;." `
  --add-data "icon.jpg;." `
  --hidden-import notion_client `
  --hidden-import playwright `
  --hidden-import playwright.sync_api `
  --hidden-import pypdf `
  --hidden-import docx `
  --hidden-import PIL `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageDraw `
  --hidden-import PIL.ImageFont `
  --hidden-import PIL.ImageTk `
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
