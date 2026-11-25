"""Offline stand-in for notion_client.Client, driven by recorded JSON fixtures."""

import json
from pathlib import Path
from types import SimpleNamespace

FIXTURE = Path(__file__).parent / "fixtures" / "notion_fixture.json"
DB_ID = "db" + "0" * 30


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeNotion:
    def __init__(self, fx=None, v3=False):
        """v3=True mimics notion-client 3.x: no databases.query, rows come from data_sources.query."""
        self.fx = fx or load_fixture()
        self.calls = []
        self.pages = SimpleNamespace(retrieve=self._retrieve)
        self.blocks = SimpleNamespace(children=SimpleNamespace(list=self._list), retrieve=self._block)
        if v3:
            self.databases = SimpleNamespace(retrieve=self._db_retrieve_v3)
            self.data_sources = SimpleNamespace(query=self._ds_query)
        else:
            self.databases = SimpleNamespace(query=self._query, retrieve=self._db_retrieve)

    def _retrieve(self, page_id):
        self.calls.append(("pages.retrieve", page_id))
        pid = page_id.replace("-", "")
        if pid not in self.fx["pages"]:
            raise Exception("object_not_found: " + pid)
        return json.loads(json.dumps(self.fx["pages"][pid]))  # deep copy

    def _list(self, block_id, page_size=100, start_cursor=None):
        self.calls.append(("blocks.children.list", block_id))
        res = json.loads(json.dumps(self.fx["blocks"].get(block_id.replace("-", ""), [])))
        return {"results": res, "has_more": False, "next_cursor": None}

    def _block(self, block_id):
        """blocks.retrieve: returns the block with a *fresh* signed URL (suffix _fresh)."""
        self.calls.append(("blocks.retrieve", block_id))
        for blocks in self.fx["blocks"].values():
            for b in blocks:
                if b["id"] == block_id.replace("-", ""):
                    b = json.loads(json.dumps(b))
                    d = b.get(b["type"]) or {}
                    src = d.get(d.get("type")) or {}
                    if "url" in src:
                        src["url"] = src["url"].replace(".png", "_fresh.png").replace(".jpg", "_fresh.jpg")
                    return b
        raise Exception("object_not_found")

    def _query(self, database_id, page_size=100, start_cursor=None):
        self.calls.append(("databases.query", database_id))
        ids = self.fx["databases"].get(database_id.replace("-", ""))
        if ids is None:
            raise Exception("object_not_found")
        return {
            "results": [json.loads(json.dumps(self.fx["pages"][i])) for i in ids],
            "has_more": False,
            "next_cursor": None,
        }

    def _db_retrieve(self, database_id):
        return {"properties": {}}

    def _db_retrieve_v3(self, database_id):
        self.calls.append(("databases.retrieve", database_id))
        if database_id.replace("-", "") not in self.fx["databases"]:
            raise Exception("object_not_found")
        return {"object": "database", "data_sources": [{"id": "ds-" + database_id, "name": "Main"}]}

    def _ds_query(self, data_source_id, page_size=100, start_cursor=None):
        self.calls.append(("data_sources.query", data_source_id))
        return self._query(data_source_id[len("ds-") :], page_size, start_cursor)
