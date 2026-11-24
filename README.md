# Notion Exporter

Export Notion pages to **PDF, HTML, Markdown, Text, Word and JSON**, and save
their **images with custom names**. Desktop app (Tkinter).

## Features
- Database, single page, or several URLs at once
- Two PDF engines: **API** (fast, no login) and **Browser** (exact Notion look)
- Choose which pages and which properties to export
- File and image naming templates: `{date:%Y-%m-%d} {title:40}`, `{page}_{n}`, any property
- Sub-pages: skip, inline, or separate files
- Links: keep, remove, or remove only Notion-internal links
- Merged PDF with bookmarks, combined HTML/Markdown, resume, retries
- Page size, margins, scale, page numbers, custom CSS

## Install
```bash
pip install -r requirements.txt
playwright install chromium
python notion_exporter.py
```

## Notion setup
1. Create an integration at https://www.notion.so/my-integrations and copy the token.
2. In Notion, open your page/database > **...** > **Connections** > add your integration.
3. Paste the token and the page/database URL into the app.

## Notes
- The token is never saved unless you tick "Remember token" (stored as plain text).
- Image links from Notion expire after about an hour, so images are embedded or saved locally.

## License
MIT
