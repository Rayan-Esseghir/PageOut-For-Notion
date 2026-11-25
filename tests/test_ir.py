"""IR conversion: Notion JSON is understood in exactly one place."""

from fake_notion import FakeNotion, load_fixture

import pageout.sources.notion_api as napi
from pageout.core.ir import plain_text, walk
from pageout.sources.notion_ir import page_id_from_href, to_document

FULL = "a" * 32


def doc():
    fx = load_fixture()
    tree = napi.build_tree(FakeNotion(fx), FULL, {})
    return to_document(fx["pages"][FULL], "Full", tree, FULL)


def test_block_kinds_and_nesting():
    d = doc()
    kinds = [b.kind for b in d.blocks]
    for k in (
        "heading",
        "paragraph",
        "bulleted",
        "numbered",
        "todo",
        "toggle",
        "quote",
        "callout",
        "code",
        "divider",
        "equation",
        "image",
        "table",
        "column_list",
        "synced",
        "bookmark",
        "media",
        "child_page",
        "child_database",
        "link_to_page",
    ):
        assert k in kinds, k
    tg = next(b for b in d.blocks if b.kind == "toggle")
    assert plain_text(tg.text) == "Toggle title" and tg.children[1].kind == "toggle"
    table = next(b for b in d.blocks if b.kind == "table")
    assert table.col_header and plain_text(table.rows[1][0]) == "a|b" and table.children == []


def test_rich_text_flags_and_links():
    d = doc()
    para = next(b for b in d.blocks if b.kind == "paragraph" and any(s.bold for s in b.text))
    flags = {s.text: s for s in para.text}
    assert flags["bold"].bold and flags["italic"].italic and flags["code"].code
    assert flags["strike"].strike and flags["under"].underline and flags["red text"].color == "red"
    ids = {s.page_id for b in d.blocks for s in b.text if s.page_id}
    assert ids == {"b" * 32, "aabbccddeeff00112233445566778899"}  # internal link + page mention


def test_page_id_from_href():
    i = "0123456789abcdef" * 2
    assert page_id_from_href("/" + i) == i
    assert page_id_from_href(f"https://www.notion.so/My-Page-{i}?pvs=4") == i
    assert page_id_from_href("https://example.com/" + i) is None
    assert page_id_from_href(None) is None


def test_properties_are_typed():
    d = doc()
    props = {p.name: p for p in d.properties}
    assert props["Date"].date == "2024-03-05" and props["Date"].text == ""
    assert props["Tags"].text == "alpha, beta" and props["Done"].text == "Yes" and props["Score"].text == "42"
    assert d.icon_emoji == "📘" and d.source["properties"]["Score"]["number"] == 42


def test_walk_includes_subpages_when_asked():
    d = doc()
    sub = next(b for b in d.blocks if b.kind == "child_page")
    from pageout.core.ir import Block, Document

    sub.sub = Document(id="c", title="S", blocks=[Block("paragraph")])
    assert len(list(walk(d.blocks))) == len(list(walk(d.blocks, subs=False))) + 1
