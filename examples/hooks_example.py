"""Example PageOut hooks.  Use:  pageout export <url> -f md --hooks examples/hooks_example.py
(or  hooks: [examples/hooks_example.py]  in pageout.yaml).  Hook files are normal Python: trust them."""


def filter_page(page):
    """Skip drafts: pages whose 'status' property says draft."""
    return "draft" not in page.get("status", "").lower()


def transform_node(block, doc):
    """Drop callouts that start with 'INTERNAL', turn every H1 into H2."""
    if block.kind == "callout" and block.text and block.text[0].text.startswith("INTERNAL"):
        return None
    if block.kind == "heading" and block.level == 1:
        block.level = 2
    return block


def transform_frontmatter(fm, doc):
    """Add the page id to Markdown front matter."""
    fm["notion_id"] = doc.id
    return fm
