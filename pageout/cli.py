"""Command line interface:  pageout export <url> --format pdf,md --out DIR

Settings are layered (later wins):  built-in defaults < ~/.notion_pdf_exporter/config.json
< pageout.yaml (--config) < command-line flags.
"""

import argparse
import json
import os
import sys
import threading

from pageout.core.config import (
    APP_NAME,
    APP_STAGE,
    APP_VERSION,
    DB_EXPORT_MODES,
    DEFAULTS,
    ENGINES,
    FORMATS,
    LINK_MODES,
    MD_PRESETS,
    SUB_MODES,
    load_config,
)
from pageout.core.errors import Cancelled
from pageout.core.pipeline import export

FORMAT_ALIASES = {"markdown": "md", "text": "txt", "word": "docx", "latex": "tex"}
ALL_FORMATS = FORMATS + ["images"]
EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, EXIT_CANCEL = 0, 1, 2, 130


class UsageError(Exception):
    pass


def pick(value, options, what):
    """Match a friendly CLI value ('inline') to a config label ('Inline in parent')."""
    v = str(value).strip().lower()
    for o in options:
        if o.lower() == v:
            return o
    hits = [o for o in options if o.lower().startswith(v) or v in o.lower().split("(")[0].split()]
    if len(hits) == 1:
        return hits[0]
    raise UsageError(f"Invalid {what} '{value}'. Choose one of: " + ", ".join(options))


def parse_formats(text):
    out = []
    for f in str(text).replace(";", ",").split(","):
        f = f.strip().lower()
        if not f:
            continue
        f = FORMAT_ALIASES.get(f, f)
        if f not in ALL_FORMATS:
            raise UsageError(f"Unknown format '{f}'. Choose from: {', '.join(ALL_FORMATS)}")
        out.append(f)
    return out


def set_formats(cfg, formats):
    for f in ALL_FORMATS:
        cfg["fmt_" + f] = f in formats


def coerce(key, raw):
    if key not in DEFAULTS:
        raise UsageError(f"Unknown setting '{key}'. See the keys in README / pageout.yaml.")
    default = DEFAULTS[key]
    if isinstance(raw, str):
        if isinstance(default, bool):
            if raw.lower() in ("1", "true", "yes", "on"):
                return True
            if raw.lower() in ("0", "false", "no", "off"):
                return False
            raise UsageError(f"Setting '{key}' needs true/false, got '{raw}'.")
        try:
            if isinstance(default, int):
                return int(raw)
            if isinstance(default, float):
                return float(raw)
        except ValueError:
            raise UsageError(f"Setting '{key}' needs a number, got '{raw}'.")
    return raw


def read_settings_file(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError:
                raise UsageError("Reading YAML needs PyYAML:  pip install pyyaml  (or use a .json / .toml file)")
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        elif ext == ".toml":
            import tomllib

            with open(path, "rb") as f:
                data = tomllib.load(f)
        else:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
    except FileNotFoundError:
        raise UsageError(f"Config file not found: {path}")
    except UsageError:
        raise
    except Exception as e:
        raise UsageError(f"Cannot read {path}: {e}")
    if not isinstance(data, dict):
        raise UsageError(f"{path} must contain a mapping of settings.")
    return data


def apply_settings(cfg, data, warn=print):
    """Merge a settings mapping (friendly aliases + raw config keys) into ``cfg``."""
    for key, value in data.items():
        if key == "formats":
            set_formats(cfg, parse_formats(",".join(value) if isinstance(value, list) else value))
        elif key in ("out", "output"):
            cfg["save_dir"] = str(value)
        elif key in ("source", "sources"):
            cfg["database"] = " ".join(value) if isinstance(value, list) else str(value)
        elif key == "hooks":
            cfg["hooks"] = [str(x) for x in (value if isinstance(value, list) else [value])]
        elif key in ("token", "gemini_api_key"):
            warn(f"Ignoring '{key}' in the settings file: keep secrets in the keyring or environment.")
        else:
            cfg[key] = coerce(key, value)
    return cfg


def build_parser():
    p = argparse.ArgumentParser(prog="pageout", description=f"{APP_NAME} {APP_VERSION} ({APP_STAGE})")
    sub = p.add_subparsers(dest="cmd")
    e = sub.add_parser("export", help="export Notion pages (or an export zip)")
    e.add_argument("sources", nargs="*", help="page / database URLs or ids")
    e.add_argument("--zip", help="read a Notion export .zip instead of the API (offline, experimental)")
    e.add_argument("-f", "--format", help="comma list: " + ",".join(ALL_FORMATS))
    e.add_argument("-o", "--out", help="output folder")
    e.add_argument("-c", "--config", help="settings file (.yaml / .json / .toml)")
    e.add_argument("--token", help="Notion token (prefer NOTION_TOKEN or the keyring)")
    e.add_argument("--engine", choices=["api", "browser"])
    e.add_argument("--sub-pages", choices=["skip", "inline", "separate"])
    e.add_argument("--links", choices=["keep", "remove", "external-only"])
    e.add_argument("--name-format", help="file name template, e.g. '{date} - {title}'")
    e.add_argument("--md-preset", help="Markdown flavour: " + "/".join(MD_PRESETS))
    e.add_argument("--db-export", help="database extra: " + "/".join(DB_EXPORT_MODES))
    e.add_argument("--max-pages", type=int)
    e.add_argument("--hooks", action="append", help="hook .py file (repeatable)")
    e.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="any setting (repeatable)")
    e.add_argument("--force", action="store_true", help="re-export even if nothing changed")
    e.add_argument("--no-incremental", action="store_true")
    e.add_argument("--no-rewrite-links", action="store_true")
    e.add_argument("--profile-timing", action="store_true", help="write timing_report.json with export profiling data")
    e.add_argument("-q", "--quiet", action="store_true")
    sub.add_parser("version", help="print the version")
    i = sub.add_parser("init-config", help="write an example pageout.yaml")
    i.add_argument("path", nargs="?", default="pageout.yaml")
    return p


EXAMPLE_YAML = """# pageout.yaml - every key of the app's settings works here (see README).
sources:
  - https://www.notion.so/your-database-or-page-url
formats: [pdf, md, html]          # pdf html md txt docx json tex images
out: ./export
name_format: "{date} - {title}"
sub_mode: Inline in parent          # Skip | Inline in parent | Separate files
md_preset: GFM                      # GFM | Vanilla | Obsidian
incremental: true                   # skip pages that did not change
# hooks: [./my_hooks.py]            # see examples/hooks_example.py
# The token is NOT read from this file: use NOTION_TOKEN or the OS keyring.
"""


def make_config(args, warn):
    cfg = load_config()
    if args.config:
        apply_settings(cfg, read_settings_file(args.config), warn)
    if args.format:
        set_formats(cfg, parse_formats(args.format))
    if args.sources:
        cfg["database"] = " ".join(args.sources)
    if args.out:
        cfg["save_dir"] = args.out
    if args.token:
        cfg["token"] = args.token
    if args.engine:
        cfg["engine"] = ENGINES[0 if args.engine == "api" else 1]
    if args.sub_pages:
        cfg["sub_mode"] = pick(args.sub_pages, SUB_MODES, "sub-pages mode")
    if args.links:
        cfg["links"] = {"keep": LINK_MODES[0], "remove": LINK_MODES[1], "external-only": LINK_MODES[2]}[args.links]
    if args.name_format:
        cfg["name_format"] = args.name_format
    if args.md_preset:
        cfg["md_preset"] = pick(args.md_preset, MD_PRESETS, "Markdown preset")
    if args.db_export:
        cfg["db_export"] = pick(args.db_export, DB_EXPORT_MODES, "database export mode")
    if args.max_pages is not None:
        cfg["max_pages"] = args.max_pages
    if args.hooks:
        cfg["hooks"] = list(cfg.get("hooks") or []) + args.hooks
    for item in args.set:
        if "=" not in item:
            raise UsageError(f"--set needs KEY=VALUE, got '{item}'")
        k, _, v = item.partition("=")
        cfg[k.strip()] = coerce(k.strip(), v)
    if args.force:
        cfg["force"] = True
    if args.no_incremental:
        cfg["incremental"] = False
    if args.no_rewrite_links:
        cfg["rewrite_links"] = False
    if args.profile_timing:
        cfg["profile_timing"] = True
    if not any(cfg.get("fmt_" + f) for f in ALL_FORMATS):
        raise UsageError("No format selected. Use --format, e.g. --format pdf,md")
    if not str(cfg.get("save_dir", "")).strip():
        raise UsageError("No output folder. Use --out DIR")
    return cfg


def main(argv=None, notion=None, stdout=None, stderr=None):
    out, err = stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    if args.cmd == "version":
        print(f"{APP_NAME} {APP_VERSION} ({APP_STAGE})", file=out)
        return EXIT_OK
    if args.cmd == "init-config":
        if os.path.exists(args.path):
            print(f"{args.path} already exists - not overwritten.", file=err)
            return EXIT_USAGE
        with open(args.path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_YAML)
        print(f"Wrote {args.path}", file=out)
        return EXIT_OK
    if args.cmd != "export":
        build_parser().print_help(out)
        return EXIT_USAGE
    try:
        cfg = make_config(args, lambda m: print("warning: " + m, file=err))
        documents = None
        if args.zip:
            import zipfile

            from pageout.sources.notion_zip import ZipSource

            try:
                documents = ZipSource(args.zip).documents()
            except (OSError, zipfile.BadZipFile) as e:
                raise UsageError(f"Cannot read the zip file '{args.zip}': {e}")
            if not documents:
                raise UsageError("The zip contains no Markdown pages (export from Notion as 'Markdown & CSV').")
        elif notion is None and not cfg.get("token"):
            raise UsageError("No Notion token. Set NOTION_TOKEN, store it in the app, or pass --token.")
        elif not str(cfg.get("database", "")).strip():
            raise UsageError("Nothing to export. Pass a page/database URL (or --zip).")
    except UsageError as e:
        print(f"error: {e}", file=err)
        return EXIT_USAGE

    cancel = threading.Event()
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=err))
    try:
        res = export(cfg, log=log, cancel=cancel, notion=notion, documents=documents)
    except KeyboardInterrupt:
        cancel.set()
        print("Cancelled.", file=err)
        return EXIT_CANCEL
    except Cancelled:
        print("Cancelled.", file=err)
        return EXIT_CANCEL
    except Exception as e:
        from pageout.core.secrets import redact

        print("error: " + redact(e, [cfg.get("token", ""), cfg.get("gemini_api_key", "")]), file=err)
        return EXIT_PROBLEMS
    msg = f"Exported {res.total - res.skipped} page(s)"
    if res.skipped:
        msg += f", {res.skipped} unchanged (skipped)"
    if res.timing and res.timing.summary():
        msg += f" · {res.timing.summary()}"
    print(f"{msg} -> {res.out_dir}", file=out)
    for what, why in res.failed[:20]:
        print(f"  problem: {what}: {why}", file=err)
    return EXIT_PROBLEMS if res.failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
