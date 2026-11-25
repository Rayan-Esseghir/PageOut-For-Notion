"""Vendor KaTeX for offline math rendering.

    npm pack katex@0.16.9 && tar xzf katex-0.16.9.tgz
    python tools/vendor_katex.py path/to/package

Writes pageout/assets/katex/{katex.min.js, katex.inline.css, LICENSE}. Only the woff2 fonts are
embedded (as data: URIs), which keeps the HTML self-contained and ~370 KB.
"""

import base64
import re
import shutil
import sys
from pathlib import Path

pkg = Path(sys.argv[1]) / "dist" if len(sys.argv) > 1 else Path("package/dist")
out = Path(__file__).resolve().parent.parent / "pageout" / "assets" / "katex"
out.mkdir(parents=True, exist_ok=True)

css = (pkg / "katex.min.css").read_text(encoding="utf-8")


def face(m):
    block = m.group(0)
    w2 = re.search(r"url\((fonts/[^)]+?\.woff2)\)", block)
    if not w2:
        return ""
    data = base64.b64encode((pkg / w2.group(1)).read_bytes()).decode()
    return re.sub(r"src:[^;}]+", f'src:url(data:font/woff2;base64,{data}) format("woff2")', block, count=1)


css = re.sub(r"@font-face\{[^}]*\}", face, css)
(out / "katex.inline.css").write_text(css, encoding="utf-8")
shutil.copy(pkg / "katex.min.js", out / "katex.min.js")
lic = pkg.parent / "LICENSE"
if lic.exists():
    shutil.copy(lic, out / "LICENSE")
print("wrote", out, {p.name: p.stat().st_size for p in out.iterdir()})
