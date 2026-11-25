"""Database export modes: index page, table of properties, CSV."""

import csv
import html as _html
import os

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


def index_markdown(title, items, link_path, index_path, date_fmt, with_table, props_fn):
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


def index_html_body(title, items, link_path, index_path, date_fmt, with_table, props_fn):
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
