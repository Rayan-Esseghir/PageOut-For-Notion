"""Offline source: a Notion "Export -> Markdown & CSV" zip (no token, no network).

Reads Markdown files and CSV database exports. Page links between files of the export become
real page links, so link rewriting works offline as well.

CSV files are named like "DatabaseName-<id>.csv" and contain database rows that are
converted to Document objects for export.
"""

import csv
import hashlib
import io
import posixpath
import re
import zipfile
from urllib.parse import unquote

from pageout.core.ir import Asset, Block, Document, Media, Property, Span
from pageout.sources.base import BaseSource

_ID_RE = re.compile(r"([0-9a-f]{32})", re.I)  # Match 32-hex ID
_CSV_ID_RE = re.compile(r".*-([0-9a-f]{32})\.csv$", re.I)  # CSV: Name-<id>.csv
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
_INLINE = re.compile(
    r"(?P<code>`[^`]+`)|(?P<bold>\*\*[^*]+\*\*)|(?P<strike>~~[^~]+~~)|(?P<ital>\*[^*\s][^*]*\*)"
    r"|(?P<math>\$[^$\n]+\$)|(?P<link>\[[^\]]*\]\([^)]+\))"
)


def _spans(text):
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(Span(text[pos : m.start()]))
        g, tok = m.lastgroup, m.group()
        if g == "code":
            out.append(Span(tok[1:-1], code=True))
        elif g == "bold":
            out.append(Span(tok[2:-2], bold=True))
        elif g == "strike":
            out.append(Span(tok[2:-2], strike=True))
        elif g == "ital":
            out.append(Span(tok[1:-1], italic=True))
        elif g == "math":
            out.append(Span(tok[1:-1], equation=tok[1:-1]))
        else:
            label, href = re.match(r"\[([^\]]*)\]\(([^)]+)\)", tok).groups()
            href = unquote(href)
            idm = re.search(r"([0-9a-f]{32})(?:\.md)?$", href.replace("-", ""), re.I)
            internal = not re.match(r"[a-z]+://", href)
            out.append(Span(label, href=href, page_id=idm.group(1).lower() if (idm and internal) else None))
        pos = m.end()
    if pos < len(text):
        out.append(Span(text[pos:]))
    return out


class _Parser:
    def __init__(self, lines, md_dir, files):
        self.lines, self.i, self.md_dir, self.files = lines, 0, md_dir, files

    def image_asset(self, ref):
        ref = unquote(ref)
        if re.match(r"[a-z]+://", ref):
            return None
        path = posixpath.normpath(posixpath.join(self.md_dir, ref))
        data = self.files.get(path)
        if data is None:
            return None
        ext = posixpath.splitext(path)[1].lower() or ".png"
        return Asset(url=ref, bytes=data, ext=ext)

    def parse(self, until=None):
        blocks, para = [], []

        def flush():
            if para:
                blocks.append(Block("paragraph", text=_spans("\n".join(para))))
                para.clear()

        while self.i < len(self.lines):
            ln = self.lines[self.i]
            s = ln.strip()
            if until and s == until:
                self.i += 1
                break
            if not s:
                flush()
                self.i += 1
                continue
            m = re.match(r"^```(\w*)\s*$", s)
            if m:
                flush()
                code = []
                self.i += 1
                while self.i < len(self.lines) and not self.lines[self.i].strip().startswith("```"):
                    code.append(self.lines[self.i])
                    self.i += 1
                self.i += 1
                blocks.append(Block("code", language=m.group(1), text=[Span("\n".join(code))]))
                continue
            m = re.match(r"^(#{1,6})\s+(.*)$", s)
            if m:
                flush()
                blocks.append(Block("heading", level=min(len(m.group(1)), 3), text=_spans(m.group(2))))
                self.i += 1
                continue
            if re.match(r"^(-{3,}|\*{3,})$", s):
                flush()
                blocks.append(Block("divider"))
                self.i += 1
                continue
            m = re.match(r"^\$\$\s*(.*?)\s*\$\$$", s)
            if m:
                flush()
                blocks.append(Block("equation", expression=m.group(1)))
                self.i += 1
                continue
            m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
            if m:
                flush()
                media = Media("image", unquote(m.group(2)), _spans(m.group(1)) if m.group(1) else [])
                media.asset = self.image_asset(m.group(2))
                blocks.append(Block("image", media=media))
                self.i += 1
                continue
            if s.startswith(">"):
                flush()
                q = []
                while self.i < len(self.lines) and self.lines[self.i].strip().startswith(">"):
                    q.append(self.lines[self.i].strip().lstrip(">").strip())
                    self.i += 1
                blocks.append(Block("quote", text=_spans("\n".join(q))))
                continue
            if s.startswith("<details"):
                flush()
                self.i += 1
                summary = []
                while self.i < len(self.lines) and "</summary>" not in self.lines[self.i]:
                    summary.append(self.lines[self.i])
                    self.i += 1
                head = (
                    re.sub(r"</?summary>|<details>", "", "".join(summary) + self.lines[self.i]).strip()
                    if self.i < len(self.lines)
                    else ""
                )
                self.i += 1
                blocks.append(Block("toggle", text=_spans(head), children=self.parse(until="</details>")))
                continue
            if "|" in s and self.i + 1 < len(self.lines) and re.match(r"^\s*\|?\s*:?-{3,}", self.lines[self.i + 1]):
                flush()
                rows = []
                while self.i < len(self.lines) and "|" in self.lines[self.i]:
                    row = self.lines[self.i].strip().strip("|")
                    if not re.match(r"^\s*:?-{3,}", row):
                        rows.append([_spans(c.strip()) for c in re.split(r"(?<!\\)\|", row)])
                    self.i += 1
                blocks.append(Block("table", rows=rows, col_header=True))
                continue
            m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", ln)
            if m:
                flush()
                indent = len(m.group(1).replace("\t", "    "))
                kind = "numbered" if m.group(2)[0].isdigit() else "bulleted"
                body, checked = m.group(3), False
                t = re.match(r"^\[( |x|X)\]\s+(.*)$", body)
                if t:
                    kind, checked, body = "todo", t.group(1).lower() == "x", t.group(2)
                blk = Block(kind, text=_spans(body), checked=checked)
                blk._indent = indent  # type: ignore[attr-defined]
                blocks.append(blk)
                self.i += 1
                continue
            para.append(ln.rstrip())
            self.i += 1
        flush()
        return _nest_lists(blocks)


def _nest_lists(blocks):
    """Turn flat list items (with a temporary indent) into nested children."""
    out, stack = [], []
    for b in blocks:
        ind = getattr(b, "_indent", None)
        if ind is None:
            out.append(b)
            stack = []
            continue
        while stack and stack[-1][0] >= ind:
            stack.pop()
        (stack[-1][1].children if stack else out).append(b)
        stack.append((ind, b))
    return out


class ZipSource(BaseSource):
    name = "Notion export zip"

    def __init__(self, path):
        self.path = path

    def _load(self, zf, files, csvs):
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info)
            name = info.filename.replace("\\", "/")
            if name.lower().endswith(".zip"):  # Notion nests "...-Part-1.zip"
                self._load(zipfile.ZipFile(io.BytesIO(data)), files, csvs)
            elif name.lower().endswith(".md"):
                # Store as (filename, content) tuple
                csvs[name] = ("md", data.decode("utf-8", "replace"))
            elif name.lower().endswith(".csv"):
                # Store CSV data as (filename, csv_data) tuple
                csvs[name] = ("csv", data)
            elif name.lower().endswith(_IMG_EXT):
                files[name] = data

    def _parse_csv(self, csv_data):
        """Parse CSV data from Notion export and return list of property dicts."""
        props_list = []
        try:
            text = csv_data.decode("utf-8-sig", "replace")  # UTF-8 with BOM
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                # Convert row dict to Property list
                props = []
                for key, val in row.items():
                    if key:  # Skip empty keys
                        props.append(Property(key.strip(), "text", val.strip() if val else ""))
                if props:
                    props_list.append(props)
        except Exception:
            pass
        return props_list

    def documents(self):
        files, docs_data = {}, {}
        with zipfile.ZipFile(self.path) as zf:
            self._load(zf, files, docs_data)

        docs = []

        # Process Markdown files
        for name, (ftype, content) in sorted(docs_data.items()):
            if ftype != "md":
                continue
            text = content
            lines = text.replace("\r\n", "\n").split("\n")
            title, props, k = "", [], 0
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and lines[k].startswith("# "):
                title = lines[k][2:].strip()
                k += 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            while k < len(lines) and re.match(r"^[^:\n|#>`-][^:\n]*: .+$", lines[k]):  # property lines
                key, _, val = lines[k].partition(": ")
                props.append(Property(key.strip(), "text", val.strip()))
                k += 1
            base = posixpath.splitext(posixpath.basename(name))[0]
            idm = _ID_RE.search(base)
            pid = idm.group(1).lower() if idm else hashlib.sha1(name.encode()).hexdigest()[:32]
            title = title or (base[: idm.start()].strip() if idm else base).rstrip(".- ")
            md_dir = posixpath.dirname(name)
            body = _Parser(lines[k:], md_dir, files).parse()
            docs.append(
                Document(
                    id=pid,
                    title=title,
                    blocks=body,
                    properties=props,
                    source={"id": pid, "title": title, "properties": {}, "blocks": []},
                )
            )

        # Process CSV files (database exports)
        for name, (ftype, data) in sorted(docs_data.items()):
            if ftype != "csv":
                continue
            # Extract database ID from filename: "DatabaseName-<id>.csv"
            idm = _CSV_ID_RE.search(name)
            db_id = idm.group(1).lower() if idm else hashlib.sha1(name.encode()).hexdigest()[:32]
            base = posixpath.splitext(posixpath.basename(name))[0]
            title = base.rsplit("-", 1)[0] if "-" in base else base

            # Parse CSV rows into properties
            rows_props = self._parse_csv(data)

            # Create a Document for each row in the database
            for idx, row_props in enumerate(rows_props, 1):
                row_title = row_props[0].text if row_props else f"Row {idx}"
                row_id = f"{db_id[:16]}{idx:016x}"[:32]  # Generate unique ID for each row
                docs.append(
                    Document(
                        id=row_id,
                        title=row_title,
                        blocks=[],
                        properties=row_props,
                        source={"id": row_id, "title": row_title, "properties": {}, "blocks": []},
                    )
                )

        return docs
