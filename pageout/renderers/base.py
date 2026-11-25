"""Rendering context shared by the HTML / Markdown / Text / Word / LaTeX writers."""

import base64
import os
import re
from pathlib import Path
from urllib.parse import quote

from pageout.core.assets import data_uri
from pageout.core.config import IMG_MODES, LINK_MODES

INTERNAL_RE = re.compile(r"^(/|https?://(www\.)?notion\.(so|site))", re.I)


class R:
    """Per-file rendering context.

    ``resolver`` / ``current`` (optional) enable link rewriting: links to pages that are exported
    too become relative links to the exported file of the same format.
    """

    def __init__(self, cfg, kind, base_dir=None, resolver=None, current=None):
        self.cfg, self.kind, self.base_dir = cfg, kind, base_dir
        self.expand = bool(cfg.get("expand_toggles", True))
        self.links = cfg.get("links", LINK_MODES[0])
        self.resolver, self.current = resolver, current
        self.md_preset = cfg.get("md_preset", "GFM")

    def keep_link(self, href):
        if not href:
            return False
        if self.links == LINK_MODES[1]:
            return False
        if self.links == LINK_MODES[2]:
            return not INTERNAL_RE.match(href)
        return True

    def local_link(self, span):
        """Relative path to the exported copy of the page a span links to (or None)."""
        if not (self.resolver and self.current and span.page_id) or self.links == LINK_MODES[1]:
            return None
        return self.resolver.link(span.page_id, self.kind, self.current)

    def page_link(self, page_id):
        """(relative href, title) for a link_to_page block whose target is exported too."""
        if not (self.resolver and self.current) or self.links == LINK_MODES[1]:
            return None
        href = self.resolver.link(page_id, self.kind, self.current)
        return (href, self.resolver.title(page_id)) if href else None

    def wikilink(self, span):
        """Obsidian [[wikilink]] target (file name without extension) or None."""
        if not (self.resolver and span.page_id) or self.links == LINK_MODES[1]:
            return None
        it = self.resolver.item(span.page_id)
        return it.base if it is not None else None

    def href_for(self, span):
        """Final href for a rich-text span, or None when the link must not be emitted."""
        if not span.href and not span.page_id:
            return None
        local = self.local_link(span)
        if local:
            return local
        return span.href if self.keep_link(span.href) else None

    def img_src(self, img):
        path, data, url = img.path, img.bytes, img.url
        handling = self.cfg.get("img_handling", IMG_MODES[0])
        if self.kind == "pdf":
            if img.opt_bytes:
                return f"data:{img.opt_mime or 'image/jpeg'};base64," + base64.b64encode(img.opt_bytes).decode()
            if path:
                return Path(path).resolve().as_uri()
            return data_uri(img) if data else url
        if handling == IMG_MODES[2]:
            return url
        if handling == IMG_MODES[0] and data and self.kind == "html":
            return data_uri(img)
        if path and self.base_dir:
            rel = os.path.relpath(path, self.base_dir).replace(os.sep, "/")
            return quote(rel, safe="/")
        if data and self.kind == "html":
            return data_uri(img)
        return url
