"""Export pipeline: plan pages, fetch, render, merge."""

import io
import json
import os
import shutil
import tempfile
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

from notion_client import Client
from playwright.sync_api import sync_playwright

try:
    from pypdf import PdfWriter as PdfMerger  # pip install pypdf (recommended)
except ImportError:
    from PyPDF2 import PdfMerger  # type: ignore[no-redef]  # fallback

import hashlib
import time
from dataclasses import dataclass, field

from pageout.core.assets import detect_ext, download
from pageout.core.timing import (
    TimingReport,
    get_timer,
    record_api_wait,
    record_image_bytes,
    reset_timer,
    set_api_timing,
    timer,
)
from pageout.core.cache import ExportCache
from pageout.core.config import (
    DB_EXPORT_MODES,
    ENGINES,
    EXTS,
    FOLDERS,
    FORMAT_LABELS,
    FORMATS,
    ICON_MODES,
    IMG_MODES,
    LATEX_IMG_MODES,
    OUTPUT_MODES,
    SUB_MODES,
)
from pageout.core.database import index_html_body, index_markdown, write_csv
from pageout.core.errors import Cancelled, LoginRequired
from pageout.core.ir import Asset, plain_text

# Import sync module for Phase 16
try:
    from pageout.core.sync import (
        SYNC_TARGETS,
        sync_to_local_folder,
        sync_to_git,
        sync_to_gdrive,
        sync_to_dropbox,
        sync_to_s3,
        perform_sync,
        SyncReport,
    )
except ImportError:
    SYNC_TARGETS = ["None"]
    sync_to_local_folder = sync_to_gdrive = sync_to_dropbox = sync_to_s3 = sync_to_git = None
    perform_sync = SyncReport = None
from pageout.core.ir import walk as walk_ir
from pageout.core.naming import build_name, clean_filename, format_date
from pageout.core.resolver import Resolver
from pageout.core.secrets import redact
from pageout.plugins.hooks import Hooks
from pageout.renderers.base import R
from pageout.renderers.asciidoc import build_asciidoc, blocks_asciidoc
from pageout.renderers.docx import build_docx
from pageout.renderers.epub import build_epub
from pageout.renderers.html import _page_icon_html, blocks_html, esc, props_html, wrap_html
from pageout.renderers.latex import blocks_tex, build_complete_latex, escape_tex
from pageout.renderers.markdown import blocks_md, md_front_matter
from pageout.renderers.pdf import launch_context, pdf_kwargs, remove_blank_pages, render_notion_page
from pageout.renderers.rst import build_rst, blocks_rst
from pageout.renderers.txt import blocks_txt
from pageout.sources.notion_api import (
    api,
    attach_inline,
    build_tree,
    page_fields,
    page_title,
    passes_filter,
    query_all,
    retrieve_markdown_with_fallback,
    resolve_roots,
    set_api_concurrency,
    set_api_timing as notion_set_api_timing,
    sort_pages,
    strip_private,
    walk,
)
from pageout.sources.notion_ir import to_document


class Item:
    def __init__(self, id, page, title, parent=None, depth=0, created="", edited="", stamp=""):
        self.id, self.page, self.title = id, page, title or "Untitled"
        self.stamp = stamp or (page or {}).get("last_edited_time", "")  # full timestamp (cache key)
        self.parent, self.depth = parent, depth
        self.created, self.edited = created, edited
        self.tree, self.imgs, self.doc, self.fast_md = None, [], None, None  # fast_md = pre-fetched markdown

    @property
    def label(self):
        return "/".join(self.dirparts + [self.base])


class Exporter:
    def __init__(
        self,
        cfg,
        all_props=None,
        shown_props=None,
        log=print,
        progress=lambda i, n: None,
        cancel=None,
        notion=None,
        hooks=None,
    ):
        self.cfg = cfg
        self.all_props = list(all_props or [])
        self.shown_props = list(shown_props or [])
        self._log_fn, self.progress = log, progress
        self._secrets = [cfg.get("token", ""), cfg.get("gemini_api_key", "")]
        self.hooks = hooks or Hooks()
        self.resolver = None
        self.hash_paths = {}
        self.skipped = 0
        self.cancel = cancel or threading.Event()
        self.notion = notion or (Client(auth=cfg["token"]) if cfg.get("token") else None)
        self.cache = {}
        self.used_paths = set()
        self.failed = []
        self.last_tex = ""
        self._tex_body = ""
        self._lock = threading.RLock()
        # Initialize timing
        self.timing = None

    def log(self, msg):
        self._log_fn(redact(msg, self._secrets))

    def _init_timing(self):
        """Initialize timing instrumentation."""
        reset_timer()  # Reset global timing from any previous run
        self.timing = get_timer()
        set_api_timing(self.timing)
        return self.timing

    # ---- sources ----
    def fetch_roots(self):
        c = self.cfg
        extra_sources = c.get("sources", [])
        roots = resolve_roots(self.notion, c["database"], c["source_type"], extra_sources=extra_sources)
        roots = [p for p in roots if passes_filter(p, c["filter_prop"], c["filter_op"], c["filter_value"])]
        roots = sort_pages(roots, c["sort_by"], c["sort_desc"])
        roots = [p for p in roots if self.hooks.filter_page(self._hook_info(p))]
        if int(c["max_pages"]) > 0:
            roots = roots[: int(c["max_pages"])]
        return roots

    @staticmethod
    def _hook_info(page):
        info = page_fields(page)
        info["id"] = page.get("id", "")
        return info

    def tree_of(self, it):
        if it.tree is None:
            it.tree = build_tree(self.notion, it.id, self.cache)
        return it.tree

    def document(self, it):
        """IR Document of an item (built once, after the raw tree and inline sub-pages are loaded)."""
        if it.doc is None:
            it.doc = to_document(it.page, it.title, self.tree_of(it), it.id, it.created, it.edited)
            if self.hooks.active:
                it.doc.blocks = self.hooks.apply_nodes(it.doc.blocks, it.doc)
        return it.doc

    def props_of(self, it):
        """Properties of an item without fetching its blocks (used by database exports)."""
        if it.doc is not None:
            return it.doc.properties
        return to_document(it.page, it.title, [], it.id).properties if it.page else []

    def plan(self, roots):
        c = self.cfg
        items = []
        separate = c["sub_mode"] == SUB_MODES[2]
        maxdepth = int(c["sub_depth"])

        def expand(it):
            if not separate or it.depth >= maxdepth:
                return
            for b in walk(self.tree_of(it), subs=False):
                t = b["type"]
                if t == "child_page":
                    sub = Item(
                        b["id"],
                        None,
                        b["child_page"].get("title"),
                        it,
                        it.depth + 1,
                        b.get("created_time", "")[:10],
                        b.get("last_edited_time", "")[:10],
                        stamp=b.get("last_edited_time", ""),
                    )
                    if not self.hooks.filter_page(
                        {
                            "title": sub.title,
                            "id": sub.id,
                            "date": "",
                            "created": sub.created,
                            "edited": sub.edited,
                            "parent": it.title,
                        }
                    ):
                        continue
                    items.append(sub)
                    expand(sub)
                elif t == "child_database" and c["sub_dbs"]:
                    try:
                        rows = query_all(self.notion, b["id"])
                    except Exception as e:
                        self.failed.append((b["child_database"].get("title", "database"), str(e)[:80]))
                        continue
                    for row in rows:
                        sub = Item(row["id"], row, page_title(row), it, it.depth + 1)
                        items.append(sub)
                        expand(sub)

        if separate:
            self.log("Scanning for sub-pages...")
        for p in roots:
            it = Item(p["id"], p, page_title(p))
            items.append(it)
            expand(it)

        self._name_items(items)
        return items

    def plan_documents(self, docs):
        """Items for sources that already provide IR documents (e.g. a Notion export zip)."""
        items = []
        for d in docs:
            it = Item(d.id, None, d.title, None, 0, d.created, d.edited)
            it.doc, it.tree = d, []
            items.append(it)
        self._name_items(items)
        return items

    def _name_items(self, items):
        c = self.cfg
        pad = max(2, len(str(len(items))))
        counter = defaultdict(int)
        for idx, it in enumerate(items, 1):
            if it.page:
                f = page_fields(it.page, idx, pad)
            else:
                date = next((p.date for p in (it.doc.properties if it.doc else []) if p.date), "")
                f = {
                    "title": it.title,
                    "date": date,
                    "created": it.created,
                    "edited": it.edited,
                    "index": f"{idx:0{pad}d}",
                }
            f["parent"] = it.parent.title if it.parent else ""
            it.fields = f
            base = build_name(c["name_format"], f)
            it.dirparts = (it.parent.dirparts + [it.parent.base]) if it.parent else []
            key = (tuple(it.dirparts), base.lower())
            counter[key] += 1
            it.base = f"{base} ({counter[key]:02})" if counter[key] > 1 else base

    # ---- paths ----
    def path_for(self, fmt, it):
        """Output path of an item (no side effects)."""
        return os.path.join(self.cfg["save_dir"], FOLDERS[fmt], *it.dirparts, it.base + EXTS[fmt])

    def target(self, fmt, it):
        path = self.path_for(fmt, it)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    # ---- images ----
    def image_path(self, it, img, data):
        c = self.cfg
        f = dict(it.fields)
        f["page"] = it.base
        f["n"] = img.n if img.n == "cover" else f"{img.n:02d}"
        f["caption"] = clean_filename(img.caption or "")[:60]
        f["original"] = os.path.splitext(os.path.basename(unquote(urlparse(img.url).path)))[0]
        name = build_name(c["img_format"], f)
        folder = os.path.join(c["save_dir"], "Images")
        if c["img_subfolder"]:
            folder = os.path.join(folder, *it.dirparts, it.base)
        os.makedirs(folder, exist_ok=True)
        with self._lock:
            path = os.path.join(folder, name + img.ext)
            k = 2
            while path.lower() in self.used_paths:
                path = os.path.join(folder, f"{name} ({k:02d}){img.ext}")
                k += 1
            self.used_paths.add(path.lower())
        return path

    def _optimize(self, img):
        """Shrink big photos for PDF/Word embedding (much faster + smaller files)."""
        c = self.cfg
        if not c.get("optimize_images", True) or img.ext in (".svg", ".gif"):
            return
        try:
            from PIL import Image, ImageOps

            mx = int(c.get("image_max_px", 1600))
            im = Image.open(io.BytesIO(img.bytes))
            if max(im.size) <= mx and len(img.bytes) < 400_000:
                return
            im = ImageOps.exif_transpose(im)
            im.thumbnail((mx, mx), Image.LANCZOS)
            buf = io.BytesIO()
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                im.convert("RGBA").save(buf, "PNG", optimize=True)
                mime = "image/png"
            else:
                im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
            if len(buf.getvalue()) < len(img.bytes):
                img.opt_bytes, img.opt_mime = buf.getvalue(), mime
        except Exception:
            pass

    # ---- images: download (re-fetching expired links), de-duplicate, save ----
    @staticmethod
    def _expired(err):
        code = getattr(err, "code", None) or getattr(getattr(err, "response", None), "status_code", None)
        return code in (400, 401, 403, 404, 410) or any(x in str(err) for x in (" 403", "403:", "Forbidden", "expired"))

    def _fresh_url(self, it, img):
        """Ask Notion for a new signed URL of an image (cover or block)."""
        try:
            if img.n == "cover":
                cv = api(self.notion.pages.retrieve, page_id=it.id).get("cover") or {}
                return (cv.get(cv.get("type")) or {}).get("url", "")
            if img.block_id:
                d = api(self.notion.blocks.retrieve, block_id=img.block_id).get("image") or {}
                return (d.get(d.get("type")) or {}).get("url", "")
        except Exception:
            pass
        return ""

    def _download(self, it, img):
        try:
            return download(img.url)
        except Exception as err:
            if not self._expired(err) or self.notion is None:
                raise
            fresh = self._fresh_url(it, img)
            if not fresh or fresh == img.url:
                raise
            self.log(f"  image link had expired - fetched a fresh one: {it.label}")
            img.url = fresh
            return download(fresh)

    _TEX_OK = (".png", ".jpg", ".jpeg", ".pdf")

    def _to_png(self, img):
        """LaTeX only reads PNG/JPG/PDF: convert other bitmap formats (webp, gif, ...) to PNG."""
        try:
            from PIL import Image

            im = Image.open(io.BytesIO(img.bytes))
            buf = io.BytesIO()
            im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG")
            img.bytes, img.ext, img.opt_bytes = buf.getvalue(), ".png", None
        except Exception:
            pass

    def prepare_images(self, it):
        c = self.cfg
        handling = c["img_handling"]
        engine_api = c["engine"] == ENGINES[0]
        tex_files = c.get("fmt_tex", False) and c.get("latex_images") == LATEX_IMG_MODES[0]
        save_files = (
            c["fmt_images"] or handling == IMG_MODES[1] or tex_files or (handling == IMG_MODES[0] and c["fmt_md"])
        )
        embed_pdf = c["fmt_pdf"] and engine_api and handling == IMG_MODES[0]
        need_bytes = (
            save_files
            or c["fmt_docx"]
            or c.get("gemini_math_ocr", False)
            or embed_pdf
            or (handling == IMG_MODES[0] and c["fmt_html"])
        )
        if not need_bytes:
            return
        imgs = []
        doc = self.document(it)
        if c["img_cover"] and doc.cover_url:
            imgs.append(Asset(url=doc.cover_url, n="cover"))
        n = 0
        for b in walk_ir(doc.blocks):
            if b.kind == "image" and b.media and b.media.url:
                n += 1
                if b.media.asset is not None and b.media.asset.bytes:  # already loaded (zip source)
                    img = b.media.asset
                    img.n = n
                else:
                    img = Asset(url=b.media.url, caption=plain_text(b.media.caption), n=n, block_id=b.media.block_id)
                    b.media.asset = img
                imgs.append(img)
        want_opt = embed_pdf or c["fmt_docx"]

        img_count = 0
        def fetch(img):
            nonlocal img_count
            try:
                if not img.bytes:
                    data, ctype = self._download(it, img)
                    img.bytes, img.ext = data, detect_ext(img.url, ctype, data)
                    if self.timing:
                        img_count += 1
                        record_image_bytes(len(img.bytes))
                if want_opt:
                    self._optimize(img)
            except Exception as e:
                self.failed.append((f"{it.label} (image {img.n})", str(e)[:80]))

        if imgs:
            with ThreadPoolExecutor(max_workers=min(8, len(imgs))) as ex:  # downloads in parallel
                list(ex.map(fetch, imgs))
        # Record image count
        if self.timing:
            self.timing.images.count += img_count
        if save_files:
            for img in imgs:
                if not img.bytes:
                    continue
                try:
                    if tex_files and img.ext not in self._TEX_OK:
                        self._to_png(img)
                    img.sha256 = hashlib.sha256(img.bytes).hexdigest()
                    with self._lock:
                        existing = self.hash_paths.get(img.sha256)
                        if existing and os.path.exists(existing):
                            img.path = existing  # identical image already saved
                            continue
                        path = self.image_path(it, img, img.bytes)
                        with open(path, "wb") as f:
                            f.write(img.bytes)
                        img.path = path
                        self.hash_paths[img.sha256] = path
                except Exception as e:
                    self.failed.append((f"{it.label} (image {img.n})", str(e)[:80]))
        it.imgs = imgs

    # ---- content helpers ----
    def prop_rows(self, it):
        date_fmt = self.cfg.get("date_format_props", "YYYY-MM-DD")
        rows = []
        for p in self.document(it).properties:
            if p.type == "title":
                continue
            if self.all_props and p.name not in self.shown_props:
                continue
            txt = format_date(p.date, date_fmt) if p.date else p.text
            if txt:
                rows.append((p.name, txt))
        return rows

    def _page_icon_text(self, it) -> str:
        """Return the emoji/icon text for docx/md/txt (empty if hidden)."""
        mode = self.cfg.get("icon_mode", ICON_MODES[0])
        if mode == "Hide icon":
            return ""
        return self.document(it).icon_emoji

    def body_html(self, it, kind, base_dir, current=None):
        r = R(self.cfg, kind, base_dir, self.resolver, current)
        cfg = self.cfg
        rows = self.prop_rows(it)
        layout = cfg.get("prop_layout", "Notion Table")

        # Page icon HTML
        icon_html = _page_icon_html(self.document(it), cfg)

        # Title
        sep_cls = ""
        h = f'{icon_html}<h1 class="notion-title{sep_cls}">{esc(it.title)}</h1>'

        # Properties HTML
        h += props_html(rows, layout, cfg)

        # Cover page wrapper
        body_html = blocks_html(self.document(it).blocks, r)
        if cfg.get("cover_page"):
            cover = f'<div class="notion-cover-page">{h}</div><div class="notion-page-break"></div>'
            return cover + body_html
        return h + body_html

    def text_md(self, it, base_dir, current=None):
        c = self.cfg
        r = R(c, "md", base_dir, self.resolver, current)

        # Try fast markdown path via API (P4: Cheaper Markdown)
        if c.get("fast_markdown", True) and self.notion and it.tree and not it.fast_md:
            md, used_fast = retrieve_markdown_with_fallback(
                self.notion, it.id, it.tree, include_transcript=False
            )
            if used_fast and md:
                it.fast_md = md
            elif md is None and not used_fast:
                # Need to use custom converter - document() already called during prep
                pass

        # If we got fast markdown from API, use it; otherwise fall back to custom converter
        if it.fast_md:
            body = it.fast_md
            # Still need to build front matter with properties
            icon = self._page_icon_text(it)
            prefix = f"{icon} " if icon else ""
            fm = {"title": it.title}
            fm.update(dict(self.prop_rows(it)))
            if self.hooks.active:
                doc = self.document(it)
                fm = dict(self.hooks.transform_frontmatter(fm, doc))
            title = fm.pop("title", it.title)
            front = md_front_matter(title, list(fm.items()), c.get("md_preset"))
            return front + f"\n\n# {prefix}{it.title}\n\n" + body + "\n"

        # Fall back to custom converter
        doc = self.document(it)
        body = "\n".join(blocks_md(doc.blocks, r))
        icon = self._page_icon_text(it)
        prefix = f"{icon} " if icon else ""
        fm = {"title": it.title}
        fm.update(dict(self.prop_rows(it)))
        if self.hooks.active:
            fm = dict(self.hooks.transform_frontmatter(fm, doc))
        title = fm.pop("title", it.title)
        front = md_front_matter(title, list(fm.items()), c.get("md_preset"))
        return front + f"\n\n# {prefix}{it.title}\n\n" + body + "\n"

    def text_txt(self, it):
        lines = [it.title, "=" * len(it.title), ""]
        lines += [f"{k}: {v}" for k, v in self.prop_rows(it)]
        if len(lines) > 3:
            lines.append("")
        lines += blocks_txt(self.document(it).blocks)
        return "\n".join(lines) + "\n"

    def text_tex(self, it, base_dir):
        r = R(self.cfg, "tex", base_dir, self.resolver)
        body = blocks_tex(self.document(it).blocks, r, self.document(it), base_dir, self.log)
        self._tex_body = body
        return build_complete_latex(it.title, self.prop_rows(it), body, self.cfg)

    def _clean_pdf(self, path):
        if not self.cfg.get("remove_blank_pages", True):
            return
        try:
            n = remove_blank_pages(path)
            if n:
                self.log(f"  removed {n} blank page(s)")
        except Exception:
            pass

    # ---- pdf ----
    def pdf_browser(self, page, it, path, hide_names):
        for attempt in range(int(self.cfg["retries"]) + 1):
            try:
                render_notion_page(page, it.id, path, self.cfg, self.all_props, hide_names)
                return
            except LoginRequired:
                raise Exception(
                    "Notion asked for a login. Use 'Log in to Notion' on the Source "
                    "tab, sign in, close the window, then export again."
                )
            except Exception:
                if attempt >= int(self.cfg["retries"]):
                    raise
                self.log(f"retrying: {it.label}")

    def pdf_api(self, page, it, path, tmp):
        html = wrap_html(it.title, self.body_html(it, "pdf", None), self.cfg)
        hp = os.path.join(tmp, f"{abs(hash(it.id))}.html")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        page.goto(Path(hp).resolve().as_uri(), wait_until="load")
        try:  # fonts / math finished (max 8 s, so a missing internet connection never hangs)
            page.evaluate(
                "Promise.race([document.fonts ? document.fonts.ready : 0, new Promise(r => setTimeout(r, 8000))])"
            )
        except Exception:
            pass
        page.pdf(**pdf_kwargs(self.cfg, path))
        try:
            os.remove(hp)
        except OSError:
            pass

    # ---- main ----
    def _incremental_off_reason(self, formats, documents):
        c = self.cfg
        if documents is not None:
            return "this source has no change timestamps"
        if c["combine"]:
            return "combined files need every page"
        if c["fmt_images"]:
            return "raw image export is on"
        if c["sub_mode"] == SUB_MODES[1]:
            return "inline sub-pages are not tracked by the parent's timestamp"
        return ""

    def _write_db_export(self, items, formats):
        c = self.cfg
        mode = c.get("db_export", DB_EXPORT_MODES[0])
        if mode in (None, "", DB_EXPORT_MODES[0]) or not items:
            return
        name = clean_filename(c["merged_name"]) or "All_Pages"
        date_fmt = c.get("date_format_props", "YYYY-MM-DD")

        if mode == DB_EXPORT_MODES[4]:  # Group by mode
            self._write_group_by_export(items, formats, name, date_fmt)
            return

        if mode == DB_EXPORT_MODES[3]:
            path = os.path.join(c["save_dir"], name + ".csv")
            write_csv(path, items, date_fmt, self.props_of)
            self.log(f"Database CSV written: {path}")
            return
        first = next((f for f in ("html", "md", "pdf", "docx", "txt", "tex", "json") if f in formats), None)
        if first is None:
            self.log("Index page skipped: tick at least one export format.")
            return
        with_table = mode == DB_EXPORT_MODES[2]
        for f in [x for x in ("html", "md") if x in formats] or ["md"]:
            idx = os.path.join(c["save_dir"], FOLDERS[f], "_Index" + EXTS[f])
            os.makedirs(os.path.dirname(idx), exist_ok=True)
            link = lambda it, lf=(f if f in formats else first): self.path_for(lf, it)  # noqa: E731
            with open(idx, "w", encoding="utf-8") as fh:
                if f == "html":
                    fh.write(
                        wrap_html(name, index_html_body(name, items, link, idx, date_fmt, with_table, self.props_of, c), c)
                    )
                else:
                    fh.write(index_markdown(name, items, link, idx, date_fmt, with_table, self.props_of, c))
            self.log(f"Index written: {idx}")

    def _write_group_by_export(self, items, formats, base_name, date_fmt):
        """Write exports grouped by a property value (one file per group)."""
        c = self.cfg
        group_by_prop = c.get("group_by", "").strip()
        if not group_by_prop:
            self.log("Group by: no property specified, skipping.")
            return

        first = next((f for f in ("html", "md", "pdf", "docx", "txt", "tex", "json") if f in formats), None)
        if first is None:
            self.log("Group by export: skipping, no valid export format selected.")
            return

        # Group items by the property value
        groups = {}
        for it in items:
            group_key = ""
            for p in self.props_of(it):
                if p.name.lower() == group_by_prop.lower():
                    group_key = p.text or p.date or ""
                    break
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(it)

        # Write each group to its own file
        total_written = 0
        from pageout.core.database import index_markdown, index_html_body
        from pageout.renderers.html import wrap_html

        for group_key, group_items in groups.items():
            # Clean the group key for filename
            group_name = clean_filename(str(group_key))[:50] or "Other"

            for fmt in formats:
                group_idx = os.path.join(c["save_dir"], FOLDERS[fmt], f"{base_name}_{group_name}" + EXTS[fmt])
                os.makedirs(os.path.dirname(group_idx), exist_ok=True)
                link = lambda it, lf=fmt: self.path_for(lf, it)  # noqa: E731
                with open(group_idx, "w", encoding="utf-8") as fh:
                    if fmt == "html":
                        fh.write(
                            wrap_html(f"{base_name} - {group_key}", index_html_body(
                                f"{base_name} - {group_key}", group_items, link, group_idx,
                                date_fmt, False, self.props_of, c
                            ), c)
                        )
                    elif fmt == "md":
                        fh.write(index_markdown(f"{base_name} - {group_key}", group_items, link, group_idx,
                                            date_fmt, False, self.props_of, c))
                    elif fmt == "json":
                        for it in group_items:
                            try:
                                data = self.document(it).source
                                item_data = {
                                    "id": it.id,
                                    "title": it.title,
                                    "properties": data.get("properties", {}),
                                    "blocks": strip_private(data.get("blocks", [])) if data else []
                                }
                                item_path = self.path_for("json", it)
                                os.makedirs(os.path.dirname(item_path), exist_ok=True)
                                with open(item_path, "w", encoding="utf-8") as jf:
                                    json.dump(item_data, jf, ensure_ascii=False, indent=2)
                            except Exception as e:
                                self.log(f"Failed to write JSON for {it.title}: {e}")
                self.log(f"Group-by export written: {group_idx}")
                total_written += len(group_items)

        self.log(f"Group-by export: {total_written} pages written in {len(groups)} group(s)")

    def run(self, selected_roots=None, documents=None):
        c = self.cfg
        formats = [f for f in FORMATS if c["fmt_" + f]]
        if not formats and not c["fmt_images"]:
            raise Exception("Pick at least one export format.")
        if not c["save_dir"].strip():
            raise Exception("Choose an output folder.")
        use_api_pdf = c["engine"] == ENGINES[0]
        doc_formats = [f for f in formats if f != "pdf"]
        need_tree = (
            bool(doc_formats) or c["fmt_images"] or c["sub_mode"] != SUB_MODES[0] or ("pdf" in formats and use_api_pdf)
        )
        inline = c["sub_mode"] == SUB_MODES[1]

        # Initialize timing
        self._init_timing()

        self.log("Reading pages...")
        if documents is not None:
            items = self.plan_documents(documents)
        else:
            roots = selected_roots or self.fetch_roots()
            if not roots:
                raise Exception("No pages matched.")
            items = self.plan(roots)
        if not items:
            raise Exception("No pages matched.")
        total = len(items)
        self.resolver = Resolver(items, self.path_for) if c.get("rewrite_links", True) else None

        # incremental sync: pages whose last_edited_time and settings are unchanged are skipped
        cache, skip = None, set()
        if c.get("incremental", True):
            why = self._incremental_off_reason(formats, documents)
            if why:
                self.log(f"Incremental sync is off: {why}.")
            else:
                cache = ExportCache(c["save_dir"], c)
                if not c.get("force"):
                    skip = {k for k, x in enumerate(items, 1) if cache.is_fresh(x, formats)}
                    if skip:
                        self.log(f"{len(skip)} page(s) unchanged, will be skipped (use Force to re-export).")
        self.log(
            f"Exporting {total} page(s) to: "
            + ", ".join(FORMAT_LABELS[f] for f in formats + (["images"] if c["fmt_images"] else []))
        )

        workers = max(1, min(8, int(c.get("workers", 4))))
        set_api_concurrency(min(3, workers))
        prefetch_pool = ThreadPoolExecutor(max_workers=workers) if need_tree else None
        futs, window = {}, workers * 2

        def prep(it):
            self.tree_of(it)
            if inline:
                attach_inline(self.notion, it.tree, self.cache, 1, int(c["sub_depth"]))
            self.document(it)
            self.prepare_images(it)

        def submit(k):
            if prefetch_pool and 1 <= k <= total and k not in skip:
                futs[k] = prefetch_pool.submit(prep, items[k - 1])

        for k in range(1, min(total, window) + 1):  # pages are fetched in the background
            submit(k)  # while the previous one is being rendered

        hide_names = [n for n in self.all_props if n not in self.shown_props] if self.all_props else []
        made_pdfs, combined_html, combined_md, made_tex = [], [], [], []
        tmp = tempfile.mkdtemp(prefix="notion_export_")
        pw = browser = ctx = None
        try:
            if "pdf" in formats:
                pw = sync_playwright().start()
                pcfg = dict(c, use_login=bool(c["use_login"]) and not use_api_pdf)
                browser, ctx = launch_context(pw, pcfg)

            html_root = os.path.join(c["save_dir"], FOLDERS["html"])
            md_root = os.path.join(c["save_dir"], FOLDERS["md"])
            tex_root = os.path.join(c["save_dir"], FOLDERS["tex"])

            # Determine PDF workers for parallel processing
            pdf_workers = max(1, min(int(c.get("workers", 4)), total)) if "pdf" in formats else 1
            pdf_pool = ThreadPoolExecutor(max_workers=pdf_workers) if "pdf" in formats else None
            pdf_futures = {}

            def run_pdf_api(pcfg, it, path, hide_names, tmp_dir):
                """Run PDF via API engine in a worker thread - creates own Playwright and browser."""
                pdf_start = time.perf_counter()
                thread_pw = thread_browser = thread_ctx = thread_page = None
                try:
                    # Disable use_login for parallel workers (persistent context not thread-safe)
                    worker_cfg = dict(pcfg, use_login=False)
                    thread_pw = sync_playwright().start()
                    thread_browser, thread_ctx = launch_context(thread_pw, worker_cfg)
                    thread_page = thread_ctx.new_page()
                    self.pdf_api(thread_page, it, path, tmp_dir)
                    self._clean_pdf(path)
                finally:
                    for obj in (thread_page, thread_ctx, thread_browser):
                        try:
                            if obj:
                                obj.close()
                        except Exception:
                            pass
                    if thread_pw:
                        try:
                            thread_pw.stop()
                        except Exception:
                            pass
                if self.timing:
                    elapsed_ms = (time.perf_counter() - pdf_start) * 1000
                    with self._lock:
                        self.timing.pdf.total_ms += elapsed_ms
                        self.timing.pdf.count += 1

            def run_pdf_browser(pcfg, it, path, hide_names, tmp_dir):
                """Run PDF via Browser engine in a worker thread - creates own Playwright and browser."""
                pdf_start = time.perf_counter()
                thread_pw = thread_browser = thread_ctx = thread_page = None
                try:
                    # Disable use_login for parallel workers (persistent context not thread-safe)
                    worker_cfg = dict(pcfg, use_login=False)
                    thread_pw = sync_playwright().start()
                    thread_browser, thread_ctx = launch_context(thread_pw, worker_cfg)
                    thread_page = thread_ctx.new_page()
                    self.pdf_browser(thread_page, it, path, hide_names)
                    self._clean_pdf(path)
                finally:
                    for obj in (thread_page, thread_ctx, thread_browser):
                        try:
                            if obj:
                                obj.close()
                        except Exception:
                            pass
                    if thread_pw:
                        try:
                            thread_pw.stop()
                        except Exception:
                            pass
                if self.timing:
                    elapsed_ms = (time.perf_counter() - pdf_start) * 1000
                    with self._lock:
                        self.timing.pdf.total_ms += elapsed_ms
                        self.timing.pdf.count += 1

            for i, it in enumerate(items, 1):
                if self.cancel.is_set():
                    raise Cancelled()
                self.progress(i - 1, total)
                fut = futs.pop(i, None) if need_tree else None
                submit(i + window)
                if i in skip:
                    outs = cache.outputs(it)
                    if outs.get("pdf"):
                        made_pdfs.append((it.label, outs["pdf"]))
                    self.skipped += 1
                    self.log(f"[{i}/{total}] unchanged, skipped: {it.label}")
                    continue
                failed_before, outputs = len(self.failed), {}
                try:
                    if fut is not None:
                        fut.result()

                    for fmt in formats:
                        path = self.target(fmt, it)
                        if c["skip_existing"] and os.path.exists(path):
                            outputs[fmt] = path
                            if fmt == "pdf":
                                made_pdfs.append((it.label, path))
                            continue
                        try:
                            if fmt == "pdf":
                                # Submit PDF generation to thread pool for parallel processing
                                if use_api_pdf:
                                    future = pdf_pool.submit(run_pdf_api, pcfg, it, path, hide_names, tmp)
                                else:
                                    future = pdf_pool.submit(run_pdf_browser, pcfg, it, path, hide_names, tmp)
                                pdf_futures[it.id] = (future, it, path)
                            elif fmt == "html":
                                body = self.body_html(it, "html", os.path.dirname(path), path)
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(wrap_html(it.title, body, c))
                            elif fmt == "md":
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(self.text_md(it, os.path.dirname(path), path))
                            elif fmt == "txt":
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(self.text_txt(it))
                            elif fmt == "docx":
                                icon_text = self._page_icon_text(it)
                                build_docx(
                                    it.title,
                                    icon_text,
                                    self.prop_rows(it),
                                    self.document(it).blocks,
                                    R(c, "docx"),
                                    path,
                                    c,
                                )
                            elif fmt == "json":
                                src = self.document(it).source
                                data = {
                                    "id": it.id,
                                    "title": it.title,
                                    "properties": src.get("properties", {}),
                                    "blocks": strip_private(src.get("blocks", [])),
                                }
                                with open(path, "w", encoding="utf-8") as f:
                                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                            elif fmt == "tex":
                                tex_code = self.text_tex(it, os.path.dirname(path))
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(tex_code)
                                made_tex.append((it.title, path, self._tex_body))
                                self.last_tex = tex_code
                            elif fmt == "epub":
                                r = R(c, "epub", os.path.dirname(path), self.resolver, path)
                                icon_text = self._page_icon_text(it)
                                build_epub(
                                    it.title,
                                    icon_text,
                                    self.prop_rows(it),
                                    self.document(it).blocks,
                                    r,
                                    path,
                                    c,
                                )
                            elif fmt == "rst":
                                rst_content = build_rst(it.title, self.prop_rows(it), self.document(it).blocks, R(c, "rst"), c)
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(rst_content)
                            elif fmt == "adoc":
                                adoc_content = build_asciidoc(it.title, self.prop_rows(it), self.document(it).blocks, R(c, "adoc"), c)
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(adoc_content)
                        except LoginRequired:
                            raise
                        except Exception as e:
                            if "login" in str(e).lower() and fmt == "pdf":
                                raise
                            self.failed.append(
                                (f"{it.label} [{fmt}]", str(e).splitlines()[0][:100] if str(e) else "error")
                            )
                            self.log(f"FAILED {fmt}: {it.label}")
                            continue
                        outputs[fmt] = path
                    if c["combine"]:
                        if c["fmt_html"]:
                            combined_html.append((it, self.body_html(it, "html", html_root)))
                        if c["fmt_md"]:
                            combined_md.append(self.text_md(it, md_root))
                    self.log(f"[{i}/{total}] {it.label}")
                    if cache is not None and len(self.failed) == failed_before:
                        cache.record(it, outputs)
                    for im in it.imgs:  # free memory early
                        im.bytes = None
                        im.opt_bytes = None
                except Cancelled:
                    raise
                except Exception as e:
                    if "asked for a login" in str(e):
                        raise
                    self.failed.append((it.label, str(e).splitlines()[0][:100] if str(e) else "error"))
                    self.log(f"[{i}/{total}] FAILED: {it.label}")

            # Wait for all PDF futures to complete
            if pdf_pool:
                for fid, (future, it, path) in pdf_futures.items():
                    try:
                        future.result()
                        made_pdfs.append((it.label, path))
                    except Exception as e:
                        self.failed.append((f"{it.label} [pdf]", str(e).splitlines()[0][:100] if str(e) else "error"))
                        self.log(f"FAILED pdf: {it.label}")
                pdf_pool.shutdown(wait=True)
        finally:
            if cache is not None:
                cache.save()
            if prefetch_pool:
                prefetch_pool.shutdown(wait=False, cancel_futures=True)
            for obj in (ctx, browser):
                try:
                    if obj:
                        obj.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)
        self.progress(total, total)

        name = clean_filename(c["merged_name"]) or "All_Pages"
        if combined_html:
            toc = "".join(f'<li><a href="#p{n}">{esc(it.title)}</a></li>' for n, (it, _) in enumerate(combined_html))
            secs = "".join(f'<section class="page" id="p{n}">{b}</section>' for n, (_, b) in enumerate(combined_html))
            with open(os.path.join(html_root, name + ".html"), "w", encoding="utf-8") as f:
                f.write(wrap_html(name, f"<h1 class='notion-title'>{esc(name)}</h1><ol>{toc}</ol>{secs}", c))
        if combined_md:
            with open(os.path.join(md_root, name + ".md"), "w", encoding="utf-8") as f:
                f.write("\n\n---\n\n".join(combined_md))
        if made_tex and c["combine"]:
            combined_tex_sections = []
            for it_title, _, body_code in made_tex:
                combined_tex_sections.append(f"\\clearpage\n\\section{{{escape_tex(it_title)}}}\n\n" + body_code)
            with open(os.path.join(tex_root, name + ".tex"), "w", encoding="utf-8") as f:
                f.write(build_complete_latex(name, [], "\n\n".join(combined_tex_sections), c))

        try:
            self._write_db_export(items, formats)
        except Exception as e:
            self.failed.append(("database export", str(e)[:100]))
        if self.skipped:
            self.log(f"{self.skipped} page(s) unchanged, skipped.")

        if made_pdfs and c["output_mode"] != OUTPUT_MODES[2]:
            self.log("Merging PDFs...")
            merge_start = time.perf_counter()
            merger = PdfMerger()
            for title, path in made_pdfs:
                try:
                    merger.append(path, outline_item=title if c["bookmarks"] else None)
                except Exception as e:
                    self.failed.append((title + " [merge]", str(e)[:80]))
            out = os.path.join(c["save_dir"], name + ".pdf")
            merger.write(out)
            merger.close()
            if self.timing:
                elapsed_ms = (time.perf_counter() - merge_start) * 1000
                self.timing.merge.total_ms += elapsed_ms
                self.timing.merge.count += 1
            if c["output_mode"] == OUTPUT_MODES[1]:
                for _, path in made_pdfs:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                for dp, _, _ in os.walk(os.path.join(c["save_dir"], FOLDERS["pdf"]), topdown=False):
                    try:
                        os.rmdir(dp)
                    except OSError:
                        pass
        self.failed[:] = [(redact(a, self._secrets), redact(b, self._secrets)) for a, b in self.failed]
        return c["save_dir"], total, self.failed, self.timing


@dataclass
class Result:
    """Outcome of an export run (what the GUI and the CLI report)."""

    out_dir: str
    total: int
    failed: list = field(default_factory=list)
    skipped: int = 0
    last_tex: str = ""
    timing: TimingReport = None
    profile_timing: bool = False
    # Phase 16: Sync result
    sync_target: str = "None"
    sync_message: str = ""
    sync_success: bool = False
    sync_error: str = ""
    sync_files: int = 0

    @property
    def timing_summary(self) -> str:
        """Return the timing summary string."""
        if self.timing:
            return self.timing.summary()
        return "No timing data"


def export(
    config,
    progress=None,
    cancel=None,
    log=None,
    notion=None,
    selected_roots=None,
    all_props=None,
    shown_props=None,
    hooks=None,
    documents=None,
):
    """Headless entry point used by the GUI and the CLI: ``export(config) -> Result``."""
    if hooks is None and config.get("hooks"):
        hooks = Hooks.from_files(config["hooks"])
    ex = Exporter(
        config, all_props, shown_props, log or (lambda m: None), progress or (lambda i, n: None), cancel, notion, hooks
    )
    out, total, failed, timing = ex.run(selected_roots, documents)
    profile = config.get("profile_timing", False)

    # Phase 16: Perform sync after export if configured
    sync_target = config.get("sync_target", "None")
    sync_after = config.get("sync_after_export", False)
    sync_report = SyncReport("None", True, "Sync disabled", 0)

    if sync_after and sync_target != "None" and perform_sync is not None:
        sync_config = {
            "sync_path": config.get("sync_path", ""),
            "sync_branch": config.get("sync_branch", "main"),
            "gdrive_folder_id": config.get("gdrive_folder_id", ""),
            "dropbox_path": config.get("dropbox_path", "/exports"),
            "s3_bucket": config.get("s3_bucket", ""),
            "s3_prefix": config.get("s3_prefix", "exports"),
        }
        sync_report = perform_sync(out, sync_target, sync_config, config)
        if log:
            if sync_report.success:
                log(f"Sync completed: {sync_report.message}")
            else:
                log(f"Sync failed: {sync_report.message}")

    result = Result(
        out, total, failed, ex.skipped, ex.last_tex,
        timing=timing,
        profile_timing=profile,
        sync_target=sync_report.target if sync_report else "None",
        sync_message=sync_report.message if sync_report else "",
        sync_success=sync_report.success if sync_report else False,
        sync_error=sync_report.errors[0] if sync_report and sync_report.errors else "",
        sync_files=sync_report.files_synced if sync_report else 0,
    )
    # Write timing JSON if profile_timing is enabled
    if profile and timing:
        timing_path = os.path.join(out, "timing_report.json")
        with open(timing_path, "w", encoding="utf-8") as f:
            f.write(timing.to_json())
        if log:
            log(f"Timing report written to: {timing_path}")
    return result
