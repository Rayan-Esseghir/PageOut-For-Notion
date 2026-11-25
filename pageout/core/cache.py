"""Incremental sync: skip pages whose last_edited_time and settings did not change."""

import hashlib
import json
import os

CACHE_FILE = ".pageout_cache.json"
CACHE_VERSION = 1

# settings that do NOT change the content of an exported file
_IGNORED = {
    "token",
    "gemini_api_key",
    "remember_token",
    "allow_plaintext_secrets",
    "workers",
    "retries",
    "extra_wait",
    "skip_existing",
    "incremental",
    "force",
    "database",
    "source_type",
    "sort_by",
    "sort_desc",
    "filter_prop",
    "filter_op",
    "filter_value",
    "max_pages",
    "merged_name",
    "output_mode",
    "bookmarks",
    "combine",
    "save_dir",
    "db_export",
    "use_login",
    "_ver",
    "theme_preset",
}


def config_fingerprint(cfg):
    keep = {
        k: v
        for k, v in sorted(cfg.items())
        if k not in _IGNORED and not k.startswith("fmt_") and isinstance(v, (str, int, float, bool, type(None)))
    }
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def norm(i):
    return (i or "").replace("-", "").lower()


class ExportCache:
    def __init__(self, save_dir, cfg):
        self.path = os.path.join(save_dir, CACHE_FILE)
        self.fp = config_fingerprint(cfg)
        self.pages = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") == CACHE_VERSION:
                self.pages = data.get("pages", {})
        except Exception:
            pass

    def is_fresh(self, item, formats):
        """True when every requested output of this page exists and nothing relevant changed."""
        e = self.pages.get(norm(item.id))
        if not e or not item.stamp or e.get("stamp") != item.stamp or e.get("config") != self.fp:
            return False
        outs = e.get("outputs", {})
        return all(f in outs and os.path.exists(outs[f]) for f in formats)

    def outputs(self, item):
        return dict(self.pages.get(norm(item.id), {}).get("outputs", {}))

    def record(self, item, outputs):
        self.pages[norm(item.id)] = {"stamp": item.stamp, "config": self.fp, "outputs": outputs, "title": item.title}

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "pages": self.pages}, f, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass
