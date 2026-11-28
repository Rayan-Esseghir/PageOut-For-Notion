"""AsciiDoc renderer (reads IR only)."""

from pageout.core.ir import LIST_KINDS, Asset, plain_text
from pageout.renderers.base import R


def escape_asciidoc(s: str) -> str:
    """Escape AsciiDoc special characters."""
    if not s:
        return ""
    # Backslashes are extremely dangerous, escape them first
    s = s.replace("\\", "\\\\")
    # Escape asterisks for bold/italic
    s = s.replace("*", "\\*")
    # Escape underscores (often used for emphasis)
    s = s.replace("_", "\\_")
    # Escape plus signs (for inline literal)
    s = s.replace("+", "\\+")
    # Escape braces
    s = s.replace("{", "\\{")
    s = s.replace("}", "\\}")
    # Escape brackets
    s = s.replace("[", "\\[")
    s = s.replace("]", "\\]")
    # Escape colons (attribute lists)
    s = s.replace(":", "\\:")
    # Escape apostrophes
    s = s.replace("'", "\\'")
    return s


def rt_adoc(rts, r):
    """Convert rich text runs to AsciiDoc inline markup."""
    out = []
    for x in rts or []:
        s = x.equation if x.equation is not None else escape_asciidoc(x.text)
        if x.equation:
            # Render math as code literal or use math block
            s = f"`{s}`"
        if x.code:
            s = f"``{s}``"
        if x.bold:
            s = f"**{s}**"
        if x.italic:
            s = f"*{s}*"
        if x.strike:
            s = f"~~{s}~~"
        if x.underline:
            s = f"___{s}___"
        href = r.href_for(x)
        if href:
            # AsciiDoc external links
            s = f"link:{href}[{s}]"
        out.append(s)
    return "".join(out)


def _trim(lines):
    """Remove trailing empty lines from a list."""
    while lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def blocks_asciidoc(blocks, r, depth=0):
    """Convert IR blocks to AsciiDoc."""
    lines, num, prev = [], 0, None
    pad = "    " * depth

    for b in blocks:
        t = b.kind
        kids = b.children
        num = num + 1 if t == "numbered" else 0
        text = rt_adoc(b.text, r)

        if t in LIST_KINDS:
            if prev in LIST_KINDS and prev != t and lines and lines[-1] != "":
                lines.append("")
            prev = t
            if t == "bulleted":
                marker = "*"
            elif t == "numbered":
                marker = "."
            else:  # todo
                marker = f"* {'x' if b.checked else ' '}"
            lines.append(pad + marker + " " + text)
            lines.extend(_trim(blocks_asciidoc(kids, r, depth + 1)))
            continue
        prev = t
        if lines and lines[-1] != "":
            lines.append("")

        block = []
        after = kids

        if t in ("paragraph", "text"):
            block = [pad + text]
        elif t == "heading":
            # AsciiDoc uses underlines or over/under
            level_chars = ["=", "==", "===", "====", "~~~~~"]
            if b.level <= len(level_chars):
                underline = level_chars[b.level - 1]
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
            if t == "callout":
                # Use admonition for callouts
                lines.append(pad + f".[{b.icon or 'NOTE'}]")
                lines.append(pad + "[source,note]")
                lines.extend(pad + "----" for _ in range(1))
                lines.extend(pad + ln for ln in inner.split("\n"))
                lines.append(pad + "----")
                block = []
            else:
                # Blockquote
                lines.append(pad + "[quote]")
                lines.append(pad + "____")
                lines.extend(pad + "  " + ln for ln in inner.split("\n"))
                lines.append(pad + "____")
                block = []
            after = []
        elif t == "code":
            lang = b.language or "asciidoc"
            block = [pad + "----", pad + f"[{lang}]"]
            block.extend([pad + ln for ln in plain_text(b.text).split("\n")])
            block.append(pad + "----")
        elif t == "divider":
            block = [pad + "''''"]
        elif t == "equation":
            block = [pad + ".. latexmath::", ""]
            block.extend([pad + "    " + ln for ln in b.expression.split("\n")])
        elif t == "image":
            m = b.media
            if m and m.url:
                img = m.asset or Asset(url=m.url)
                n = r.cfg.get("img_handling", "Embed in file")
                if n == "Embed in file" and img.bytes:
                    from pageout.core.assets import data_uri

                    block = [pad + f"image::{data_uri(img)}[link]"]
                else:
                    block = [pad + f"image::{r.img_src(img)}[link]"]
                caption = plain_text(m.caption)
                if caption:
                    block.append(pad + f".{escape_asciidoc(caption)}")
        elif t == "media":
            m = b.media
            name = m.display_name()
            block = [pad + f".{escape_asciidoc(name)}"]
        elif t == "bookmark":
            block = [pad + f"link:{b.url}[{escape_asciidoc(b.url)}]"]
        elif t == "toggle":
            # Use collapsible section for toggles
            if r.expand:
                lines.append(pad + "[%collapsible]")
                lines.append(pad + f".{text}")
                lines.append(pad + "====>")
                if kids:
                    lines.extend(_trim(blocks_asciidoc(kids, r, depth + 1)))
                lines.append(pad + "<==")
                block = []
                after = []
            else:
                block = [pad + f"**{text}**"]
        elif t == "table":
            rows = [[escape_asciidoc(rt_adoc(c, r)) for c in row] for row in b.rows]
            if rows:
                width = max(len(x) for x in rows)
                rows = [x + [""] * (width - len(x)) for x in rows]
                block = [pad + "[options(header,cols=" + ",".join(["*"] * width) + ")"]
                block.append(pad + "|===")
                for row in rows:
                    block.append(pad + " | ".join(row))
                block.append(pad + "|===")
            after = []
        elif t == "column_list":
            for c in kids:
                block += _trim(blocks_asciidoc(c.children, r, depth)) + [""]
            block = _trim(block)
            after = []
        elif t in ("column", "synced"):
            block = _trim(blocks_asciidoc(kids, r, depth))
            after = []
        elif t == "child_page":
            s = b.sub
            if s:
                block = [pad + f"Link:{s.title}[{s.title}]", ""]
                block.extend(_trim(blocks_asciidoc(s.blocks, r, depth)))
            else:
                block = [pad + f"Link:{b.title}[{b.title}]"]
            after = []
        elif t == "child_database":
            block = [pad + f".Database: {b.title}"]
        elif t == "link_to_page":
            pl = r.page_link(b.target_id)
            block = [pad + f"Link:{pl[1] if pl else 'linked page'}[{pl[1] if pl else 'linked page'}]"]
        if not block:
            continue
        lines.extend(block)
        lines.append("")
        if after:
            lines.extend(_trim(blocks_asciidoc(after, r, depth + 1)))
            lines.append("")
    return _trim(lines)


def wrap_asciidoc(title: str, content: str, cfg: dict, frontmatter: str = "") -> str:
    """Wrap content in AsciiDoc document structure.

    If use_template=True and custom template is configured, uses that.
    Otherwise falls back to default structure.
    """
    template_name = cfg.get("template", "page")

    # Try to use custom template
    use_template = cfg.get("use_template", True)
    if use_template:
        try:
            from pageout.core.templates import TemplateError, load_template, template_exists

            if template_exists(template_name, "adoc"):
                tmpl = load_template(template_name, "adoc")
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
        2: "==",
        3: "===",
        4: "====",
        5: "~~~~~",
    }
    title_line = f"={title}"

    result = f"{title_line}\n"
    if frontmatter:
        result += f"\n{frontmatter}\n"
    result += f"\n{content}"
    return result + "\n"


def build_asciidoc(title: str, rows: list, tree, r: R, cfg: dict) -> str:
    """Build complete AsciiDoc document.

    Args:
        title: Page title
        rows: Property rows as list of (key, value) tuples
        tree: Block tree from IR
        r: Rendering context
        cfg: Configuration dict

    Returns:
        Complete AsciiDoc document as string
    """
    # Build front matter
    frontmatter_parts = []
    for k, v in rows:
        frontmatter_parts.append(f"{k}: {escape_asciidoc(v)}")
    frontmatter = "\n".join(frontmatter_parts) if frontmatter_parts else ""

    # Build body
    body = "\n".join(blocks_asciidoc(tree, r))

    # Wrap in document structure
    return wrap_asciidoc(title, body, cfg, frontmatter) + "\n"
