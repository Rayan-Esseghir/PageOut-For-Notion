"""PageOut for Notion - launcher.

Kept so existing shortcuts and the PyInstaller build scripts keep working. The code lives in
the ``pageout`` package:  GUI (no arguments) or CLI (``python notion_exporter.py export ...``).
"""

from pageout.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
