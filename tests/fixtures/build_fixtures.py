"""Generates tests/fixtures/*.json (Notion-API-shaped responses).
Run only when you intentionally change fixtures:  python tests/fixtures/build_fixtures.py
The JSON files are committed; tests never call the real Notion API."""

import json
from pathlib import Path

HERE = Path(__file__).parent
_n = [0]


def nid():
    _n[0] += 1
    return f"{_n[0]:032x}"


def rt(text, href=None, **ann):
    a = dict(bold=False, italic=False, strikethrough=False, underline=False, code=False, color="default")
    a.update(ann)
    return {
        "type": "text",
        "text": {"content": text, "link": {"url": href} if href else None},
        "annotations": a,
        "plain_text": text,
        "href": href,
    }


def mention(text, page_id):
    a = dict(bold=False, italic=False, strikethrough=False, underline=False, code=False, color="default")
    return {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": page_id}},
        "annotations": a,
        "plain_text": text,
        "href": "https://www.notion.so/" + page_id,
    }


def eq(expr):
    a = dict(bold=False, italic=False, strikethrough=False, underline=False, code=False, color="default")
    return {"type": "equation", "equation": {"expression": expr}, "annotations": a, "plain_text": expr, "href": None}


BLOCKS = {}


def block(t, data, children=None, bid=None):
    bid = bid or nid()
    b = {
        "object": "block",
        "id": bid,
        "type": t,
        "has_children": bool(children),
        "created_time": "2024-01-01T00:00:00.000Z",
        "last_edited_time": "2024-01-02T00:00:00.000Z",
        t: data,
    }
    if children:
        BLOCKS[bid] = children
    return b


def para(*r, children=None):
    return block("paragraph", {"rich_text": list(r), "color": "default"}, children)


def page_obj(pid, title, date, tags, icon="📘"):
    return {
        "object": "page",
        "id": pid,
        "created_time": "2024-01-01T00:00:00.000Z",
        "last_edited_time": "2024-03-05T10:00:00.000Z",
        "icon": {"type": "emoji", "emoji": icon},
        "cover": None,
        "properties": {
            "Name": {"id": "title", "type": "title", "title": [rt(title)]},
            "Date": {"id": "d", "type": "date", "date": {"start": date, "end": None}},
            "Tags": {"id": "t", "type": "multi_select", "multi_select": [{"name": x} for x in tags]},
            "Done": {"id": "c", "type": "checkbox", "checkbox": True},
            "Score": {"id": "n", "type": "number", "number": 42},
        },
    }


# ---------------- full page ----------------
FULL, EMPTY, SUB = "a" * 32, "b" * 32, "c" * 32

sub_child = para(rt("Text inside the sub-page."))
BLOCKS[SUB] = [
    sub_child,
    block("heading_2", {"rich_text": [rt("Sub heading")], "color": "default", "is_toggleable": False}),
]

root = [
    block("heading_1", {"rich_text": [rt("Main heading")], "color": "default", "is_toggleable": False}),
    para(
        rt("Plain, "),
        rt("bold", bold=True),
        rt(", "),
        rt("italic", italic=True),
        rt(", "),
        rt("code", code=True),
        rt(", "),
        rt("strike", strikethrough=True),
        rt(", "),
        rt("under", underline=True),
        rt(", "),
        rt("red text", color="red"),
        rt(", "),
        rt("bg", color="yellow_background"),
        rt(". 100% $ & # _ { } ~ ^ \\ chars."),
    ),
    para(
        rt(
            "External ",
        ),
        rt("link", href="https://example.com/a?b=1#c"),
        rt(" and "),
        rt("internal", href="/aabbccddeeff00112233445566778899"),
        rt(" and inline math "),
        eq("E=mc^2"),
    ),
    para(rt("See "), rt("the empty page", href="/" + EMPTY), rt(" and "), mention("Empty page", EMPTY), rt(".")),
    block("link_to_page", {"type": "page_id", "page_id": EMPTY}),
    para(rt("مرحبا بالعالم، هذا نص عربي.")),
    para(),
    block(
        "bulleted_list_item",
        {"rich_text": [rt("Bullet one")], "color": "default"},
        [block("bulleted_list_item", {"rich_text": [rt("Nested bullet")], "color": "default"})],
    ),
    block("bulleted_list_item", {"rich_text": [rt("Bullet two")], "color": "default"}),
    block("numbered_list_item", {"rich_text": [rt("First")], "color": "default"}),
    block("numbered_list_item", {"rich_text": [rt("Second")], "color": "default"}),
    block("to_do", {"rich_text": [rt("Done task")], "checked": True, "color": "default"}),
    block("to_do", {"rich_text": [rt("Open task")], "checked": False, "color": "default"}),
    block(
        "toggle",
        {"rich_text": [rt("Toggle title")], "color": "default"},
        [
            para(rt("Hidden content")),
            block("toggle", {"rich_text": [rt("Nested toggle")], "color": "default"}, [para(rt("Deep content"))]),
        ],
    ),
    block("quote", {"rich_text": [rt("A wise quote.")], "color": "default"}),
    block(
        "callout",
        {"rich_text": [rt("Callout text")], "icon": {"type": "emoji", "emoji": "⚠️"}, "color": "yellow_background"},
    ),
    block(
        "code",
        {"rich_text": [rt("def f(x):\n    return x < 2 & 1")], "language": "python", "caption": [rt("Code caption")]},
    ),
    block("divider", {}),
    block("equation", {"expression": "\\int_0^1 x^2\\,dx = \\frac13"}),
    block(
        "image",
        {"type": "external", "external": {"url": "https://example.com/pics/fig1.png"}, "caption": [rt("Figure one")]},
    ),
    block("image", {"type": "external", "external": {"url": "https://example.com/pics/fig2.jpg"}, "caption": []}),
    block(
        "table",
        {"table_width": 2, "has_column_header": True, "has_row_header": False},
        [
            block("table_row", {"cells": [[rt("H1")], [rt("H2")]]}),
            block("table_row", {"cells": [[rt("a|b")], [rt("c & d")]]}),
        ],
    ),
    block(
        "column_list",
        {},
        [
            block("column", {}, [para(rt("Left column"))]),
            block("column", {}, [para(rt("Right column"))]),
        ],
    ),
    block("synced_block", {"synced_from": None}, [para(rt("Synced original"))]),
    block("bookmark", {"url": "https://example.org/read", "caption": [rt("A bookmark")]}),
    block(
        "file",
        {
            "type": "external",
            "external": {"url": "https://example.org/doc.pdf"},
            "caption": [rt("Attached doc")],
            "name": "doc.pdf",
        },
    ),
    block("child_page", {"title": "Sub page"}, bid=SUB),
    block("child_database", {"title": "Inner DB"}),
]
BLOCKS[FULL] = root

# ---------------- empty page ----------------
BLOCKS[EMPTY] = []

PAGES = {
    FULL: page_obj(FULL, "Full: Test/Page?", "2024-03-05", ["alpha", "beta"]),
    EMPTY: page_obj(EMPTY, "Empty page", "2024-01-10", [], icon="📄"),
}
DB = {"db" + "0" * 30: [FULL, EMPTY]}

(HERE / "notion_fixture.json").write_text(
    json.dumps({"pages": PAGES, "blocks": BLOCKS, "databases": DB}, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("written", HERE / "notion_fixture.json")
