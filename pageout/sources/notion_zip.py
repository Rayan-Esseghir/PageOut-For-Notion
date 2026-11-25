"""Offline source: a Notion "Export -> Markdown & CSV" zip (no token, no network).

EXPERIMENTAL: reads the Markdown files only (CSV database files are ignored). Page links between
files of the export become real page links, so link rewriting works offline as well.
"""

import hashlib
import io
import posixpath
import re
import zipfile
from urllib.parse import unquote

from pageout.core.ir import Asset, Block, Document, Media, Property, Span
from pageout.sources.base import BaseSource

_ID_RE = re.compile(r"\s([0-9a-f]{32})(?:\.md)?$", re.I)
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

    def _load(self, zf, files, mds):
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info)
            name = info.filename.replace("\\", "/")
            if name.lower().endswith(".zip"):  # Notion nests "...-Part-1.zip"
                self._load(zipfile.ZipFile(io.BytesIO(data)), files, mds)
            elif name.lower().endswith(".md"):
                mds[name] = data.decode("utf-8", "replace")
            elif name.lower().endswith(_IMG_EXT):
                files[name] = data

    def documents(self):
        files, mds = {}, {}
        with zipfile.ZipFile(self.path) as zf:
            self._load(zf, files, mds)
        docs = []
        for name, text in sorted(mds.items()):
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
            title = title or (base[: idm.start()] if idm else base)
            body = _Parser(lines[k:], posixpath.dirname(name), files).parse()
            docs.append(
                Document(
                    id=pid,
                    title=title,
                    blocks=body,
                    properties=props,
                    source={"id": pid, "title": title, "properties": {}, "blocks": []},
                )
            )
        return docs
