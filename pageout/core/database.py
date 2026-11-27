"""Database export modes: index page, table of properties, CSV."""

import csv
import html as _html
import os
from typing import Optional, Dict, Any

from pageout.core.naming import format_date


def _headers_and_rows(items, date_fmt, props_fn):
    headers = []
    for it in items:
        for p in props_fn(it):
            if p.type != "title" and p.name not in headers:
                headers.append(p.name)
    rows = []
    for it in items:
        props = {
            p.name: (format_date(p.date, date_fmt) if p.date else p.text) for p in props_fn(it) if p.type != "title"
        }
        rows.append((it, [props.get(h, "") for h in headers]))
    return headers, rows


def write_csv(path, items, date_fmt, props_fn):
    headers, rows = _headers_and_rows(items, date_fmt, props_fn)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Title"] + headers)
        for it, vals in rows:
            w.writerow([it.title] + vals)


def _rel(target, index_path):
    from urllib.parse import quote

    return quote(os.path.relpath(target, os.path.dirname(index_path)).replace(os.sep, "/"), safe="/")


def index_markdown(title, items, link_path, index_path, date_fmt, with_table, props_fn, cfg=None):
    """Generate the body Markdown for an index page.

    If cfg has 'use_template' and 'template' settings, uses the template system.
    Otherwise uses the default inline Markdown generation.
    """
    # Check if we should use templates
    if cfg and cfg.get("use_template", True):
        try:
            from pageout.core.templates import TemplateError, template_exists, load_template

            template_name = cfg.get("index_template", "index")
            if template_exists(template_name, "md"):
                tmpl = load_template(template_name, "md")

                # Build content based on with_table setting
                if with_table:
                    headers, rows = _headers_and_rows(items, date_fmt, props_fn)
                    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
                    lines = []
                    lines += [
                        "| Title | " + " | ".join(esc(h) for h in headers) + " |",
                        "| --- | " + " | ".join("---" for _ in headers) + " |",
                    ]
                    for it, vals in rows:
                        link = f"[{esc(it.title)}]({_rel(link_path(it), index_path)})"
                        lines.append("| " + link + " | " + " | ".join(esc(v) for v in vals) + " |")
                    content = "\n".join(lines)
                else:
                    content = "\n".join(
                        f"{'  ' * it.depth}- [{it.title}]({_rel(link_path(it), index_path)})"
                        for it in items
                    )

                context = {
                    "title": title,
                    "content": content,
                }
                return tmpl.render(context)
        except TemplateError:
            pass  # Fall back to default inline generation

    # Default inline Markdown generation
    lines = [f"# {title}", ""]
    if with_table:
        headers, rows = _headers_and_rows(items, date_fmt, props_fn)
        esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines += [
            "| Title | " + " | ".join(esc(h) for h in headers) + " |",
            "| --- | " + " | ".join("---" for _ in headers) + " |",
        ]
        for it, vals in rows:
            link = f"[{esc(it.title)}]({_rel(link_path(it), index_path)})"
            lines.append("| " + link + " | " + " | ".join(esc(v) for v in vals) + " |")
    else:
        for it in items:
            lines.append(f"{'  ' * it.depth}- [{it.title}]({_rel(link_path(it), index_path)})")
    return "\n".join(lines) + "\n"


def index_html_body(title, items, link_path, index_path, date_fmt, with_table, props_fn, cfg=None):
    """Generate the body HTML for an index page.

    If cfg has 'use_template' and 'template' settings, uses the template system.
    Otherwise uses the default inline HTML generation.
    """
    # Check if we should use templates
    if cfg and cfg.get("use_template", True):
        try:
            from pageout.core.templates import TemplateError, template_exists, load_template

            template_name = cfg.get("index_template", "index")
            if template_exists(template_name, "html"):
                tmpl = load_template(template_name, "html")

                # Build content based on with_table setting
                e = _html.escape
                if with_table:
                    headers, rows = _headers_and_rows(items, date_fmt, props_fn)
                    content_parts = ["<table>"]
                    content_parts.append("<tr><th>Title</th>" + "".join(f"<th>{e(h)}</th>" for h in headers) + "</tr>")
                    for it, vals in rows:
                        content_parts.append(
                            f'<tr><td><a href="{e(_rel(link_path(it), index_path), quote=True)}">{e(it.title)}</a></td>'
                            + "".join(f"<td>{e(v)}</td>" for v in vals)
                            + "</tr>"
                        )
                    content_parts.append("</table>")
                    content = "".join(content_parts)
                else:
                    content = (
                        "<ul>"
                        + "".join(
                            f'<li style="margin-left:{it.depth * 1.2}em"><a href="{e(_rel(link_path(it), index_path), quote=True)}">'
                            f"{e(it.title)}</a></li>"
                            for it in items
                        )
                        + "</ul>"
                    )

                context = {
                    "title": title,
                    "content": content,
                }
                return tmpl.render(context)
        except TemplateError:
            pass  # Fall back to default inline generation

    # Default inline HTML generation
    e = _html.escape
    out = [f'<h1 class="notion-title">{e(title)}</h1>']
    if with_table:
        headers, rows = _headers_and_rows(items, date_fmt, props_fn)
        out.append("<table><tr><th>Title</th>" + "".join(f"<th>{e(h)}</th>" for h in headers) + "</tr>")
        for it, vals in rows:
            out.append(
                f'<tr><td><a href="{e(_rel(link_path(it), index_path), quote=True)}">{e(it.title)}</a></td>'
                + "".join(f"<td>{e(v)}</td>" for v in vals)
                + "</tr>"
            )
        out.append("</table>")
    else:
        out.append(
            "<ul>"
            + "".join(
                f'<li style="margin-left:{it.depth * 1.2}em"><a href="{e(_rel(link_path(it), index_path), quote=True)}">'
                f"{e(it.title)}</a></li>"
                for it in items
            )
            + "</ul>"
        )
    return "".join(out)


def index_markdown_template(title, content, cfg=None):
    """Generate index markdown using template system.

    Falls back to default structure if no template available.
    """
    if cfg and cfg.get("use_template", True):
        try:
            from pageout.core.templates import TemplateError, template_exists, load_template

            template_name = cfg.get("index_template", "index")
            if template_exists(template_name, "md"):
                tmpl = load_template(template_name, "md")
                context = {
                    "title": title,
                    "content": content,
                    "frontmatter": "",
                }
                return tmpl.render(context)
        except TemplateError:
            pass

    # Default structure
    return f"# {title}\n\n{content}"
