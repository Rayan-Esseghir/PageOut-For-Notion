"""User hooks: tiny Python files that tweak an export without touching the app.

A hook file may define any of:

    def filter_page(page: dict) -> bool:                       # False -> skip this page
    def transform_node(block: Block, doc: Document):           # return block, a new Block, or None to drop it
    def transform_frontmatter(fm: dict, doc: Document) -> dict # Markdown front matter

``page`` has the keys title, date, created, edited, id, plus every property (lower-case name).
SECURITY: hook files are executed as normal Python. Only load files you trust.
"""

import importlib.util
from pathlib import Path


class Hooks:
    def __init__(self):
        self._filter, self._node, self._front = [], [], []
        self.sources = []

    @classmethod
    def from_files(cls, paths):
        h = cls()
        for p in paths or []:
            h.add_file(p)
        return h

    def add_file(self, path):
        path = Path(path).expanduser()
        spec = importlib.util.spec_from_file_location(f"pageout_hook_{len(self.sources)}", str(path))
        if spec is None or spec.loader is None:
            raise Exception(f"Cannot load hook file: {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.add_module(mod)
        self.sources.append(str(path))

    def add_module(self, mod):
        for attr, bucket in (
            ("filter_page", self._filter),
            ("transform_node", self._node),
            ("transform_frontmatter", self._front),
        ):
            fn = getattr(mod, attr, None)
            if callable(fn):
                bucket.append(fn)

    @property
    def active(self):
        return bool(self._filter or self._node or self._front)

    # ---- hook points ----
    def filter_page(self, info):
        return all(fn(info) is not False for fn in self._filter)

    def apply_nodes(self, blocks, doc):
        """Run transform_node over every block (children and inline sub-pages included)."""
        if not self._node:
            return blocks
        out = []
        for b in blocks:
            for fn in self._node:
                b = fn(b, doc)
                if b is None:
                    break
            if b is None:
                continue
            b.children = self.apply_nodes(b.children, doc)
            if b.sub is not None:
                b.sub.blocks = self.apply_nodes(b.sub.blocks, doc)
            out.append(b)
        return out

    def transform_frontmatter(self, fm, doc):
        for fn in self._front:
            res = fn(fm, doc)
            if isinstance(res, dict):
                fm = res
        return fm
