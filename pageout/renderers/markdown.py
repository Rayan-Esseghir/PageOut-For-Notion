"""Markdown renderer (reads IR only)."""

import json

from pageout.core.ir import LIST_KINDS, Asset, plain_text


def _wrap_ws(s, left, right):
    core = s.strip()
    if not core:
        return s
    lead = s[: len(s) - len(s.lstrip())]
    tail = s[len(s.rstrip()) :]
    return f"{lead}{left}{core}{right}{tail}"


def rt_md(rts, r):
    out = []
    for x in rts or []:
        s = f"${x.equation}$" if x.equation is not None else x.text
        vanilla = r.md_preset == "Vanilla"
        if x.code:
            s = _wrap_ws(s, "`", "`")
        if x.bold:
            s = _wrap_ws(s, "**", "**")
        if x.italic:
            s = _wrap_ws(s, "*", "*")
        if x.strike and not vanilla:
            s = _wrap_ws(s, "~~", "~~")
        if x.underline and not vanilla:
            s = _wrap_ws(s, "<u>", "</u>")
        wiki = r.wikilink(x) if r.md_preset == "Obsidian" else None
        if wiki:
            shown = x.text.strip()
            s = _wrap_ws(s, f"[[{wiki}|", "]]") if shown and shown != wiki else f"[[{wiki}]]"
            out.append(s)
            continue
        href = r.href_for(x)
        if href:
            s = _wrap_ws(s, "[", f"]({href})")
        out.append(s)
    return "".join(out)


def _trim(lines):
    while lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def blocks_md(blocks, r, depth=0):
    lines, num, prev = [], 0, None
    pad = "    " * depth
    for b in blocks:
        t = b.kind
        kids = b.children
        num = num + 1 if t == "numbered" else 0
        text = rt_md(b.text, r)
        if t in LIST_KINDS:
            if prev in LIST_KINDS and prev != t and lines and lines[-1] != "":
                lines.append("")
            prev = t
            if t == "bulleted":
                marker = "- "
            elif t == "numbered":
                marker = f"{num}. "
            else:
                if r.md_preset == "Vanilla":
                    marker = "- ☑ " if b.checked else "- ☐ "
                else:
                    marker = "- [x] " if b.checked else "- [ ] "
            lines.append(pad + marker + text)
            lines.extend(_trim(blocks_md(kids, r, depth + 1)))
            continue
        prev = t
        if lines and lines[-1] != "":
            lines.append("")
        block = []
        after = kids
        if t in ("paragraph", "text"):
            block = [pad + text]
        elif t == "heading":
            block = [pad + "#" * b.level + " " + text]
        elif t in ("quote", "callout"):
            icon = (b.icon + " ") if (t == "callout" and b.icon) else ""
            inner = (icon + text + "\n" + "\n".join(_trim(blocks_md(kids, r)))).strip("\n")
            if t == "callout" and r.md_preset == "Obsidian":
                inner = "[!note]\n" + inner
            block = [pad + ("> " + ln if ln else ">") for ln in inner.split("\n")]
            after = []
        elif t == "code":
            block = [pad + "```" + b.language] + [pad + ln for ln in plain_text(b.text).split("\n")] + [pad + "```"]
        elif t == "divider":
            block = [pad + "---"]
        elif t == "equation":
            block = [pad + "$$ " + b.expression + " $$"]
        elif t == "image":
            m = b.media
            if m and m.url:
                img = m.asset or Asset(url=m.url)
                block = [pad + f"![{plain_text(m.caption)}]({r.img_src(img)})"]
        elif t == "media":
            m = b.media
            name = m.display_name()
            block = [pad + (f"[{name}]({m.url})" if m.external and r.keep_link(m.url) else name)]
        elif t == "bookmark":
            url = b.url
            block = [pad + (f"[{plain_text(b.caption) or url}]({url})" if r.keep_link(url) else url)]
        elif t == "toggle" and r.md_preset == "Vanilla":  # no raw HTML in vanilla Markdown
            block = [pad + f"**{text}**"] + ([""] + _trim(blocks_md(kids, r, depth)) if kids else [])
            after = []
        elif t == "toggle":
            block = (
                [pad + f"<details><summary>{text}</summary>", ""]
                + _trim(blocks_md(kids, r, depth))
                + ["", pad + "</details>"]
            )
            after = []
        elif t == "table":
            rows = [[rt_md(c, r).replace("|", "\\|").replace("\n", " ") for c in row] for row in b.rows]
            if rows:
                width = max(len(x) for x in rows)
                rows = [x + [""] * (width - len(x)) for x in rows]
                block = [pad + "| " + " | ".join(rows[0]) + " |", pad + "| " + " | ".join(["---"] * width) + " |"] + [
                    pad + "| " + " | ".join(x) + " |" for x in rows[1:]
                ]
            after = []
        elif t == "column_list":
            for c in kids:
                block += _trim(blocks_md(c.children, r, depth)) + [""]
            block = _trim(block)
            after = []
        elif t in ("column", "synced"):
            block = _trim(blocks_md(kids, r, depth))
            after = []
        elif t == "child_page":
            s = b.sub
            if s:
                block = [pad + "## 📄 " + s.title, ""] + _trim(blocks_md(s.blocks, r, depth))
            else:
                block = [pad + "📄 " + b.title]
            after = []
        elif t == "child_database":
            block = [pad + "🗂 " + b.title + " (database)"]
        elif t == "link_to_page":
            pl = r.page_link(b.target_id)
            block = [pad + (f"↪ [{pl[1]}]({pl[0]})" if pl else "↪ linked page")]
        if not block:
            continue
        lines.extend(block)
        lines.append("")
        if after:
            lines.extend(_trim(blocks_md(after, r, depth + 1)))
            lines.append("")
    return _trim(lines)


def md_front_matter(title, rows, preset=None):
    out = ["---", "title: " + json.dumps(title, ensure_ascii=False)]
    for k, v in rows:
        if preset == "Obsidian" and k.lower() == "tags":  # Obsidian reads tags as a YAML list
            tags = [t.strip() for t in str(v).split(",") if t.strip()]
            out.append("tags: " + json.dumps(tags, ensure_ascii=False))
            continue
        out.append(f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}")
    out.append("---")
    return "\n".join(out)


def wrap_markdown(title, content, cfg, frontmatter="", use_template=True):
    """Wrap content in Markdown template.

    If use_template=True and custom template is configured, uses that.
    Otherwise falls back to default structure.
    """
    template_name = cfg.get("template", "page")

    if use_template:
        try:
            from pageout.core.templates import TemplateError, load_template, template_exists

            if template_exists(template_name, "md"):
                tmpl = load_template(template_name, "md")
                context = {
                    "title": title,
                    "content": content,
                    "frontmatter": frontmatter,
                }
                return tmpl.render(context)
        except TemplateError:
            pass  # Fall back to default structure

    # Default structure
    result = f"# {title}\n"
    if frontmatter:
        result += f"\n{frontmatter}\n"
    result += f"\n{content}"
    return result + "\n"
