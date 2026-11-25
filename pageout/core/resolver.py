"""Link resolver: maps Notion page ids to the exported files so links work offline."""

import os
from urllib.parse import quote

from pageout.core.cache import norm

LINKABLE = ("html", "md")  # formats where a relative file link is meaningful


class Resolver:
    def __init__(self, items, path_for):
        self._path_for = path_for
        self.by_id = {norm(it.id): it for it in items}

    def item(self, page_id):
        return self.by_id.get(norm(page_id))

    def link(self, page_id, fmt, current):
        """Relative URL from the file ``current`` to the exported ``fmt`` file of ``page_id``."""
        if fmt not in LINKABLE or not current:
            return None
        it = self.item(page_id)
        if it is None:
            return None
        target = self._path_for(fmt, it)
        rel = os.path.relpath(target, os.path.dirname(current)).replace(os.sep, "/")
        return quote(rel, safe="/")

    def title(self, page_id):
        it = self.item(page_id)
        return it.title if it else ""
