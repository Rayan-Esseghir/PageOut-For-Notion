"""Intermediate Representation (IR).

Notion's JSON is understood in exactly one place (sources/notion_ir.py). Everything after
that (resolver, hooks, renderers) works on these plain dataclasses.

Exception by design: the JSON *format* is a lossless dump of the source data, so the JSON
renderer reads ``Document.source`` (the opaque payload kept by the source adapter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

_Bytes = bytes  # the Asset field named 'bytes' shadows the builtin inside the class body

# Block kinds used by the converters and renderers
LIST_KINDS = ("bulleted", "numbered", "todo")
MEDIA_KINDS = ("video", "file", "pdf", "audio")
BOOKMARK_KINDS = ("bookmark",)  # bookmark / embed / link_preview


@dataclass
class Span:
    """One run of rich text. ``equation`` is set for inline math (``text`` is then the plain text)."""

    text: str = ""
    bold: bool = False
    italic: bool = False
    strike: bool = False
    underline: bool = False
    code: bool = False
    color: str = "default"
    href: Optional[str] = None
    equation: Optional[str] = None
    page_id: Optional[str] = None  # 32-hex id when href / mention points at a Notion page


RichText = list


def plain_text(rt: list) -> str:
    return "".join(s.text for s in rt or [])


@dataclass
class Asset:
    """A downloaded / processed image (runtime data filled in by the pipeline)."""

    url: str
    caption: str = ""
    n: Any = 0  # int, or "cover"
    bytes: Optional[_Bytes] = None
    ext: str = ".png"
    path: Optional[str] = None
    opt_bytes: Optional[_Bytes] = None
    opt_mime: str = "image/jpeg"
    sha256: str = ""
    block_id: str = ""  # lets the pipeline re-fetch an expired URL


@dataclass
class Media:
    kind: str  # image | video | file | pdf | audio
    url: str = ""
    caption: list = field(default_factory=list)
    name: str = ""
    external: bool = False
    block_id: str = ""
    asset: Optional[Asset] = None

    def display_name(self) -> str:
        return plain_text(self.caption) or self.name or self.url.split("?")[0].rsplit("/", 1)[-1] or self.kind


@dataclass
class Property:
    name: str
    type: str
    text: str = ""  # already-formatted text for non-date types
    date: str = ""  # ISO date (first 10 chars) for date-like types


@dataclass
class Block:
    kind: str
    id: str = ""
    text: list = field(default_factory=list)  # rich text
    children: list = field(default_factory=list)  # list[Block]
    level: int = 0  # heading level 1-3
    checked: bool = False  # todo
    color: str = "default"
    icon: str = ""  # callout emoji ("" when none)
    language: str = ""  # code
    caption: list = field(default_factory=list)  # code caption
    expression: str = ""  # block equation
    url: str = ""  # bookmark / embed
    media: Optional[Media] = None
    rows: list = field(default_factory=list)  # table: list[list[RichText]]
    col_header: bool = False
    row_header: bool = False
    title: str = ""  # child_page / child_database
    sub: Optional["Document"] = None  # inlined sub-page
    target_id: str = ""  # link_to_page


@dataclass
class Document:
    id: str
    title: str
    blocks: list = field(default_factory=list)
    properties: list = field(default_factory=list)  # list[Property]
    icon_emoji: str = ""
    icon_url: str = ""
    cover_url: str = ""
    created: str = ""
    edited: str = ""
    source: dict = field(default_factory=dict)  # opaque payload for the JSON renderer


def walk(blocks: list, subs: bool = True) -> Iterator[Block]:
    """Depth-first walk over blocks (children, and inlined sub-pages when ``subs``)."""
    for b in blocks:
        yield b
        yield from walk(b.children, subs)
        if subs and b.sub is not None:
            yield from walk(b.sub.blocks, subs)
