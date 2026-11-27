"""Notion API access: rate limiting, pagination, property helpers, block tree, fast markdown."""

import re
import threading
import time
from urllib.parse import urlparse

from pageout.core.naming import format_date

_API_SEM = threading.Semaphore(3)  # Notion allows ~3 requests/second on average
_api_timing = None  # Will be set by pipeline

# Block types that are NOT supported by pages.retrieve_markdown
UNSUPPORTED_MD_BLOCKS = {"table_of_contents", "breadcrumb", "table_row"}


def set_api_concurrency(n):
    global _API_SEM
    _API_SEM = threading.Semaphore(max(1, int(n)))


def set_api_timing(timing):
    """Set the timing module for API call instrumentation."""
    global _api_timing
    _api_timing = timing


def api(fn, **kw):
    """Call the Notion API, retrying on rate limits / temporary errors (thread-safe)."""
    global _api_timing
    for attempt in range(7):
        api_start = time.perf_counter()
        try:
            with _API_SEM:
                result = fn(**kw)
                if _api_timing:
                    elapsed_ms = (time.perf_counter() - api_start) * 1000
                    _api_timing.notion_api.total_ms += elapsed_ms
                    _api_timing.notion_api.count += 1
                return result
        except Exception as e:
            s = str(e).lower()
            temp = any(
                x in s for x in ("429", "rate limit", "rate_limited", "timed out", "502", "503", "504", "bad gateway")
            )
            if attempt < 6 and temp:
                wait = 1.5 * (attempt + 1)
                try:
                    wait = max(wait, float(getattr(e, "headers", {}).get("retry-after")))
                except Exception:
                    pass
                if _api_timing:
                    _api_timing.api_wait_ms += wait * 1000
                time.sleep(wait)
                continue
            if _api_timing:
                elapsed_ms = (time.perf_counter() - api_start) * 1000
                _api_timing.notion_api.total_ms += elapsed_ms
                _api_timing.notion_api.count += 1
            raise


def parse_database_id(text):
    """Accepts a raw ID or a full Notion URL (page or database)."""
    text = text.strip()
    path = urlparse(text).path if ("://" in text or "notion.so" in text) else text
    seg = path.rstrip("/").rsplit("/", 1)[-1].replace("-", "")
    m = re.search(r"([0-9a-fA-F]{32})$", seg)
    return m.group(1) if m else text


def extract_date_from_props(properties):
    """Return the first filled date property as YYYY-MM-DD ('' if none)."""
    dates = (p["date"]["start"] for p in properties.values() if p.get("type") == "date" and p.get("date"))
    return next(dates, "")[:10]


def plain(rts):
    return "".join(r.get("plain_text", "") for r in rts or [])


def prop_to_text(prop, date_fmt="YYYY-MM-DD"):
    t = prop.get("type")
    v = prop.get(t)
    if v is None:
        return ""
    if t in ("title", "rich_text"):
        return plain(v)
    if t == "date":
        raw = (v.get("start") or "")[:10]
        return format_date(raw, date_fmt) if raw else ""
    if t in ("select", "status"):
        return v.get("name", "")
    if t == "multi_select":
        return ", ".join(x.get("name", "") for x in v)
    if t in ("people",):
        return ", ".join(x.get("name") or "" for x in v)
    if t in ("created_by", "last_edited_by"):
        return v.get("name") or ""
    if t == "checkbox":
        return "Yes" if v else "No"
    if t in ("created_time", "last_edited_time"):
        return format_date(str(v)[:10], date_fmt)
    if t in ("number", "url", "email", "phone_number"):
        return str(v)
    if t == "files":
        return ", ".join(x.get("name", "") for x in v)
    if t == "unique_id":
        return f"{v.get('prefix') or ''}{'-' if v.get('prefix') else ''}{v.get('number', '')}"
    if t == "formula":
        ft = v.get("type")
        fv = v.get(ft)
        if isinstance(fv, dict):
            fv = fv.get("start")
        if fv is None:
            return ""
        if ft == "date":
            return format_date(str(fv)[:10], date_fmt)
        return str(fv)
    return ""


def page_title(page):
    return next((prop_to_text(v) for v in page["properties"].values() if v["type"] == "title"), "") or "Untitled"


def page_fields(page, index=0, pad=3):
    props = page["properties"]
    f = {
        "title": page_title(page),
        "date": extract_date_from_props(props),
        "created": page.get("created_time", "")[:10],
        "edited": page.get("last_edited_time", "")[:10],
        "parent": "",
    }
    for k, v in props.items():
        txt = prop_to_text(v)
        if txt or k.lower() not in f:
            f[k.lower()] = txt
    f["index"] = f"{index:0{pad}d}"
    return f


def passes_filter(page, prop, op, value):
    if not prop or not value:
        return True
    text = page_fields(page).get(prop.strip().lower(), "").lower()
    v = value.strip().lower()
    if op == "contains":
        return v in text
    if op == "does not contain":
        return v not in text
    return text == v


def sort_pages(pages, by, desc):
    if by == "Database order":
        return list(reversed(pages)) if desc else list(pages)
    k = by.strip().lower()

    def key(p):
        f = page_fields(p)
        if k == "last edited":
            return f["edited"]
        return f.get(k, "").lower()

    return sorted(pages, key=key, reverse=desc)


def query_all(notion, database_id, limit=None):
    """Fetch rows of a database; works with the classic and newer data-source API."""

    def paginate(fn, **base):
        out, cursor = [], None
        while True:
            size = min(100, limit - len(out)) if limit else 100
            kw = dict(base, page_size=size)
            if cursor:
                kw["start_cursor"] = cursor
            resp = api(fn, **kw)
            out.extend(resp.get("results", []))
            if (limit and len(out) >= limit) or not resp.get("has_more"):
                return out[:limit] if limit else out
            cursor = resp.get("next_cursor")

    classic = getattr(notion.databases, "query", None)  # removed in notion-client 3.x
    first = None
    if classic is not None:
        try:
            return paginate(classic, database_id=database_id)
        except Exception as e:
            first = e
    ds_api = getattr(notion, "data_sources", None)
    if ds_api is None:
        raise Exception("Could not access the database. " + str(first))
    try:
        db = api(notion.databases.retrieve, database_id=database_id)
        sources = db.get("data_sources") or []
        if not sources:
            raise first or Exception("the database has no data source")
        return paginate(ds_api.query, data_source_id=sources[0]["id"])  # first data source only
    except Exception as e:
        raise Exception("Could not access the database. " + str(first or e))


def resolve_roots(notion, source_text, source_type):
    """Turn IDs/URLs (space or comma separated) into page objects."""
    tokens = [t for t in re.split(r"[\s,;]+", source_text.strip()) if t]
    if not tokens:
        raise Exception("Enter a database or page ID / URL.")
    roots, seen = [], set()
    for tok in tokens:
        _id = parse_database_id(tok)
        got = None
        if source_type in ("Auto-detect", "Single page"):
            try:
                got = [api(notion.pages.retrieve, page_id=_id)]
            except Exception as e:
                if source_type == "Single page":
                    raise Exception("Could not open the page. " + str(e))
        if got is None:
            got = query_all(notion, _id)
        for p in got:
            if p["id"] not in seen:
                seen.add(p["id"])
                roots.append(p)
    return roots


def load_property_names(notion, source_text, source_type):
    tok = re.split(r"[\s,;]+", source_text.strip())[0]
    _id = parse_database_id(tok)
    if source_type in ("Auto-detect", "Single page"):
        try:
            return list(api(notion.pages.retrieve, page_id=_id)["properties"].keys())
        except Exception:
            if source_type == "Single page":
                raise
    try:
        db = api(notion.databases.retrieve, database_id=_id)
        if db.get("properties"):
            return list(db["properties"].keys())
    except Exception:
        pass
    pages = query_all(notion, _id, limit=1)
    if not pages:
        raise Exception("The database is empty or not shared with your integration.")
    return list(pages[0]["properties"].keys())


LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")


def build_tree(notion, block_id, cache):
    """Fetch all blocks of a page/block recursively (sub-pages are not entered)."""
    if block_id in cache:
        return cache[block_id]
    out, cursor = [], None
    while True:
        kw = {"block_id": block_id, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        resp = api(notion.blocks.children.list, **kw)
        out.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    for b in out:
        t = b["type"]
        if t in ("child_page", "child_database") or not b.get("has_children"):
            continue
        cid = b["id"]
        if t == "synced_block":
            cid = ((b["synced_block"].get("synced_from") or {}).get("block_id")) or cid
        try:
            b["children"] = build_tree(notion, cid, cache)
        except Exception:
            b["children"] = []
    cache[block_id] = out
    return out


def walk(blocks, subs=True):
    for b in blocks:
        yield b
        yield from walk(b.get("children", []), subs)
        if subs and b.get("_sub"):
            yield from walk(b["_sub"]["tree"], subs)


def attach_inline(notion, blocks, cache, depth, maxdepth):
    """Load sub-pages found inside `blocks` so they render inside the parent."""
    for b in list(walk(blocks, subs=False)):
        if b["type"] == "child_page" and depth <= maxdepth:
            try:
                tree = build_tree(notion, b["id"], cache)
            except Exception:
                continue
            b["_sub"] = {"title": b["child_page"].get("title") or "Untitled", "tree": tree}
            attach_inline(notion, tree, cache, depth + 1, maxdepth)


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_private(x) for x in obj]
    return obj


def has_unsupported_markdown_blocks(blocks):
    """Check if a block tree contains block types not supported by retrieve_markdown."""
    for b in blocks:
        t = b.get("type")
        if t in UNSUPPORTED_MD_BLOCKS:
            return True
        if b.get("has_children") or b.get("children"):
            if has_unsupported_markdown_blocks(b.get("children", [])):
                return True
    return False


def retrieve_markdown_page(notion, page_id, include_transcript=False):
    """Retrieve a page's markdown via the Notion API's retrieve_markdown endpoint.

    Returns the markdown string on success, or None if:
    - The API endpoint is not available (notion-client < 3.x)
    - The page contains unsupported block types
    - Any other error occurs
    """
    try:
        # Check if pages.retrieve_markdown is available
        if not hasattr(notion.pages, "retrieve_markdown"):
            return None

        result = api(notion.pages.retrieve_markdown, page_id=page_id, include_transcript=include_transcript)
        return result.get("markdown") if isinstance(result, dict) else result
    except Exception:
        return None


def retrieve_markdown_with_fallback(notion, page_id, tree, include_transcript=False):
    """Retrieve markdown for a page, using fast API path with custom converter fallback.

    Returns:
        (markdown_string, used_fast_api: bool) - markdown and whether fast API was used

    Strategy:
    1. If fast_markdown is enabled and page has no unsupported blocks, try API
    2. Fall back to custom converter if API fails or blocks are unsupported
    """
    # Check if tree contains unsupported block types
    if has_unsupported_markdown_blocks(tree if tree else []):
        return None, False  # Force custom converter

    md = retrieve_markdown_page(notion, page_id, include_transcript)
    if md is not None:
        return md, True

    return None, False
