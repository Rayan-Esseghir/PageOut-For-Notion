"""reStructuredText renderer (reads IR only)."""

from pageout.core.ir import LIST_KINDS, Asset, plain_text
from pageout.renderers.base import R


def escape_rst(s: str) -> str:
    """Escape reStructuredText special characters."""
    if not s:
        return ""
    # Backslashes are extremely dangerous, escape them first
    s = s.replace("\\", "\\\\")
    # Escape asterisks
    s = s.replace("*", "\\*")
    # Escape backticks (code literal delimiter)
    s = s.replace("`", "\\`")
    # Escape caret for substitution
    s = s.replace("^", "\\^")
    # Escape quotes (for field lists)
    s = s.replace('"', '\\"')
    # Escape colon at start of line (for comments)
    return s


def rt_rst(rts, r):
    """Convert rich text runs to reStructuredText inline markup."""
    out = []
    for x in rts or []:
        s = x.equation if x.equation is not None else escape_rst(x.text)
        if x.equation:
            # Render math as code literal or use math directive
            s = f"``{s}``"
        if x.code:
            s = f"``{s}``"
        if x.bold:
            s = f"**{s}**"
        if x.italic:
            s = f"*{s}*"
        if x.strike:
            s = f"~~{s}~~"
        if x.underline:
            s = f"[[{s}]]"
        href = r.href_for(x)
        if href:
            # reStructuredText external links
            s = f"`{s} <{href}>_`"
        out.append(s)
    return "".join(out)


def _trim(lines):
    """Remove trailing empty lines from a list."""
    while lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def blocks_rst(blocks, r, depth=0):
    """Convert IR blocks to reStructuredText."""
    lines, num, prev = [], 0, None
    pad = "    " * depth

    for b in blocks:
        t = b.kind
        kids = b.children
        num = num + 1 if t == "numbered" else 0
        text = rt_rst(b.text, r)

        if t in LIST_KINDS:
            if prev in LIST_KINDS and prev != t and lines and lines[-1] != "":
                lines.append("")
            prev = t
            if t == "bulleted":
                marker = "- "
            elif t == "numbered":
                marker = f"{num}. "
            else:  # todo
                marker = f"{'[x] ' if b.checked else '[ ] '}"
            lines.append(pad + marker + text)
            lines.extend(_trim(blocks_rst(kids, r, depth + 1)))
            continue
        prev = t
        if lines and lines[-1] != "":
            lines.append("")

        block = []
        after = kids

        if t in ("paragraph", "text"):
            block = [pad + text]
        elif t == "heading":
            # reStructuredText uses underlines
            level_chars = ["=", "-", "~", "^", '"', "'", "&"]
            if b.level <= len(level_chars):
                underline = level_chars[b.level - 1] * max(len(text), 3)
                if depth > 0:
                    lines.append(pad + text)
                    lines.append(pad + underline)
                else:
                    block = [pad + text, pad + underline]
            else:
                block = [pad + text]
        elif t in ("quote", "callout"):
            prefix = ""
            if t == "callout" and b.icon:
                prefix = f"{b.icon} "
            inner = prefix + text
            if b.icon or t == "callout":
                # Use admonition directive for callouts
                lines.append(pad + ".. note::")
                lines.extend(pad + "   " + ln for ln in inner.split("\n"))
                block = []
            else:
                block = [pad + ("> " + ln if ln else ">") for ln in inner.split("\n")]
            after = []
        elif t == "code":
            lang = b.language or "code"
            block = [pad + ".. code-block:: " + lang, ""]
            block.extend([pad + "    " + ln for ln in plain_text(b.text).split("\n")])
        elif t == "divider":
            block = [pad + "|" + "-" * 20 + "|"]
        elif t == "equation":
            block = [pad + ".. math::", ""]
            block.extend([pad + "    " + ln for ln in b.expression.split("\n")])
        elif t == "image":
            m = b.media
            if m and m.url:
                img = m.asset or Asset(url=m.url)
                n = r.cfg.get("img_handling", "Embed in file")
                if n == "Embed in file" and img.bytes:
                    # Use inline image with data URI (won't work in all readers)
                    from pageout.core.assets import data_uri

                    block = [pad + f".. image:: {data_uri(img)}", ""]
                else:
                    # Use external link or local path
                    block = [pad + f".. image:: {r.img_src(img)}"]
                    caption = plain_text(m.caption)
                    if caption:
                        block.append(pad + "   :alt: " + caption)
        elif t == "media":
            m = b.media
            name = m.display_name()
            block = [pad + ".. list-table::", ""]
            block.append(pad + "   * - " + name)
        elif t == "bookmark":
            block = [pad + b.url]
        elif t == "toggle":
            # Use toggle directive or just bold heading
            block = [pad + f"**{text}**"]
            if r.expand:
                if kids:
                    block += [""] + _trim(blocks_rst(kids, r, depth))
            after = []
        elif t == "table":
            rows = [[escape_rst(rt_rst(c, r).replace("|", "\\|")) for c in row] for row in b.rows]
            if rows:
                width = max(len(x) for x in rows)
                rows = [x + [""] * (width - len(x)) for x in rows]
                block = [
                    pad + ".. list-table::",
                    pad + "   :widths: " + " ".join(["20"] * width),
                    pad + "   :header-rows: 1",
                    "",
                ]
                for row in rows:
                    block.append(pad + "   * - " + " - ".join(row))
            after = []
        elif t == "column_list":
            for c in kids:
                block += _trim(blocks_rst(c.children, r, depth)) + [""]
            block = _trim(block)
            after = []
        elif t in ("column", "synced"):
            block = _trim(blocks_rst(kids, r, depth))
            after = []
        elif t == "child_page":
            s = b.sub
            if s:
                block = [pad + f"../ {s.title}", ""]
                block.extend(_trim(blocks_rst(s.blocks, r, depth)))
            else:
                block = [pad + b.title]
            after = []
        elif t == "child_database":
            block = [pad + ".. container:: database", ""]
            block.extend([pad + "   " + b.title + " (database)"])
        elif t == "link_to_page":
            pl = r.page_link(b.target_id)
            block = [pad + f"↪ {pl[1] if pl else 'linked page'}"]
        if not block:
            continue
        lines.extend(block)
        lines.append("")
        if after:
            lines.extend(_trim(blocks_rst(after, r, depth + 1)))
            lines.append("")
    return _trim(lines)


def wrap_rst(title: str, content: str, cfg: dict, frontmatter: str = "") -> str:
    """Wrap content in reStructuredText document structure.

    If use_template=True and custom template is configured, uses that.
    Otherwise falls back to default structure.
    """
    template_name = cfg.get("template", "page")

    # Try to use custom template
    use_template = cfg.get("use_template", True)
    if use_template:
        try:
            from pageout.core.templates import TemplateError, load_template, template_exists

            if template_exists(template_name, "rst"):
                tmpl = load_template(template_name, "rst")
                context = {
                    "title": title,
                    "content": content,
                    "frontmatter": frontmatter,
                }
                return tmpl.render(context)
        except TemplateError:
            pass  # Fall back to default structure

    # Default structure
    underlines = {
        1: "=",
        2: "-",
        3: "~",
        4: "^",
        5: '"',
    }
    title_line = title
    title_underline = underlines.get(1, "=") * len(title)

    result = f"{title_line}\n{title_underline}\n"
    if frontmatter:
        result += f"\n{frontmatter}\n"
    result += f"\n{content}"
    return result + "\n"


def build_rst(title: str, rows: list, tree, r: R, cfg: dict) -> str:
    """Build complete reStructuredText document.

    Args:
        title: Page title
        rows: Property rows as list of (key, value) tuples
        tree: Block tree from IR
        r: Rendering context
        cfg: Configuration dict

    Returns:
        Complete reStructuredText document as string
    """
    # Build front matter
    frontmatter_parts = []
    for k, v in rows:
        frontmatter_parts.append(f"{k}: {escape_rst(v)}")
    frontmatter = "\n".join(frontmatter_parts) if frontmatter_parts else ""

    # Build body
    body = "\n".join(blocks_rst(tree, r))

    # Wrap in document structure
    return wrap_rst(title, body, cfg, frontmatter) + "\n"
