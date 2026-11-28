"""Command line interface:  pageout export <url> --format pdf,md --out DIR

Settings are layered (later wins):  built-in defaults < ~/.notion_pdf_exporter/config.json
< pageout.yaml (--config) < command-line flags.
"""

import argparse
import json
import os
import sys
import threading
from datetime import datetime

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
from pageout.core.profiles import (
    delete_profile,
    list_profiles,
    load_profile,
    merge_profile_into_config,
    profile_exists,
    save_profile,
)
from pageout.core.scheduler import (
    add_schedule,
    disable_schedule,
    enable_schedule,
    list_schedules,
    remove_schedule,
)
from pageout.core.sources import (
    add_source,
    delete_source,
    get_source,
    list_sources,
    source_exists,
    toggle_pin,
)

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
    # Profile support
    e.add_argument("--profile", help="load named profile before applying other settings")
    e.add_argument("--save-profile", help="save current settings as named profile")
    e.add_argument("--list-profiles", action="store_true", help="list saved profiles and exit")
    # Source support
    e.add_argument("--source", help="load named source (recent database/page)")
    e.add_argument("--list-sources", action="store_true", help="list saved sources and exit")
    # Phase 16: Sync support
    e.add_argument(
        "--sync-target",
        choices=["None", "Local folder", "Google Drive", "Dropbox", "S3", "Git repo"],
        help="sync target for post-export",
    )
    e.add_argument("--sync-path", help="local/network folder path for sync")
    e.add_argument("--sync-branch", default="main", help="git branch for Git sync")
    e.add_argument("--sync-after", action="store_true", help="sync after export completes")

    sub.add_parser("version", help="print the version")
    i = sub.add_parser("init-config", help="write an example pageout.yaml")
    i.add_argument("path", nargs="?", default="pageout.yaml")

    # Profile subcommands
    ps = sub.add_parser("profile", help="manage saved profiles")
    ps_sub = ps.add_subparsers(dest="profile_cmd")
    ps_list = ps_sub.add_parser("list", help="list all profiles")
    ps_save = ps_sub.add_parser("save", help="save current config as a profile")
    ps_save.add_argument("name", help="profile name")
    ps_load = ps_sub.add_parser("load", help="load a profile and print merged config")
    ps_load.add_argument("name", help="profile name")
    ps_delete = ps_sub.add_parser("delete", help="delete a profile")
    ps_delete.add_argument("name", help="profile name")

    # Source subcommands
    ss = sub.add_parser("source", help="manage saved sources (databases/pages)")
    ss_sub = ss.add_subparsers(dest="source_cmd")
    ss_list = ss_sub.add_parser("list", help="list all saved sources")
    ss_add = ss_sub.add_parser("add", help="add a new source")
    ss_add.add_argument("name", help="source name")
    ss_add.add_argument("url", help="Notion database/page URL or ID")
    ss_add.add_argument(
        "--type", choices=["Auto-detect", "Database", "Page"], default="Auto-detect", help="source type"
    )
    ss_add.add_argument("--pin", action="store_true", help="pin this source")
    ss_delete = ss_sub.add_parser("delete", help="delete a source")
    ss_delete.add_argument("name", help="source name")
    ss_pin = ss_sub.add_parser("pin", help="toggle pin status of a source")
    ss_pin.add_argument("name", help="source name")

    # Queue subcommands
    qs = sub.add_parser("queue", help="manage export queue")
    qs_sub = qs.add_subparsers(dest="queue_cmd")
    qs_list = qs_sub.add_parser("list", help="list all jobs in the queue")
    qs_add = qs_sub.add_parser("add", help="add current settings as a job to the queue")
    qs_add.add_argument("--name", help="job name")
    qs_add.add_argument("--priority", choices=["low", "normal", "high"], default="normal", help="job priority")
    qs_cancel = qs_sub.add_parser("cancel", help="cancel a job")
    qs_cancel.add_argument("job_id", help="job ID to cancel")
    qs_retry = qs_sub.add_parser("retry", help="retry a failed/cancelled job")
    qs_retry.add_argument("job_id", help="job ID to retry")
    qs_remove = qs_sub.add_parser("remove", help="remove a job from queue (non-running)")
    qs_remove.add_argument("job_id", help="job ID to remove")
    qs_clear = qs_sub.add_parser("clear", help="clear completed/failed/cancelled history")
    qs_stats = qs_sub.add_parser("stats", help="show queue statistics")

    # Schedule subcommands
    ss = sub.add_parser("schedule", help="manage scheduled exports")
    ss_sub = ss.add_subparsers(dest="schedule_cmd")
    ss_list = ss_sub.add_parser("list", help="list all scheduled tasks")
    ss_add = ss_sub.add_parser("add", help="add a new scheduled task")
    ss_add.add_argument("name", help="schedule name")
    ss_add.add_argument("source", help="Notion database/page URL or ID")
    ss_add.add_argument("schedule", help="schedule expression (cron: * * * * * or Windows: daily/at HH:MM)")
    ss_add.add_argument("--output", "-o", default="./exports", help="output directory")
    ss_add.add_argument("--format", "-f", required=True, help="output format(s): pdf,md,html,txt,docx,json,tex")
    ss_add.add_argument("--filter-prop", help="property to filter by")
    ss_add.add_argument("--filter-op", choices=["contains", "does not contain", "equals"], default="contains")
    ss_add.add_argument("--filter-value", help="filter value")
    ss_add.add_argument(
        "--sort-by", choices=["Date", "Title", "Created", "Last edited", "Database order"], default="Date"
    )
    ss_add.add_argument("--sort-desc", action="store_true", help="sort descending")
    ss_add.add_argument("--group-by", help="property to group by")
    ss_remove = ss_sub.add_parser("remove", help="remove a scheduled task")
    ss_remove.add_argument("name", help="schedule name to remove")
    ss_enable = ss_sub.add_parser("enable", help="enable a disabled schedule")
    ss_enable.add_argument("name", help="schedule name to enable")
    ss_disable = ss_sub.add_parser("disable", help="disable an active schedule")

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

    # Profile support - load profile FIRST so CLI args can override it
    if args.profile:
        if not profile_exists(args.profile):
            raise UsageError(
                f"Profile '{args.profile}' not found. Use 'pageout profile list' to see available profiles."
            )
        profile_data = load_profile(args.profile)
        merge_profile_into_config(profile_data, cfg)

    # Source support - load saved source (sets database and source_type)
    if args.source:
        src = get_source(args.source)
        if not src:
            raise UsageError(f"Source '{args.source}' not found. Use 'pageout source list' to see available sources.")
        cfg["database"] = src["url"]
        cfg["source_type"] = src.get("source_type", "Auto-detect")
        cfg["sources"] = src.get("sources", [])
        # Load filter/sort/group_by settings from source
        if src.get("filter_prop"):
            cfg["filter_prop"] = src["filter_prop"]
        if src.get("filter_op"):
            cfg["filter_op"] = src["filter_op"]
        if src.get("filter_value"):
            cfg["filter_value"] = src["filter_value"]
        if src.get("sort_by"):
            cfg["sort_by"] = src["sort_by"]
        cfg["sort_desc"] = bool(src.get("sort_desc", False))
        cfg["max_pages"] = int(src.get("max_pages", 0))
        if src.get("group_by"):
            cfg["group_by"] = src["group_by"]
        if src.get("workspace"):
            cfg["workspace"] = src["workspace"]

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

    # Phase 16: Sync configuration
    if args.sync_target:
        cfg["sync_target"] = args.sync_target
    if args.sync_path:
        cfg["sync_path"] = args.sync_path
    if args.sync_branch:
        cfg["sync_branch"] = args.sync_branch
    if args.sync_after:
        cfg["sync_after_export"] = True

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

    # Profile subcommands
    if args.cmd == "profile":
        if args.profile_cmd == "list":
            profiles = list_profiles()
            if profiles:
                for p in profiles:
                    print(p, file=out)
            else:
                print("No profiles saved.", file=out)
            return EXIT_OK
        elif args.profile_cmd == "save":
            cfg = load_config()
            # Filter out secrets
            for key in ("token", "gemini_api_key"):
                if key in cfg:
                    cfg[key] = ""
            save_profile(args.name, cfg)
            print(f"Profile '{args.name}' saved.", file=out)
            return EXIT_OK
        elif args.profile_cmd == "load":
            if not profile_exists(args.name):
                print(f"Profile '{args.name}' not found.", file=err)
                return EXIT_USAGE
            cfg = load_config()
            profile_data = load_profile(args.name)
            merge_profile_into_config(profile_data, cfg)
            # Filter out secrets before printing
            for key in ("token", "gemini_api_key"):
                if key in cfg:
                    cfg[key] = ""
            print(json.dumps(cfg, indent=2), file=out)
            return EXIT_OK
        elif args.profile_cmd == "delete":
            if not profile_exists(args.name):
                print(f"Profile '{args.name}' not found.", file=err)
                return EXIT_USAGE
            delete_profile(args.name)
            print(f"Profile '{args.name}' deleted.", file=out)
            return EXIT_OK
        else:
            build_parser().print_help(out)
            return EXIT_USAGE

    # Source subcommands
    if args.cmd == "source":
        if args.source_cmd == "list":
            sources = list_sources()
            if sources:
                for s in sources:
                    pin_mark = "📌 " if s.get("pinned") else "  "
                    print(f"{pin_mark}{s['name']}  ({s.get('source_type', 'Auto-detect')})  {s['url'][:80]}", file=out)
            else:
                print("No sources saved.", file=out)
            return EXIT_OK
        elif args.source_cmd == "add":
            if not args.name or not args.url:
                build_parser().print_help(err)
                return EXIT_USAGE
            add_source(args.name, args.url, args.type, args.pin)
            print(f"Source '{args.name}' added.", file=out)
            return EXIT_OK
        elif args.source_cmd == "delete":
            if not source_exists(args.name):
                print(f"Source '{args.name}' not found.", file=err)
                return EXIT_USAGE
            delete_source(args.name)
            print(f"Source '{args.name}' deleted.", file=out)
            return EXIT_OK
        elif args.source_cmd == "pin":
            if not source_exists(args.name):
                print(f"Source '{args.name}' not found.", file=err)
                return EXIT_USAGE
            new_status = toggle_pin(args.name)
            print(f"Source '{args.name}' {'pinned' if new_status else 'unpinned'}.", file=out)
            return EXIT_OK
        else:
            build_parser().print_help(out)
            return EXIT_USAGE

    # Queue subcommands
    if args.cmd == "queue":
        from pageout.core.queue import ExportQueue, JobPriority

        q = ExportQueue()
        if args.queue_cmd == "list":
            jobs = q.get_all_jobs()
            if not jobs:
                print("Queue is empty.", file=out)
                return EXIT_OK
            for job in jobs:
                status = job.status.value
                priority = job.priority.name
                created = job.created_at[:19].replace("T", " ")
                print(f"{job.id}  [{status}]  [{priority}]  {created}  {job.name}", file=out)
                if job.message:
                    print(f"    {job.message}", file=out)
            return EXIT_OK
        elif args.queue_cmd == "add":
            cfg = load_config()
            # Filter out secrets before adding to queue
            for key in ("token", "gemini_api_key"):
                if key in cfg:
                    cfg[key] = ""
            priority_map = {"low": JobPriority.LOW, "normal": JobPriority.NORMAL, "high": JobPriority.HIGH}
            job_id = q.add_job(
                name=args.name or f"CLI Export {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                config=cfg,
                priority=priority_map[args.priority],
            )
            print(f"Job added to queue: {job_id}", file=out)
            return EXIT_OK
        elif args.queue_cmd == "cancel":
            if q.cancel_job(args.job_id):
                print(f"Job {args.job_id} cancelled.", file=out)
            else:
                print(f"Job {args.job_id} not found.", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.queue_cmd == "retry":
            if q.retry_job(args.job_id):
                print(f"Job {args.job_id} queued for retry.", file=out)
            else:
                print(f"Job {args.job_id} not found or not retryable.", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.queue_cmd == "remove":
            if q.remove_job(args.job_id):
                print(f"Job {args.job_id} removed.", file=out)
            else:
                print(f"Job {args.job_id} not found or cannot be removed (running).", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.queue_cmd == "clear":
            q.clear_history()
            print("Queue history cleared.", file=out)
            return EXIT_OK
        elif args.queue_cmd == "stats":
            stats = q.get_stats()
            for status, count in stats.items():
                print(f"{status}: {count}", file=out)
            return EXIT_OK
        else:
            build_parser().print_help(out)
            return EXIT_USAGE

    # Schedule subcommands
    if args.cmd == "schedule":
        if args.schedule_cmd == "list":
            schedules = list_schedules()
            from pageout.core.scheduler import get_platform

            platform_name = get_platform()
            if schedules:
                for s in schedules:
                    status_mark = "✓" if s.status.value == "active" else "⊘"
                    print(f"{status_mark} {s.name} [{s.schedule}] ({platform_name}) -> {s.output_dir}", file=out)
            else:
                print("No schedules saved.", file=out)
            return EXIT_OK
        elif args.schedule_cmd == "add":
            if not args.name or not args.source or not args.schedule:
                build_parser().print_help(err)
                return EXIT_USAGE
            try:
                formats = args.format.split(",") if isinstance(args.format, str) else args.format
                task_id = add_schedule(
                    name=args.name,
                    source=args.source,
                    output_dir=args.output,
                    formats=formats,
                    schedule=args.schedule,
                    filter_prop=args.filter_prop or "",
                    filter_op=args.filter_op or "contains",
                    filter_value=args.filter_value or "",
                    sort_by=args.sort_by or "Date",
                    sort_desc=args.sort_desc,
                    group_by=args.group_by or "",
                )
                print(f"Schedule '{args.name}' added with ID: {task_id}", file=out)
            except ValueError as e:
                print(f"error: {e}", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.schedule_cmd == "remove":
            if not args.name:
                build_parser().print_help(err)
                return EXIT_USAGE
            if remove_schedule(args.name):
                print(f"Schedule '{args.name}' removed.", file=out)
            else:
                print(f"Schedule '{args.name}' not found.", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.schedule_cmd == "enable":
            if not args.name:
                build_parser().print_help(err)
                return EXIT_USAGE
            if enable_schedule(args.name):
                print(f"Schedule '{args.name}' enabled.", file=out)
            else:
                print(f"Schedule '{args.name}' not found.", file=err)
                return EXIT_USAGE
            return EXIT_OK
        elif args.schedule_cmd == "disable":
            if not args.name:
                build_parser().print_help(err)
                return EXIT_USAGE
            if disable_schedule(args.name):
                print(f"Schedule '{args.name}' disabled.", file=out)
            else:
                print(f"Schedule '{args.name}' not found.", file=err)
                return EXIT_USAGE
            return EXIT_OK
        else:
            build_parser().print_help(out)
            return EXIT_USAGE

    if args.cmd != "export":
        build_parser().print_help(out)
        return EXIT_USAGE

    # Handle --list-profiles, --save-profile, --list-sources on export command
    if args.list_profiles:
        profiles = list_profiles()
        if profiles:
            for p in profiles:
                print(p, file=out)
        else:
            print("No profiles saved.", file=out)
        return EXIT_OK

    if args.list_sources:
        sources = list_sources()
        if sources:
            for s in sources:
                pin_mark = "📌 " if s.get("pinned") else "  "
                print(f"{pin_mark}{s['name']}  ({s.get('source_type', 'Auto-detect')})  {s['url'][:80]}", file=out)
        else:
            print("No sources saved.", file=out)
        return EXIT_OK

    if args.save_profile:
        cfg = load_config()
        for key in ("token", "gemini_api_key"):
            if key in cfg:
                cfg[key] = ""
        save_profile(args.save_profile, cfg)
        print(f"Profile '{args.save_profile}' saved.", file=out)
        return EXIT_OK

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
