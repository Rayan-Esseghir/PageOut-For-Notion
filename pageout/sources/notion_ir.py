"""Notion JSON -> IR.  The only place (besides the API client) that knows Notion's block schema."""

import re

from pageout.core.ir import Block, Document, Media, Property, Span
from pageout.sources.notion_api import plain, prop_to_text

_ID_RE = re.compile(r"([0-9a-fA-F]{32})(?:[?#].*)?$")
_INTERNAL_RE = re.compile(r"^(/|https?://(www\.)?notion\.(so|site))", re.I)

_SIMPLE = {"bulleted_list_item": "bulleted", "numbered_list_item": "numbered", "to_do": "todo"}


def page_id_from_href(href):
    """32-hex page id for Notion-internal links ('/<id>', notion.so/...<id>), else None."""
    if not href or not _INTERNAL_RE.match(href):
        return None
    path = re.split(r"[?#]", href, 1)[0].rstrip("/").replace("-", "")
    m = re.search(r"([0-9a-fA-F]{32})$", path)
    return m.group(1).lower() if m else None


def rich(rts):
    out = []
    for x in rts or []:
        a = x.get("annotations", {})
        href = x.get("href")
        page_id = page_id_from_href(href)
        if x.get("type") == "mention":
            m = x.get("mention") or {}
            if m.get("type") == "page":
                page_id = (m["page"].get("id") or "").replace("-", "").lower() or page_id
        out.append(
            Span(
                text=x.get("plain_text", ""),
                bold=bool(a.get("bold")),
                italic=bool(a.get("italic")),
                strike=bool(a.get("strikethrough")),
                underline=bool(a.get("underline")),
                code=bool(a.get("code")),
                color=a.get("color") or "default",
                href=href,
                page_id=page_id,
                equation=x["equation"]["expression"] if x.get("type") == "equation" else None,
            )
        )
    return out


def _url_of(d):
    return (d.get(d.get("type")) or {}).get("url", "")


def convert_block(b):
    t = b["type"]
    d = b.get(t) or {}
    kids = [convert_block(c) for c in b.get("children", [])]
    blk = Block(kind="skip", id=b.get("id", ""), children=kids)
    if t == "paragraph":
        blk.kind, blk.text = "paragraph", rich(d.get("rich_text"))
    elif t in ("heading_1", "heading_2", "heading_3"):
        blk.kind, blk.level, blk.text = "heading", int(t[-1]), rich(d.get("rich_text"))
    elif t in _SIMPLE:
        blk.kind, blk.text = _SIMPLE[t], rich(d.get("rich_text"))
        blk.checked = bool(d.get("checked"))
    elif t == "toggle":
        blk.kind, blk.text = "toggle", rich(d.get("rich_text"))
    elif t == "quote":
        blk.kind, blk.text = "quote", rich(d.get("rich_text"))
    elif t == "callout":
        ic = d.get("icon") or {}
        blk.kind, blk.text, blk.color = "callout", rich(d.get("rich_text")), d.get("color") or "default"
        blk.icon = ic.get("emoji", "") if ic.get("type") == "emoji" else ""
    elif t == "code":
        blk.kind, blk.text = "code", rich(d.get("rich_text"))
        blk.language, blk.caption = d.get("language", ""), rich(d.get("caption"))
    elif t == "divider":
        blk.kind = "divider"
    elif t == "equation":
        blk.kind, blk.expression = "equation", d.get("expression", "")
    elif t == "image":
        blk.kind = "image"
        blk.media = Media(
            "image", _url_of(d), rich(d.get("caption")), external=d.get("type") == "external", block_id=b.get("id", "")
        )
    elif t in ("video", "file", "pdf", "audio"):
        blk.kind = "media"
        blk.media = Media(
            t,
            _url_of(d),
            rich(d.get("caption")),
            name=d.get("name") or "",
            external=d.get("type") == "external",
            block_id=b.get("id", ""),
        )
    elif t in ("bookmark", "embed", "link_preview"):
        blk.kind, blk.url, blk.caption = "bookmark", d.get("url", ""), rich(d.get("caption"))
    elif t == "table":
        blk.kind = "table"
        blk.col_header, blk.row_header = bool(d.get("has_column_header")), bool(d.get("has_row_header"))
        blk.rows = [
            [rich(c) for c in k["table_row"]["cells"]] for k in b.get("children", []) if k["type"] == "table_row"
        ]
        blk.children = []
    elif t == "column_list":
        blk.kind = "column_list"
    elif t == "column":
        blk.kind = "column"
    elif t == "synced_block":
        blk.kind = "synced"
    elif t == "child_page":
        blk.kind, blk.title = "child_page", d.get("title", "")
        s = b.get("_sub")
        if s:
            blk.sub = Document(id=b.get("id", ""), title=s["title"], blocks=[convert_block(c) for c in s["tree"]])
    elif t == "child_database":
        blk.kind, blk.title = "child_database", d.get("title", "")
    elif t == "link_to_page":
        blk.kind = "link_to_page"
        tid = d.get(d.get("type"))
        blk.target_id = tid.replace("-", "").lower() if isinstance(tid, str) else ""
    elif t in ("table_of_contents", "breadcrumb", "table_row"):
        blk.kind = "skip"
    elif isinstance(d, dict) and "rich_text" in d:
        blk.kind, blk.text = "text", rich(d.get("rich_text"))
    return blk


def convert_property(name, prop):
    t = prop.get("type")
    v = prop.get(t)
    p = Property(name=name, type=t or "")
    if v is None:
        return p
    if t == "date":
        p.date = (v.get("start") or "")[:10]
    elif t in ("created_time", "last_edited_time"):
        p.date = str(v)[:10]
    elif t == "formula":
        ft = v.get("type")
        fv = v.get(ft)
        if isinstance(fv, dict):
            fv = fv.get("start")
        if fv is not None:
            if ft == "date":
                p.date = str(fv)[:10]
            else:
                p.text = str(fv)
    else:
        p.text = prop_to_text(prop)
    return p


def to_document(page, title, tree, item_id="", created="", edited=""):
    """Build a Document from a Notion page object (or None for sub-pages) and its raw block tree."""
    page = page or {}
    icon = page.get("icon") or {}
    icon_emoji = icon.get("emoji", "") if icon.get("type") == "emoji" else ""
    icon_url = ""
    if icon.get("type") in ("external", "file"):
        icon_url = (icon.get(icon["type"]) or {}).get("url", "")
    cv = page.get("cover") or {}
    doc = Document(
        id=item_id or page.get("id", ""),
        title=title or "Untitled",
        blocks=[convert_block(b) for b in tree or []],
        properties=[convert_property(k, v) for k, v in (page.get("properties") or {}).items()],
        icon_emoji=icon_emoji,
        icon_url=icon_url,
        cover_url=_url_of(cv) if cv else "",
        created=created or page.get("created_time", "")[:10],
        edited=edited or page.get("last_edited_time", "")[:10],
        source={
            "id": item_id or page.get("id", ""),
            "title": title or "Untitled",
            "properties": page.get("properties", {}),
            "blocks": tree or [],
        },
    )
    return doc


__all__ = ["rich", "convert_block", "convert_property", "to_document", "page_id_from_href", "plain"]
