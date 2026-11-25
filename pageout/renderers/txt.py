"""Plain-text renderer (reads IR only)."""

from pageout.core.ir import plain_text


def blocks_txt(blocks, depth=0):
    lines, num = [], 0
    pad = "  " * depth
    for b in blocks:
        t = b.kind
        kids = b.children
        num = num + 1 if t == "numbered" else 0
        text = plain_text(b.text)
        if t == "bulleted":
            lines.append(f"{pad}• {text}")
        elif t == "numbered":
            lines.append(f"{pad}{num}. {text}")
        elif t == "todo":
            lines.append(f"{pad}[{'x' if b.checked else ' '}] {text}")
        elif t == "heading":
            lines += ["", pad + text.upper() if b.level == 1 else pad + text, ""]
        elif t == "divider":
            lines.append(pad + "-" * 30)
        elif t == "image":
            cap = b.media.caption if b.media else []
            lines.append(f"{pad}[Image{': ' + plain_text(cap) if cap else ''}]")
        elif t == "table":
            for row in b.rows:
                lines.append(pad + "\t".join(plain_text(c) for c in row))
            kids = []
        elif t == "child_page":
            s = b.sub
            lines += ["", f"{pad}== {(s.title if s else None) or b.title} =="]
            if s:
                lines += blocks_txt(s.blocks, depth)
        elif t == "equation":
            lines.append(pad + b.expression)
        elif t == "bookmark":
            lines.append(pad + b.url)
        elif t == "code":
            lines += [pad + ln for ln in text.split("\n")]
        elif t in ("column_list", "column", "synced"):
            lines += blocks_txt(kids, depth)
            kids = []
        elif t in ("paragraph", "text", "quote", "callout", "toggle"):
            lines.append(pad + text)
        if kids:
            lines += blocks_txt(kids, depth + 1)
    return lines
