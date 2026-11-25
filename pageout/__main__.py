"""python -m pageout  ->  GUI (no arguments) or CLI (with arguments)."""

import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        from pageout.cli import main as cli_main

        return cli_main(argv)
    from pageout.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
