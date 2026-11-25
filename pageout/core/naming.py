"""File-name templates and date formatting."""

import re
import sys
from datetime import datetime

_DATE_FMT_MAP = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "MMM DD, YYYY": "%b %d, %Y",
    "MMMM D, YYYY": "%B %-d, %Y" if sys.platform != "win32" else "%B %#d, %Y",
    "D MMM YYYY": "%-d %b %Y" if sys.platform != "win32" else "%#d %b %Y",
    "ISO 8601": "%Y-%m-%dT%H:%M:%SZ",
    "Relative": None,  # handled specially
}


def format_date(iso_str: str, fmt_preset: str) -> str:
    """Format an ISO date string using the given preset or strftime pattern."""
    if not iso_str:
        return ""
    # Relative
    if fmt_preset == "Relative":
        try:
            d = datetime.fromisoformat(iso_str[:10])
            delta = (datetime.now() - d).days
            if delta == 0:
                return "Today"
            if delta == 1:
                return "Yesterday"
            if delta < 0:
                return f"In {-delta} days"
            if delta < 30:
                return f"{delta} days ago"
            if delta < 365:
                return f"{delta // 30} months ago"
            return f"{delta // 365} years ago"
        except Exception:
            return iso_str[:10]
    strfmt = _DATE_FMT_MAP.get(fmt_preset, fmt_preset)
    if strfmt is None:
        return iso_str[:10]
    try:
        return datetime.fromisoformat(iso_str[:10]).strftime(strfmt)
    except Exception:
        return iso_str[:10]


def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return re.sub(r"\s+", " ", name).strip()


def apply_fmt(value, fmt):
    if not fmt:
        return value
    if fmt.isdigit():
        return value[: int(fmt)]
    try:
        return datetime.fromisoformat(value[:10]).strftime(fmt)
    except Exception:
        return value


def build_name(template, fields):
    """{title} {date} {index} {created} {edited} {parent} {any property}.
    Extras: {date:%d-%m-%Y} formats dates, {title:40} truncates."""

    def repl(m):
        raw = m.group(1).strip()
        if raw.lower() in fields:
            return str(fields[raw.lower()])
        key, _, fmt = raw.partition(":")
        return apply_fmt(str(fields.get(key.strip().lower(), "")), fmt.strip())

    name = re.sub(r"\{([^{}]+)\}", repl, template)
    name = clean_filename(name)
    name = re.sub(r"(?:\s-)(?:\s-)+\s", " - ", name)
    name = re.sub(r"^[\s\-_.,]+|[\s\-_.,]+$", "", name)
    return (name or "Untitled")[:150].strip()
